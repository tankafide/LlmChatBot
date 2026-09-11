import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition
from test_conversation_api import FakeRunner, mia_dealership_id

from autoassist.app import create_app
from autoassist.chat.answers import GroundedAnswer
from autoassist.chat.contracts import ChatProviderError, ChatProviderTimeoutError
from autoassist.chat.gemini import create_gemini_runner
from autoassist.config import Settings, load_runtime_config
from autoassist.inventory.importer import InventoryImportService, parse_inventory_csv


@pytest.mark.parametrize("with_key", [False, True])
def test_optional_gemini_wiring(tmp_path, monkeypatch, with_key):
    config = load_runtime_config(Path("config/dealerships.json"))
    assert all(d.default_connection == "primary-openai" for d in config.dealerships)
    for connection in config.connections.values():
        monkeypatch.delenv(connection.api_key_env, raising=False)
    runner = FakeRunner()
    calls = []

    def factory(model, key, inventory):
        calls.append((model, key))
        return runner

    monkeypatch.setattr("autoassist.app.create_gemini_runner", factory)
    if with_key:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))
    with TestClient(app):
        pass
    assert calls == ([("gemini-3.1-flash-lite", "test-key")] if with_key else [])
    assert runner.closed is with_key


async def test_gemini_native_tool_request_bounds_and_cleanup(monkeypatch):
    runner = create_gemini_runner("gemini-3.1-flash-lite", "test-key", None)
    model = runner._agent.model.wrapped
    client = model.provider.client
    options = client._api_client._http_options
    assert options.timeout == 30_000
    assert options.retry_options.attempts == 1
    generate = AsyncMock(
        return_value=types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name="search_inventory", args={"make": "Toyota"}
                                )
                            )
                        ]
                    ),
                    finish_reason="STOP",
                )
            ]
        )
    )
    monkeypatch.setattr(client.aio.models, "generate_content", generate)
    close = AsyncMock(wraps=client.aio.aclose)
    monkeypatch.setattr(client.aio, "aclose", close)
    try:
        response = await model.request(
            [ModelRequest(parts=[UserPromptPart("Find a Toyota")])],
            {"max_tokens": 2048, "parallel_tool_calls": False},
            ModelRequestParameters(
                output_mode="tool",
                allow_text_output=False,
                function_tools=[
                    ToolDefinition(
                        name="search_inventory",
                        parameters_json_schema={
                            "type": "object",
                            "properties": {"make": {"type": "string"}},
                            "required": ["make"],
                        },
                    )
                ],
                output_tools=[
                    ToolDefinition(
                        name="final_result",
                        parameters_json_schema=GroundedAnswer.model_json_schema(),
                    )
                ],
            ),
        )
        assert isinstance(response.parts[0], ToolCallPart)
        assert response.parts[0].args_as_dict() == {"make": "Toyota"}
        sent = generate.call_args.kwargs
        assert sent["config"]["max_output_tokens"] == 2048
        assert "search_inventory" in str(sent["config"])
        assert "maxItems" not in str(sent["config"])
        assert "At most 10 items." in str(sent["config"])
        assert "At most 9 items." in str(sent["config"])
    finally:
        await runner.close()
    close.assert_awaited_once()


def test_gemini_schema_adaptation_preserves_application_output_limits():
    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate({"intent": "list", "vehicles": [{"vehicle_id": "test"}] * 11})
    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate(
            {"intent": "details", "vehicles": [{"vehicle_id": "test", "fields": ["price"] * 10}]}
        )


@pytest.fixture
def gemini_transport(monkeypatch):
    """Use the real Google SDK, schema mapping and error mapping with fake HTTP only."""
    from google import genai

    real_client = genai.Client

    def install(handler, inventory=None):
        def client(**kwargs):
            kwargs["http_options"].async_client_args = {"transport": httpx.MockTransport(handler)}
            return real_client(**kwargs)

        monkeypatch.setattr("autoassist.chat.gemini.genai.Client", client)
        return create_gemini_runner("gemini-3.1-flash-lite", "test-key", inventory)

    return install


def generation_response():
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "final_result",
                                    "args": {"intent": "unsupported"},
                                }
                            }
                        ],
                    },
                    "finishReason": "STOP",
                }
            ]
        },
    )


async def request_generation(runner):
    return await runner._agent.model.request(
        [ModelRequest(parts=[UserPromptPart("hello")])],
        {"max_tokens": 2048},
        ModelRequestParameters(
            output_mode="tool",
            allow_text_output=False,
            output_tools=[
                ToolDefinition(
                    name="final_result", parameters_json_schema=GroundedAnswer.model_json_schema()
                )
            ],
        ),
    )


