from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openai.types.responses import Response, ResponseFunctionToolCall
from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition
from test_conversation_api import FakeRunner, mia_dealership_id
from turn_client import post_and_wait

from autoassist.app import create_app
from autoassist.chat.answers import GroundedAnswer
from autoassist.chat.openai import create_openai_runner
from autoassist.config import Settings, load_runtime_config


@pytest.mark.parametrize("with_key", [False, True])
def test_default_openai_wiring_and_missing_key(tmp_path, monkeypatch, with_key):
    config = load_runtime_config(Path("config/dealerships.json"))
    assert all(d.default_connection == "primary-openai" for d in config.dealerships)
    for connection in config.connections.values():
        monkeypatch.delenv(connection.api_key_env, raising=False)
    runner = FakeRunner()
    calls = []

    def factory(model, key, inventory):
        calls.append((model, key))
        return runner

    monkeypatch.setattr("autoassist.app.create_openai_runner", factory)
    if with_key:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))
    with TestClient(app) as client:
        response = post_and_wait(
            client,
            f"/dealerships/{mia_dealership_id(client)}/conversations",
            json={"creation_id": str(uuid4())},
        )
        assert response.status_code == (201 if with_key else 503)
    assert calls == ([("gpt-5.6-luna", "test-key")] if with_key else [])
    assert runner.closed is with_key


async def test_openai_responses_tool_request_bounds_and_cleanup(monkeypatch):
    runner = create_openai_runner("gpt-5.6-luna", "test-key", None)
    model = runner._agent.model.wrapped
    client = model.provider.client
    assert client.timeout == 30.0
    assert client.max_retries == 0

    create = AsyncMock(
        return_value=Response(
            id="resp_test",
            created_at=1_789_000_000,
            model="gpt-5.6-luna",
            object="response",
            output=[
                ResponseFunctionToolCall(
                    arguments='{"make":"Toyota"}',
                    call_id="call_test",
                    name="search_inventory",
                    type="function_call",
                )
            ],
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
            status="completed",
        )
    )
    monkeypatch.setattr(client.responses, "create", create)
    close = AsyncMock(wraps=client.close)
    monkeypatch.setattr(client, "close", close)
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
        sent = create.call_args.kwargs
        assert sent["model"] == "gpt-5.6-luna"
        assert sent["max_output_tokens"] == 2048
        assert sent["parallel_tool_calls"] is False
        assert "search_inventory" in str(sent["tools"])
        assert "final_result" in str(sent["tools"])
    finally:
        await runner.close()
    close.assert_awaited_once()
