from __future__ import annotations

from autoassist.safety.records import CrashResult, RecallResult


def render_safety(results: list[RecallResult | CrashResult]) -> str:
    """Render validated safety evidence within the public reply character limit.

    Called by the grounded runner for a nonempty same-vehicle result list. Return text no
    longer than 8000 characters, retrying shorter excerpts as needed. Raise ValueError if
    mandatory material cannot fit; empty input raises IndexError.
    """
    for excerpt_limit in (300, 180, 80):
        reply = _render_safety(results, excerpt_limit)
        if len(reply) <= 8000:
            return reply
    raise ValueError("mandatory safety reply exceeds limit")


def _render_safety(results: list[RecallResult | CrashResult], excerpt_limit: int) -> str:
    """Build a safety reply using a chosen excerpt length.

    Called by render_safety for each size attempt. Return text with statuses, urgent flags,
    choices/ratings, provenance, and uncertainty statements. Assume a nonempty validated
    same-vehicle list; empty input raises IndexError. This helper does not enforce the overall
    reply limit.
    """
    first = results[0]
    identity = first.lookup_identity
    lines = [f"{identity.year} {identity.make} {identity.model} (stock {first.stock_id}) — NHTSA"]
    for result in results:
        if isinstance(result, RecallResult):
            if result.status == "unavailable":
                lines.append(f"Recall data unavailable ({result.reason}).")
            elif result.status == "empty":
                lines.append("No campaigns returned for this year/make/model at retrieval time.")
            else:
                lines.append(
                    f"Recalls: {result.total_count} campaigns; "
                    f"{result.urgent_count} with park-it/park-outside flags."
                )
                for campaign in result.campaigns:
                    lines.append(
                        f"NHTSA campaign {campaign.campaign_number}: "
                        f"{campaign.component or 'component unavailable'}"
                    )
                    if campaign.park_it:
                        lines.append("NHTSA urgent flag: park it.")
                    if campaign.park_outside:
                        lines.append("NHTSA urgent flag: park outside.")
                    for label in ("summary", "consequence", "remedy", "notes"):
                        value = getattr(campaign, label)
                        if value and len(value) > excerpt_limit:
                            value = value[:excerpt_limit] + " [excerpt]"
                        if label != "notes" or value:
                            lines.append(f"NHTSA {label} excerpt: {value or 'text unavailable'}")
                if result.omitted_count:
                    lines.append(
                        f"{result.omitted_count} additional campaigns omitted; see source."
                    )
            lines.append(
                "Year/make/model campaigns do not establish this VIN's applicability or repair "
                "status. Check the VIN at https://www.nhtsa.gov/recalls."
            )
        else:
            lines.append(
                f"Crash ratings: {result.status.replace('_', ' ')}"
                + (f" ({result.reason})." if result.reason else ".")
            )
            if result.status == "ambiguous":
                for index, item in enumerate(result.candidates, 1):
                    lines.append(f"{index}. {item.description} — NHTSA ID {item.vehicle_id}")
                if result.total_candidate_count > len(result.candidates):
                    lines.append(
                        f"Showing {len(result.candidates)} of "
                        f"{result.total_candidate_count} variants; "
                        "provide a distinguishing description for others."
                    )
                lines.append(
                    "Reply with the exact displayed NHTSA ID or description that applies. "
                    "Do not combine choices."
                )
            if result.matched_variant:
                lines.append(
                    f"Variant: {result.matched_variant.description} "
                    f"(NHTSA ID {result.matched_variant.vehicle_id})."
                )
            for name in ("overall", "frontal", "side", "rollover"):
                rating = result.categories.get(name)
                if rating:
                    value = (
                        f"{rating.stars}/5 stars"
                        if rating.status == "rated"
                        else rating.status.replace("_", " ")
                    )
                    lines.append(f"{name.capitalize()}: {value}.")
            for label, note in result.notes.items():
                if note:
                    lines.append(f"NHTSA supplemental note [{label}]: {note}")
            if result.concern_notes_omitted:
                lines.append(
                    f"{result.concern_notes_omitted} NHTSA concern/warning fields omitted: "
                    "invalid or oversized."
                )
            if result.dynamic_tip_result is not None:
                lines.append(f"NHTSA dynamicTipResult: {result.dynamic_tip_result}")
            lines.append(
                "Concern-field coverage is incomplete; missing notes do not establish absence "
                "of safety concerns. Individual ratings are not a safety guarantee or vehicle "
                "ranking. https://www.nhtsa.gov/ratings"
            )
        time = result.retrieved_at or result.attempted_at
        lines.append(
            f"NHTSA source: {result.source_url}\n"
            f"{'Retrieved' if result.retrieved_at else 'Attempted'}: {time.isoformat()}"
        )
    return "\n".join(lines)
