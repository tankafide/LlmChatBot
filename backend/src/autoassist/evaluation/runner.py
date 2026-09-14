"""Run labeled customer conversations against the production agent and isolated data."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from pydantic import TypeAdapter
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from sqlalchemy import select

from autoassist.chat.contracts import ChatRunRequest
from autoassist.chat.gemini import create_gemini_runner
from autoassist.chat.grok import create_grok_runner
from autoassist.chat.grounded import INSTRUCTIONS
from autoassist.chat.history import retain_replay
from autoassist.chat.openai import create_openai_runner
from autoassist.config import load_runtime_config
from autoassist.db.bootstrap import bootstrap_dealerships
from autoassist.db.database import create_database_engine, initialize_schema, make_session_factory
from autoassist.db.models import Dealership, Vehicle
from autoassist.evaluation.scoring import ConversationLabel, score_turn
from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.inventory.importer import InventoryImportService, parse_inventory_csv
from autoassist.inventory.repository import InventoryRepository
from autoassist.inventory.service import InventoryService
from autoassist.observability import TurnMetrics, current_turn
from autoassist.safety.service import SafetyService


def load_labels(path: Path) -> list[ConversationLabel]:
    """Load a bounded, uniquely identified conversation evaluation suite.

    Used by both validation-only and live evaluation. Return validated labels; raise
    validation/ValueError for bad data, duplicate IDs, or a count outside 15–25. File errors
    propagate.
    """
    cases = TypeAdapter(list[ConversationLabel]).validate_json(path.read_bytes())
    if not 15 <= len(cases) <= 25 or len({case.id for case in cases}) != len(cases):
        raise ValueError("suite requires 15–25 conversations with unique IDs")
    return cases


def fixture_transport(mode: str) -> httpx.MockTransport:
    """Return a deterministic NHTSA HTTP transport for evaluation scenarios.

    Called for each evaluation conversation. Mode selects unavailable, ambiguous, or empty
    fixtures; no live NHTSA request occurs.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        """Supply a fixture response for one evaluation HTTP request.

        Invoked by MockTransport. Return 503 in unavailable mode; otherwise return empty
        recall data, ambiguous crash choices, or empty crash data according to mode/path.
        """
        if mode == "unavailable":
            return httpx.Response(503)
        if "recalls" in request.url.path:
            return httpx.Response(200, json={"Count": 0, "results": []})
        if mode == "ambiguous":
            return httpx.Response(
                200,
                json={
                    "Count": 2,
                    "Results": [
                        {
                            "VehicleId": 201,
                            "VehicleDescription": "2022 Toyota RAV4 SUV variant alpha",
                        },
                        {
                            "VehicleId": 202,
                            "VehicleDescription": "2022 Toyota RAV4 SUV variant beta",
                        },
                    ],
                },
            )
        return httpx.Response(200, json={"Count": 0, "Results": []})

    return httpx.MockTransport(respond)


