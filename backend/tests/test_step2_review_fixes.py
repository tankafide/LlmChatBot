from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import write_config
from pydantic_ai import ModelRetry, RunContext, RunUsage
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.exc import OperationalError
from turn_client import submit_and_wait

from autoassist.app import create_app
from autoassist.chat.answers import GroundedAnswer
from autoassist.chat.budget import MAX_PROVIDER_INPUT_BYTES, BudgetedModel, request_bytes
from autoassist.chat.context import ChatDependencies
from autoassist.chat.contracts import ChatProviderError, ChatRunRequest, ChatRunResult
from autoassist.chat.grounded import PydanticChatRunner
from autoassist.chat.history import MAX_HISTORY_BYTES
from autoassist.config import Settings
from autoassist.inventory.records import VehicleRecord


class Runner:
    def __init__(self):
        self.calls = 0
        self.result = ChatRunResult(reply="done", replay_json='{"messages_json":"[]"}')

    async def run(self, _request):
        self.calls += 1
        return self.result

    async def close(self):
        pass


@pytest.fixture
async def service(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEST_XAI_API_KEY", "test-only")
    runner = Runner()
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'review.db'}",
            config_file=write_config(tmp_path / "config.json"),
        ),
        runner_factory=lambda *_args: runner,
    )
    async with app.router.lifespan_context(app):
        dealer = next(
            x.id for x in app.state.inventory_service.list_dealerships() if x.slug == "mia-motors"
        )
        yield app.state.conversation_service, dealer, runner


