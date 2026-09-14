from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, TypedDict

from autoassist.integrations.nhtsa import (
    LookupBudget,
    NhtsaClient,
    NhtsaError,
    detail_url,
    discovery_url,
    recall_url,
)
from autoassist.inventory.records import VehicleRecord
from autoassist.safety import parsing
from autoassist.safety.matching import compatibility, identity_for, resolve_choice, tokens
from autoassist.safety.records import CrashResult, Identity, Presentation, RecallResult


class CrashProvenance(TypedDict):
    """Type the common keyword fields used to construct crash results.

    This TypedDict supports static checking only; CrashResult performs runtime validation.
    """

    inventory_vehicle_id: str
    stock_id: str
    lookup_identity: Identity
    source_url: str
    attempted_at: datetime


@dataclass(slots=True)
class SafetyRun:
    """Own one turn safety subject, shared lookup budget, and cached branch results.

    Cache unavailable outcomes too so repeated tools do not refetch within the turn; a run
    cannot switch inventory vehicles.
    """

    budget: LookupBudget
    vehicle_id: str | None = None
    results: dict[str, RecallResult | CrashResult] = field(default_factory=dict)


class SafetyService:
    """Coordinate recall and crash workflows over the bounded NHTSA client.

    Match inventory identity, preserve ambiguity/unavailable states, and produce validated
    evidence; the chat runner renders it and persistence owns follow-up context.
    """

    def __init__(self, client: NhtsaClient) -> None:
        """Attach the NHTSA transport adapter. Return None; requests and caches belong to
        individual SafetyRun instances.

        Constructed during app startup.
        """
        self.client = client

    @staticmethod
    def _claim_vehicle(vehicle: VehicleRecord, run: SafetyRun) -> None:
        """Set or confirm this run single vehicle ID. Return None on success; raise ValueError if a
        safety branch tries to switch inventory vehicles. Both safety branches must describe the
        same inventory vehicle in this turn.

        Called at the start of recalls and crash.
        """
        if run.vehicle_id not in {None, vehicle.id}:
            raise ValueError("one safety run cannot switch inventory vehicles")
        run.vehicle_id = vehicle.id

    async def recalls(self, vehicle: VehicleRecord, run: SafetyRun) -> RecallResult:
        """Return/cache RecallResult with available, empty, or unavailable status. Bound campaign
        output and preserve provenance; expected transport/parsing failures become unavailable
        evidence.

        Called by the recall tool after subject resolution.
        """
        self._claim_vehicle(vehicle, run)
        cached = run.results.get("recalls")
        if isinstance(cached, RecallResult):
            return cached
        # NHTSA searches by inventory year/make/model, not VIN repair status. Source
        # and timestamps travel with the evidence so its scope can be explained.
        identity = identity_for(vehicle)
        url = recall_url(identity)
        attempted = datetime.now(UTC)
        try:
            records = parsing.campaigns(await self.client.get(url, "recalls", run.budget), identity)
            result = RecallResult(
                inventory_vehicle_id=vehicle.id,
                stock_id=vehicle.source_id,
                lookup_identity=identity,
                source_url=url,
                attempted_at=attempted,
                retrieved_at=datetime.now(UTC),
                # Only a successfully parsed empty response establishes no returned campaigns.
                # Network/parsing failures below produce unavailable, not empty.
                status="available" if records else "empty",
                total_count=len(records),
                campaigns=records[:5],
                omitted_count=max(0, len(records) - 5),
                urgent_count=sum(bool(item.park_it or item.park_outside) for item in records),
            )
            # Bound UTF-8 output as well as individual text fields.
            while len(result.model_dump_json().encode()) > 12 * 1024:
                kept = result.campaigns[:-1]
                if not kept:
                    raise NhtsaError("response_limit")
                result = result.model_copy(
                    update={"campaigns": kept, "omitted_count": len(records) - len(kept)}
                )
        except (NhtsaError, parsing.InvalidResponse) as exc:
            result = RecallResult(
                inventory_vehicle_id=vehicle.id,
                stock_id=vehicle.source_id,
                lookup_identity=identity,
                source_url=url,
                attempted_at=attempted,
                status="unavailable",
                reason=exc.reason
                if isinstance(exc, NhtsaError)
                else "response_limit"
                if isinstance(exc, parsing.ResponseLimit)
                else "invalid_response",
            )
        run.results["recalls"] = result
        return result

    async def crash(
        self,
        vehicle: VehicleRecord,
        run: SafetyRun,
        presentation: Presentation | None = None,
        choice_text: str | None = None,
    ) -> CrashResult:
        """Discover/select a variant and return/cache CrashResult:
        available/partial/unrated/no_ratings, no_record, ambiguous, or unavailable. Expected
        lookup failures become evidence; cross-vehicle misuse raises.

        Called by the crash tool, optionally with a previous presentation and current choice
        text.
        """
        self._claim_vehicle(vehicle, run)
        # An old variant menu is usable only for the same vehicle and lookup identity;
        # refreshed inventory can invalidate a previous presentation.
        if presentation is not None and (
            presentation.inventory_vehicle_id != vehicle.id
            or presentation.lookup_identity != identity_for(vehicle)
        ):
            presentation = None
            choice_text = None
        cached = run.results.get("crash")
        if isinstance(cached, CrashResult):
            return cached
        identity = identity_for(vehicle)
        url = discovery_url(identity)
        attempted = datetime.now(UTC)
        common = CrashProvenance(
            inventory_vehicle_id=vehicle.id,
            stock_id=vehicle.source_id,
            lookup_identity=identity,
            source_url=url,
            attempted_at=attempted,
        )
        try:
            # Crash lookup first discovers variants, then fetches one chosen detail record.
            # Remove conflicting variants before deciding whether a match is safe to select.
            discovered = parsing.variants(await self.client.get(url, "discovery", run.budget))
            candidates = tuple(
                item for item in discovered if compatibility(vehicle, item) != "conflicting"
            )
            chosen = None
            if presentation is not None and choice_text is not None:
                # Resolve numbers against the menu the user actually saw, then verify that
                # the chosen variant still exists unchanged in fresh discovery results.
                selected_id, descriptor = resolve_choice(choice_text, presentation)
                if selected_id is not None:
                    old = next(
                        item for item in presentation.candidates if item.vehicle_id == selected_id
                    )
                    chosen = next((item for item in candidates if item == old), None)
                elif descriptor:
                    matches = tuple(
                        item
                        for item in candidates
                        if set(descriptor).issubset(tokens(item.description))
                    )
                    if matches:
                        candidates = matches
                    if len(matches) == 1 and matches[0] in presentation.candidates:
                        chosen = matches[0]
            # A singleton with uncertain compatibility still needs clarification. Only a
            # positively compatible singleton is automatically selected.
            elif len(candidates) == 1 and compatibility(vehicle, candidates[0]) == "compatible":
                chosen = candidates[0]
            retrieved = datetime.now(UTC)
            if not candidates:
                result = CrashResult(**common, status="no_record", retrieved_at=retrieved)
            # Return a bounded menu instead of guessing; the runner persists the displayed
            # choices with successful replay so a later turn can resolve them.
            elif chosen is None:
                result = CrashResult(
                    **common,
                    status="ambiguous",
                    retrieved_at=retrieved,
                    candidates=candidates[:5],
                    total_candidate_count=len(candidates),
                )
            else:
                url = detail_url(chosen.vehicle_id)
                common["source_url"] = url
                row = parsing.detail(
                    await self.client.get(url, "detail", run.budget), identity, chosen
                )
                if row is None:
                    result = CrashResult(
                        **common,
                        status="no_record",
                        retrieved_at=datetime.now(UTC),
                        matched_variant=chosen,
                    )
                else:
                    categories = {
                        name: parsing.category(row.get(key))
                        for key, name in parsing.SUMMARY_KEYS.items()
                    }
                    # Summary categories determine coverage before extra categories are added.
                    # Partial ratings, explicit not-rated values, and missing values stay distinct.
                    states = [item.status for item in categories.values()]
                    status: Literal["available", "partial", "unrated", "no_ratings"] = (
                        "available"
                        if all(item == "rated" for item in states)
                        else (
                            "partial"
                            if "rated" in states
                            else "unrated"
                            if all(item == "not_rated" for item in states)
                            else "no_ratings"
                        )
                    )
                    categories.update(
                        {
                            key: parsing.category(row[key])
                            for key in parsing.EXTRA_KEYS
                            if key in row
                        }
                    )
                    notes: dict[str, str | bool] = {}
                    omitted_notes = 0
                    incomplete = True  # Absence never establishes complete concern coverage.
                    for key, value in row.items():
                        if key == "NHTSAForwardCollisionWarning" or not any(
                            word in key.casefold() for word in ("concern", "warning")
                        ):
                            continue
                        if (
                            isinstance(value, str | bool)
                            and len(key) <= 100
                            and len(str(value)) <= 300
                            and len(notes) < 12
                        ):
                            notes[key] = value
                        else:
                            omitted_notes += 1
                    dynamic = row.get("dynamicTipResult")
                    if not isinstance(dynamic, str | bool) or len(str(dynamic)) > 300:
                        dynamic = None
                    result = CrashResult(
                        **common,
                        status=status,
                        retrieved_at=datetime.now(UTC),
                        matched_variant=chosen,
                        categories=categories,
                        notes=notes,
                        concern_coverage_incomplete=incomplete,
                        concern_notes_omitted=omitted_notes,
                        dynamic_tip_result=dynamic,
                    )
            if len(result.model_dump_json().encode()) > 8 * 1024:
                raise NhtsaError("response_limit")
        # Expected external failures become uncertainty evidence, not no_record or
        # safety assurances. The other safety branch can still succeed independently.
        except (NhtsaError, parsing.InvalidResponse) as exc:
            result = CrashResult(
                **common,
                status="unavailable",
                reason=exc.reason
                if isinstance(exc, NhtsaError)
                else "response_limit"
                if isinstance(exc, parsing.ResponseLimit)
                else "invalid_response",
            )
        run.results["crash"] = result
        return result
