"""Time helpers used across the agent."""

from datetime import datetime, timezone

# Local timezone used for wall-clock scheduling semantics.
_LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc


def to_local_wallclock(value: datetime) -> datetime:
    """Keep wall-clock values unchanged and attach local timezone when needed."""
    if value.tzinfo is None:
        return value.replace(tzinfo=_LOCAL_TZ)
    # IMPORTANT: no timezone conversion here; 17:00 stays 17:00.
    return value.replace(tzinfo=_LOCAL_TZ)


def to_rfc3339_local(value: datetime) -> str:
    """Serialize datetime as local RFC3339 string (with local offset)."""
    return to_local_wallclock(value).isoformat()


# Backward-compatible aliases (legacy names kept to avoid external breakage).
def to_utc(value: datetime) -> datetime:
    return to_local_wallclock(value)


def to_rfc3339_utc(value: datetime) -> str:
    return to_rfc3339_local(value)

def parse_datetime_input(value: str) -> datetime:
    """Parse incoming ISO/RFC3339 datetime text using local wall-clock semantics."""
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("datetime value is required")

    normalized_value = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO datetime: {raw_value}") from exc

    return to_local_wallclock(parsed)


def normalize_time_range(start: str, end: str) -> tuple[str, str]:
    """Validate and normalize a start/end pair to local RFC3339 strings."""
    start_dt = parse_datetime_input(start)
    end_dt = parse_datetime_input(end)

    if end_dt <= start_dt:
        raise ValueError("end time must be after start time")

    return to_rfc3339_local(start_dt), to_rfc3339_local(end_dt)

