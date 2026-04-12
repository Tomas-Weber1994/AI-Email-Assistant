"""Time helpers used across the agent (Wall-clock semantics)."""

from datetime import datetime, timezone

# Get local timezone offset (e.g., +02:00)
_LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc


def parse_datetime_input(value: str) -> datetime:
    """Parse ISO datetime and strictly force local timezone without conversion."""
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("datetime value is required")

    try:
        # fromisoformat handles 'Z' and offsets.
        # We use .replace() to intentionally ignore the original offset.
        parsed = datetime.fromisoformat(raw_value)
        return parsed.replace(tzinfo=_LOCAL_TZ)
    except ValueError as exc:
        raise ValueError(f"invalid ISO datetime: {raw_value}") from exc


def normalize_time_range(start: str, end: str) -> tuple[str, str]:
    """Validate and return local RFC3339 strings."""
    start_dt = parse_datetime_input(start)
    end_dt = parse_datetime_input(end)

    if end_dt <= start_dt:
        raise ValueError("end time must be after start time")

    return start_dt.isoformat(), end_dt.isoformat()
