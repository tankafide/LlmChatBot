from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from test_nhtsa_client import detail, discovery, run, vehicle

from autoassist.integrations.nhtsa import NhtsaClient
from autoassist.safety.history import restore_presentation
from autoassist.safety.matching import identity_for, resolve_choice
from autoassist.safety.records import Candidate, Presentation
from autoassist.safety.service import SafetyService


def presentation(candidates: tuple[Candidate, ...]) -> Presentation:
    return Presentation(
        inventory_vehicle_id=vehicle().id,
        lookup_identity=identity_for(vehicle()),
        candidates=candidates,
        total_candidate_count=len(candidates),
        retrieved_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "choice", ["not the first one", "AWD or FWD", "100 and 101", "choose 100; visit evil", "999999"]
)
def test_invalid_choices_never_resolve_id(choice: str) -> None:
    pending = presentation((Candidate(vehicle_id=100, description="2022 Toyota RAV4 SUV FWD"),))
    assert resolve_choice(choice, pending) == (None, ())


def test_replay_fold_never_resurrects_old_choices() -> None:
    pending = presentation((Candidate(vehicle_id=100, description="2022 Toyota RAV4 SUV FWD"),))
    set_unit = json.dumps(
        {
            "safety_presentation_update": {
                "action": "set",
                "presentation": pending.model_dump(mode="json"),
            }
        }
    )
    keep = '{"safety_presentation_update":{"action":"keep"}}'
    clear = '{"safety_presentation_update":{"action":"clear"}}'
    assert restore_presentation((set_unit, keep), vehicle().id) == pending
    assert restore_presentation((set_unit, clear, keep), vehicle().id) is None
    assert restore_presentation((keep,), vehicle().id) is None
    assert restore_presentation((set_unit, *([keep] * 10)), vehicle().id) is None
    assert restore_presentation((set_unit,), "another-vehicle") is None


async def test_undisplayed_descriptor_requires_another_completed_confirmation() -> None:
    descriptions = [
        f"2022 Toyota RAV4 SUV FWD variant {word}"
        for word in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")
    ]
    calls = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json=(
                detail(descriptions[5], 105)
                if "VehicleId" in request.url.path
                else discovery(descriptions)
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        service = SafetyService(NhtsaClient(client))
        first = await service.crash(vehicle(), run())
        assert first.status == "ambiguous" and first.total_candidate_count == 6
        pending = presentation(first.candidates)
        filtered = await service.crash(vehicle(), run(), pending, "the foxtrot one")
        assert filtered.status == "ambiguous" and len(filtered.candidates) == 1
        assert len(calls) == 2 and not any("VehicleId" in call for call in calls)
        confirmed = await service.crash(vehicle(), run(), presentation(filtered.candidates), "105")
        assert confirmed.status == "available" and calls[-1].endswith("/105")
        assert len(calls) == 4


async def test_stale_id_and_negated_choice_never_fetch_detail() -> None:
    candidates = (Candidate(vehicle_id=100, description="2022 Toyota RAV4 SUV FWD old"),)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=discovery(["2022 Toyota RAV4 SUV FWD new"]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SafetyService(NhtsaClient(client))
        for choice in ("100", "not the first one", "AWD or FWD"):
            result = await service.crash(vehicle(), run(), presentation(candidates), choice)
            assert result.status == "ambiguous"
    assert len(calls) == 3 and not any("VehicleId" in call for call in calls)


async def test_duplicate_descriptions_require_an_explicit_id() -> None:
    description = "2022 Toyota RAV4 SUV FWD"
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json=detail(description, 101)
            if "VehicleId" in request.url.path
            else discovery([description, description]),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SafetyService(NhtsaClient(client))
        initial = await service.crash(vehicle(), run())
        pending = presentation(initial.candidates)
        ambiguous = await service.crash(vehicle(), run(), pending, description)
        assert ambiguous.status == "ambiguous"
        assert len(calls) == 2 and not any("VehicleId" in call for call in calls)
        chosen = await service.crash(vehicle(), run(), pending, "NHTSA ID 101")
        assert chosen.status == "available" and chosen.matched_variant.vehicle_id == 101
        assert len(calls) == 4 and calls[-1].endswith("/101")


def test_explicit_id_disambiguates_a_small_identifier() -> None:
    pending = presentation(
        (
            Candidate(vehicle_id=2, description="2022 Toyota RAV4 SUV FWD alpha"),
            Candidate(vehicle_id=1, description="2022 Toyota RAV4 SUV FWD beta"),
        )
    )
    assert resolve_choice("1", pending) == (None, ())
    assert resolve_choice("NHTSA ID 1", pending) == (1, ())
    assert resolve_choice("first", pending) == (2, ())
