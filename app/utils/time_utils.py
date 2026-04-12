"""Time helpers used across the agent."""

from datetime import datetime, timezone


def to_utc(value: datetime) -> datetime:
    """Normalize datetime to UTC, assuming naive values are already UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_rfc3339_utc(value: datetime) -> str:
    """Serialize datetime as UTC RFC3339 string with trailing Z."""
    return to_utc(value).isoformat().replace("+00:00", "Z")

def parse_datetime_input(value: str) -> datetime:
    """Parse incoming ISO/RFC3339 datetime text and normalize timezone handling."""
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("datetime value is required")

    normalized_value = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO datetime: {raw_value}") from exc

    return to_utc(parsed)


def normalize_time_range(start: str, end: str) -> tuple[str, str]:
    """Validate and normalize a start/end pair to RFC3339 UTC strings."""
    start_dt = parse_datetime_input(start)
    end_dt = parse_datetime_input(end)

    if end_dt <= start_dt:
        raise ValueError("end time must be after start time")

    return to_rfc3339_utc(start_dt), to_rfc3339_utc(end_dt)