def trace(replay: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """Extract tool behavior from a completed replay envelope.

    Called after an evaluation turn succeeds. Return (tool calls, latest final answer, safety
    statuses) via trace_messages; corrupt JSON or library message data raises.
    """
    envelope = json.loads(replay)
    messages = ModelMessagesTypeAdapter.validate_json(envelope["messages_json"])
    return trace_messages(messages)


def trace_messages(
    messages: list[ModelMessage],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """Summarize model calls and tool evidence for scoring or failure reports.

    Called on completed or captured partial messages. Return ordered non-final tool calls, the
    latest final-result arguments (empty if absent), and branch statuses. This describes
    observed messages, not proof of execution success.
    """
    calls: list[dict[str, Any]] = []
    answer: dict[str, Any] = {}
    safety: dict[str, str] = {}
    for message in messages:
        for part in message.parts:
            if isinstance(message, ModelResponse) and isinstance(part, ToolCallPart):
                args = part.args_as_dict()
                if part.tool_name == "final_result":
                    answer = args
                else:
                    calls.append({"name": part.tool_name, "args": args})
            elif isinstance(part, ToolReturnPart) and isinstance(part.content, dict):
                value = part.content
                if "evidence_id" in value and isinstance(value.get("result"), dict):
                    safety[str(value["evidence_id"])] = str(value["result"]["status"])
    return calls, answer, safety


def repair_feedback(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Extract bounded model repair feedback for the local evaluation report.

    Called after each evaluation turn, including failures. Return at most twelve feedback
    entries, clipping string reasons and structured validation details. Return an empty
    list when no retry feedback exists. These report details are separate from payload-free
    operational logs and may contain request-specific validation content.
    """
    feedback: list[dict[str, Any]] = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, RetryPromptPart):
                content = part.content
                feedback.append(
                    {
                        "tool": part.tool_name,
                        "reason": content[:1000]
                        if isinstance(content, str)
                        else [
                            {
                                "type": error["type"],
                                "location": error["loc"],
                                "message": error["msg"],
                            }
                            for error in content[:10]
                        ],
                    }
                )
    return feedback[:12]


async def evaluate(
    config: Path,
    inventory_csv: Path,
    suite: Path,
    connection_name: str,
    repeats: int,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Run labeled conversations against a real configured model using disposable inventory.

    Called only by the live CLI path or an explicit caller. Import the supplied CSV into
    temporary SQLite, mock NHTSA, and repeat scoped cases with retained context. Return a
    report with per-turn checks, metrics, hashes, and aggregate results. Turn failures become
    failed rows; setup/cleanup errors propagate. This function itself has no --live guard and
    makes billed model calls.
    """
    labels = load_labels(suite)
    if case_id is not None:
        labels = [case for case in labels if case.id == case_id]
        if not labels:
            raise ValueError("unknown case ID")
    runtime = load_runtime_config(config)
    connection = runtime.connections[connection_name]
    api_key = os.environ.get(connection.api_key_env)
    if not api_key:
        raise ValueError(f"required environment variable is unset: {connection.api_key_env}")
    rows: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="autoassist-eval-") as directory:
        engine = create_database_engine(f"sqlite:///{Path(directory).as_posix()}/evaluation.db")
        sessions = make_session_factory(engine)
        try:
            initialize_schema(engine)
            bootstrap_dealerships(sessions, runtime)
            InventoryImportService(sessions).import_records(
                "mia-motors", parse_inventory_csv(inventory_csv)
            )
            # Stable evaluation-only IDs make bounded search order reproducible across runs.
            with sessions.begin() as session:
                for vehicle in session.scalars(select(Vehicle)):
                    vehicle.id = str(
                        uuid5(NAMESPACE_URL, f"autoassist-evaluation/{vehicle.source_id}")
                    )
            with sessions() as session:
                dealer = session.scalar(
                    select(Dealership.id).where(Dealership.slug == "mia-motors")
                )
                stocks = {
                    row.id: row.source_id
                    for row in session.execute(select(Vehicle.id, Vehicle.source_id))
                }
            assert dealer is not None
            factory = {
                "openai": create_openai_runner,
                "google": create_gemini_runner,
                "xai": create_grok_runner,
            }[connection.provider]
            runner = factory(
                connection.model, api_key, InventoryService(sessions, InventoryRepository())
            )
            try:
                for repeat in range(repeats):
                    for case in labels:
                        selected = None
                        presented: tuple[str, ...] = ()
                        history: tuple[str, ...] = ()
                        conversation_id = str(uuid4())
                        async with httpx.AsyncClient(
                            transport=fixture_transport(case.safety_fixture)
                        ) as client:
                            runner.set_safety_service(SafetyService(NhtsaClient(client)))
                            for index, label in enumerate(case.turns):
                                metrics = TurnMetrics(conversation_id, str(uuid4()))
                                token = current_turn.set(metrics)
                                started = time.monotonic()
                                row: dict[str, Any] = {
                                    "case": case.id,
                                    "category": case.category,
                                    "repeat": repeat + 1,
                                    "turn": index + 1,
                                    "text": label.text,
                                    "rubric": label.rubric,
                                    "human_review": {
                                        "unsupported_claims": None,
                                        "clarification_quality": None,
                                    },
                                }
                                prior_count = sum(
                                    len(
                                        ModelMessagesTypeAdapter.validate_json(
                                            json.loads(unit)["messages_json"]
                                        )
                                    )
                                    for unit in retain_replay(history)
                                )
                                captured: list[ModelMessage] = []
                                try:
                                    with capture_run_messages() as captured:
                                        async with asyncio.timeout(60):
                                            result = await runner.run(
                                                ChatRunRequest(
                                                    dealer,
                                                    conversation_id,
                                                    metrics.request_id,
                                                    label.text,
                                                    selected,
                                                    presented,
                                                    history,
                                                    time.monotonic() + 60,
                                                )
                                            )
                                    calls, answer, safety = trace(result.replay_json)
                                    checks = score_turn(
                                        label, calls, answer, result.reply, stocks, safety
                                    )
                                    row.update(
                                        reply=result.reply,
                                        calls=calls,
                                        answer=answer,
                                        safety=safety,
                                        checks=checks,
                                        passed=all(checks.values()),
                                        functional_passed=all(
                                            value
                                            for name, value in checks.items()
                                            if name != "tool_choice"
                                        ),
                                    )
                                    history += (result.replay_json,)
                                    if result.presented_vehicle_ids is not None:
                                        presented = result.presented_vehicle_ids
                                    if result.selection_action == "set":
                                        selected = result.selected_vehicle_id
                                    elif result.selection_action == "clear":
                                        selected = None
                                except Exception as exc:
                                    calls, answer, safety = trace_messages(captured[prior_count:])
                                    row.update(
                                        passed=False,
                                        functional_passed=False,
                                        error_category=type(exc).__name__,
                                        calls=calls,
                                        answer=answer,
                                        safety=safety,
                                    )
                                finally:
                                    row.update(
                                        latency_ms=round((time.monotonic() - started) * 1000, 2),
                                        model_calls=metrics.model_calls,
                                        provider_attempts=metrics.provider_attempts,
                                        tool_calls=metrics.tool_calls,
                                        repair_feedback=repair_feedback(captured[prior_count:]),
                                    )
                                    current_turn.reset(token)
                                rows.append(row)
            finally:
                await runner.close()
        finally:
            engine.dispose()
    return {
        "provider": connection.provider,
        "model": connection.model,
        "suite_sha256": hashlib.sha256(suite.read_bytes()).hexdigest(),
        "inventory_sha256": hashlib.sha256(inventory_csv.read_bytes()).hexdigest(),
        "instructions_sha256": hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
        "interface_sha256": hashlib.sha256(
            b"".join(
                (Path(__file__).parents[1] / "chat" / name).read_bytes()
                for name in ("answers.py", "grounded.py", "selection.py", "tools.py")
            )
        ).hexdigest(),
        "safety_source": "controlled HTTP fixtures, not live NHTSA",
        "repeats": repeats,
        "summary": summarize(rows),
        "turns": rows,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a nonempty sequence of evaluation turn reports.

    Called after live evaluation. Return pass rates, category counts, latency percentiles, and
    call totals. Required row keys and at least one row are caller preconditions;
    malformed/empty inputs raise rather than producing invented statistics.
    """
    latencies = sorted(row["latency_ms"] for row in rows)
    categories = sorted({row["category"] for row in rows})
    return {
        "turns": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "automatic_pass_rate": sum(row["passed"] for row in rows) / len(rows),
        "functional_passed": sum(row["functional_passed"] for row in rows),
        "functional_pass_rate": sum(row["functional_passed"] for row in rows) / len(rows),
        "latency_p50_ms": latencies[(len(rows) - 1) // 2],
        "latency_p95_ms": latencies[max(0, (95 * len(rows) + 99) // 100 - 1)],
        "model_calls": sum(row["model_calls"] for row in rows),
        "provider_attempts": sum(row["provider_attempts"] for row in rows),
        "human_review": "pending; automatic checks do not measure all semantic claims",
        "categories": {
            category: {
                "passed": sum(row["passed"] for row in rows if row["category"] == category),
                "turns": sum(row["category"] == category for row in rows),
            }
            for category in categories
        },
    }