@pytest.mark.parametrize("status", [503, 504])
async def test_gemini_recovers_from_temporary_overload_without_changing_request(
    gemini_transport, status
):
    requests = []

    def upstream(request):
        requests.append(request.content)
        if len(requests) < 3:
            return httpx.Response(
                status,
                json={"error": {"code": status, "message": "Temporary failure."}},
            )
        return generation_response()

    runner = gemini_transport(upstream)
    try:
        response = await request_generation(runner)
        assert isinstance(response.parts[0], ToolCallPart)
        assert len(requests) == 3
        assert len(set(requests)) == 1
    finally:
        await runner.close()


@pytest.mark.parametrize(
    "status,attempts", [(503, 3), (504, 3), (400, 1), (401, 1), (429, 1), (500, 1)]
)
async def test_gemini_retry_is_bounded_and_only_for_overload(
    gemini_transport, caplog, status, attempts
):
    calls = 0

    def upstream(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            json={
                "error": {
                    "code": status,
                    "message": "private upstream details: secret",
                    "status": "UNAVAILABLE",
                }
            },
        )

    runner = gemini_transport(upstream)
    try:
        with pytest.raises(ChatProviderTimeoutError if status == 504 else ChatProviderError):
            await request_generation(runner)
        assert calls == attempts
        assert "secret" not in caplog.text
        assert f"status={status}" in caplog.text
    finally:
        await runner.close()


async def test_gemini_cancel_during_overload_backoff_stops_retry(gemini_transport, monkeypatch):
    calls = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    def upstream(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": {"code": 503, "message": "High demand"}})

    async def backoff(_delay):
        entered.set()
        await release.wait()

    monkeypatch.setattr("autoassist.chat.gemini.asyncio.sleep", backoff)
    runner = gemini_transport(upstream)
    task = asyncio.create_task(request_generation(runner))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runner.close()


@pytest.mark.parametrize("recover", [True, False])
def test_generation_retry_does_not_repeat_inventory_tool_or_durable_turn(
    application_settings, monkeypatch, gemini_transport, recover
):
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only")
    calls = 0
    tools = 0

    def upstream(request):
        nonlocal calls
        calls += 1
        parts = json.loads(request.content)["contents"][-1]["parts"]
        result = next((p["functionResponse"] for p in parts if "functionResponse" in p), None)
        if result is None:
            answer = {"name": "get_vehicle_by_stock", "args": {"stock_number": "AA-1001"}}
        elif not recover or calls < 4:
            return httpx.Response(503, json={"error": {"code": 503, "message": "High demand"}})
        else:
            vehicle = result["response"]["vehicle"]
            answer = {
                "name": "final_result",
                "args": {
                    "intent": "details",
                    "vehicles": [{"vehicle_id": vehicle["vehicle_id"], "fields": ["price"]}],
                },
            }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"functionCall": answer}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    app = create_app(
        application_settings, runner_factory=lambda _m, _k, inv: gemini_transport(upstream, inv)
    )
    with TestClient(app) as client:
        dealer = mia_dealership_id(client)
        InventoryImportService(app.state.session_factory).import_records(
            "mia-motors", parse_inventory_csv(Path("docs/context/inventory/data.csv"))
        )
        inventory = app.state.inventory_service
        original = inventory.get_by_source_id

        def lookup(*args):
            nonlocal tools
            tools += 1
            return original(*args)

        monkeypatch.setattr(inventory, "get_by_source_id", lookup)
        conversation = client.post(f"/dealerships/{dealer}/conversations", json={}).json()["id"]
        endpoint = f"/dealerships/{dealer}/conversations/{conversation}/messages"
        body = {"request_id": str(uuid4()), "text": "Select stock AA-1001."}
        response = client.post(endpoint, json=body)
        assert response.status_code == (200 if recover else 502), response.text
        if recover:
            assert "$26,335.00" in response.json()["assistant_message"]["text"]
            assert response.json()["selected_vehicle_id"] is not None
        else:
            assert response.json()["error"]["code"] == "provider_error"
        history = client.get(endpoint).json()
        assert len(history["items"]) == (2 if recover else 1)
        assert history["items"][0]["request_status"] == ("completed" if recover else "failed")
        assert client.post(endpoint, json=body).json() == response.json()
        assert tools == 1
        assert calls == 4  # One tool-call generation, then at most three final-answer attempts.


@pytest.mark.parametrize("retry_after,attempts", [("0", 3), ("60", 1), ("invalid", 1)])
async def test_gemini_does_not_retry_before_retry_after(gemini_transport, retry_after, attempts):
    calls = 0

    def upstream(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            headers={"Retry-After": retry_after},
            json={"error": {"code": 503, "message": "High demand"}},
        )

    runner = gemini_transport(upstream)
    try:
        with pytest.raises(ChatProviderError):
            await request_generation(runner)
        assert calls == attempts
    finally:
        await runner.close()
