"""One byte/count boundary for whole replay turns and their presentation context."""

MAX_HISTORY_BYTES = 64 * 1024


def retain_replay(units: tuple[str, ...]) -> tuple[str, ...]:
    total = 0
    count = 0
    for unit in reversed(units[-10:]):
        size = len(unit.encode("utf-8"))
        if total + size > MAX_HISTORY_BYTES:
            break
        total += size
        count += 1
    return units[-count:] if count else ()