@pytest.mark.parametrize("phase", ["admission", "completion"])
async def test_cancellation_drains_owned_write_before_releasing_capacity(
    service, monkeypatch, phase
):
    svc, dealer, runner = service
    conversation = await svc.create(dealer, str(uuid4()))
    name = "_admit_unit_locked" if phase == "admission" else "_complete_unit_locked"
    original = getattr(svc._store, name)
    entered, release = threading.Event(), threading.Event()

    def gated(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(svc._store, name, gated)
    request_id = str(uuid4())
    task = asyncio.create_task(svc.submit(dealer, conversation.id, request_id, "hello"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        if phase == "completion":
            assert (await task).status_code == 202
            task = next(iter(svc._tasks.values()))
        task.cancel()
        # A loop barrier lets cancellation run without assuming a thread scheduling delay.
        await asyncio.sleep(0)
        assert not task.done()
        assert svc._limiter._active == 1
        task.cancel()  # Repeated cancellation must not abandon cleanup either.
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    monkeypatch.setattr(svc._store, name, original)
    if phase == "admission":
        replay = await submit_and_wait(svc, dealer, conversation.id, request_id, "hello")
        assert replay.status_code == 409
        assert replay.body["error"]["code"] == "request_interrupted"
        assert runner.calls == 0
    else:
        assert (
            await submit_and_wait(svc, dealer, conversation.id, request_id, "hello")
        ).status_code == 200
        assert runner.calls == 1
    assert svc._limiter._active == 0
    assert (
        await submit_and_wait(svc, dealer, conversation.id, str(uuid4()), "next")
    ).status_code == 200


async def test_uncertain_admission_commit_reconciles_without_duplicate_provider_run(
    service, monkeypatch
):
    svc, dealer, runner = service
    conversation = await svc.create(dealer, str(uuid4()))
    original = svc._store._admit_unit_locked

    def commit_then_error(*args):
        original(*args)
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise OperationalError("COMMIT", {}, error)

    monkeypatch.setattr(svc._store, "_admit_unit_locked", commit_then_error)
    request_id = str(uuid4())
    first = await submit_and_wait(svc, dealer, conversation.id, request_id, "hello")
    replay = await submit_and_wait(svc, dealer, conversation.id, request_id, "hello")
    assert first == replay
    assert first.status_code == 200
    assert runner.calls == 1
    assert len((await svc.history(dealer, conversation.id, 0, 50)).items) == 2


async def test_cancelled_duplicate_does_not_interrupt_original_turn(service, monkeypatch):
    svc, dealer, runner = service
    conversation = await svc.create(dealer, str(uuid4()))
    request_id = str(uuid4())
    provider_entered, provider_release = asyncio.Event(), asyncio.Event()
    original_run = runner.run

    async def gated_run(request):
        provider_entered.set()
        await provider_release.wait()
        return await original_run(request)

    monkeypatch.setattr(runner, "run", gated_run)
    owner = asyncio.create_task(svc.submit(dealer, conversation.id, request_id, "hello"))
    try:
        await asyncio.wait_for(provider_entered.wait(), 5)
        # Exercise cancellation after duplicate admission classification, not the early replay read.
        original = svc._admit_and_classify
        classified, release = asyncio.Event(), asyncio.Event()

        async def gated_classify(*args):
            result = await original(*args)
            classified.set()
            await release.wait()
            return result

        monkeypatch.setattr(svc, "_admit_and_classify", gated_classify)
        duplicate = asyncio.create_task(
            svc._admit_with_reconciliation(dealer, conversation.id, request_id, "hello")
        )
        try:
            await asyncio.wait_for(classified.wait(), 5)
            duplicate.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await duplicate
        active = await svc.submit(dealer, conversation.id, request_id, "hello")
        assert active.status_code == 202
    finally:
        provider_release.set()
        assert (await owner).status_code == 202
        outcome = await submit_and_wait(svc, dealer, conversation.id, request_id, "hello")
    assert outcome.status_code == 200
    assert runner.calls == 1


@pytest.mark.parametrize(
    "new_size,expected", [(MAX_HISTORY_BYTES - 1000, ("C", "A")), (MAX_HISTORY_BYTES, ())]
)
async def test_presentation_uses_same_byte_suffix_as_replay(service, new_size, expected):
    svc, dealer, runner = service
    conversation = await svc.create(dealer, str(uuid4()))
    runner.result = ChatRunResult(
        reply="1. C 2. A", replay_json="{}", presented_vehicle_ids=("C", "A")
    )
    await submit_and_wait(svc, dealer, conversation.id, str(uuid4()), "list")
    unit = {
        "messages_json": "[]",
        "public_reply": "detail",
        "presented_vehicle_ids": None,
        "padding": "",
    }
    overhead = len(json.dumps(unit, separators=(",", ":")).encode())
    unit["padding"] = "x" * (new_size - overhead)
    runner.result = ChatRunResult(
        reply="detail", replay_json=json.dumps(unit, separators=(",", ":"))
    )
    await submit_and_wait(svc, dealer, conversation.id, str(uuid4()), "detail")
    context = await asyncio.to_thread(svc._store.load_context, dealer, conversation.id)
    assert context.presented_vehicle_ids == expected
    assert sum(len(x.encode()) for x in context.replay_units) <= MAX_HISTORY_BYTES
    assert context.replay_units[-1] == runner.result.replay_json


def vehicle(identifier):
    return VehicleRecord(
        identifier,
        f"STK-{identifier}",
        "Toyota",
        "Camry",
        2024,
        10000,
        "Sedan",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "text,selected,chosen,intent,allowed",
    [
        ("Show me cars", None, "A", "list", False),
        ("Show me cars", "A", "A", "list", False),
        ("The second one", None, "C", "details", False),
        ("The second one", None, "A", "details", True),
        ("The third one", "A", "A", "details", False),
        ("Stock STK-C", None, "A", "details", False),
        ("Stock STK-C", None, "C", "details", True),
        ("Stock STK-UNKNOWN", "A", "A", "details", False),
        ("Compare STK-C and STK-A", None, "C", "details", False),
        ("What is its mileage?", "A", "A", "details", True),
        ("What is its mileage?", None, "A", "details", False),
    ],
)
def test_selection_and_details_follow_user_reference(text, selected, chosen, intent, allowed):
    model = FunctionModel(lambda *_: ModelResponse([TextPart("unused")]))
    request = ChatRunRequest("dealer", "conversation", "request", text, selected, ("C", "A"), ())
    deps = ChatDependencies(
        inventory=None,
        request=request,
        evidence={x: vehicle(x) for x in ("A", "C")},
        search_executed=True,
    )
    ctx = RunContext(deps=deps, model=model, usage=RunUsage())
    answer = GroundedAnswer.model_validate(
        {
            "intent": intent,
            "vehicles": [{"vehicle_id": chosen}],
        }
    )
    runner = PydanticChatRunner(model, None)
    if allowed:
        assert runner._validate_answer(ctx, answer) == answer
    else:
        with pytest.raises(ModelRetry):
            runner._validate_answer(ctx, answer)


async def test_provider_budget_includes_schemas_and_exact_boundary():
    calls = 0

    def model_fn(*_):
        nonlocal calls
        calls += 1
        return ModelResponse([TextPart("ok")])

    model = BudgetedModel(FunctionModel(model_fn))
    messages = [ModelRequest(parts=[UserPromptPart("hello")])]
    params = ModelRequestParameters(
        function_tools=[
            ToolDefinition(name="tool", description="", parameters_json_schema={"type": "object"})
        ]
    )
    settings, prepared = model.prepare_request(None, params)
    base = len(request_bytes(messages, settings, prepared))
    params.function_tools[0].description = "x" * (MAX_PROVIDER_INPUT_BYTES - base)
    assert len(request_bytes(messages, settings, prepared)) == MAX_PROVIDER_INPUT_BYTES
    await model.request(messages, None, params)
    params.function_tools[0].description += "x"
    with pytest.raises(ChatProviderError):
        await model.request(messages, None, params)
    assert calls == 1


@pytest.mark.parametrize(
    "part",
    [
        RetryPromptPart(content="x" * MAX_PROVIDER_INPUT_BYTES),
        ToolReturnPart(tool_name="tool", content="x" * MAX_PROVIDER_INPUT_BYTES),
    ],
)
async def test_every_provider_request_counts_accumulated_tool_and_repair_messages(part):
    calls = 0

    def model_fn(*_):
        nonlocal calls
        calls += 1
        return ModelResponse([TextPart("ok")])

    model = BudgetedModel(FunctionModel(model_fn))
    messages = [ModelRequest(parts=[UserPromptPart("hello")])]
    await model.request(messages, None, ModelRequestParameters())
    messages.append(ModelRequest(parts=[part]))
    with pytest.raises(ChatProviderError):
        await model.request(messages, None, ModelRequestParameters())
    assert calls == 1


async def test_scripted_model_repairs_wrong_ordinal_before_returning_selection():
    calls = 0

    async def scripted(_messages, info):
        nonlocal calls
        calls += 1
        chosen = "C" if calls == 1 else "A"
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "intent": "details",
                        "vehicles": [{"vehicle_id": chosen, "fields": ["price"]}],
                    },
                )
            ]
        )

    class Inventory:
        def get(self, _dealer, vehicle_id):
            return vehicle(vehicle_id)

    runner = PydanticChatRunner(FunctionModel(scripted), Inventory())
    result = await runner.run(
        ChatRunRequest(
            "dealer",
            "conversation",
            "request",
            "the second one",
            None,
            ("C", "A"),
            (),
        )
    )
    assert calls == 2
    assert result.selected_vehicle_id == "A"
    assert "STK-A" in result.reply
    assert "STK-C" not in result.reply
