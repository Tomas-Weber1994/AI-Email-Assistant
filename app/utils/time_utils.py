"""Time helpers used across the agent."""

from datetime import datetime, timezone, timedelta


def to_utc(value: datetime) -> datetime:
    """Normalize datetime to UTC, assuming naive values are already UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_rfc3339_utc(value: datetime) -> str:
    """Serialize datetime as UTC RFC3339 string with trailing Z."""
    return to_utc(value).isoformat().replace("+00:00", "Z")


def in_one_hour_iso() -> str:
    """UTC time one hour from now as ISO 8601 string."""
    return to_rfc3339_utc(datetime.now(timezone.utc) + timedelta(hours=1))
