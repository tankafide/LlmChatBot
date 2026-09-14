"""One byte/count boundary for whole replay turns and their presentation context."""

MAX_HISTORY_BYTES = 64 * 1024


def retain_replay(units: tuple[str, ...]) -> tuple[str, ...]:
    """Keep a contiguous suffix of whole completed turns. Cutting individual messages could
    separate a model tool call from its result and invalidate replay. Return a count/byte-
    bounded suffix of complete replay units in original order. Return an empty tuple when
    nothing fits; the input tuple is unchanged.

    Shared by conversation replay loading, model history loading, safety presentation
    restoration, and evaluation trimming.
    """
    total = 0
    count = 0
    # Favor recent context and bound both count and UTF-8 size. This is a serialized
    # byte budget rather than a provider-specific token estimate.
    for unit in reversed(units[-10:]):
        size = len(unit.encode("utf-8"))
        if total + size > MAX_HISTORY_BYTES:
            # Stop rather than skipping a large turn: disconnected older turns could make
            # references disagree with the presentation context retained elsewhere.
            break
        total += size
        count += 1
    return units[-count:] if count else ()
