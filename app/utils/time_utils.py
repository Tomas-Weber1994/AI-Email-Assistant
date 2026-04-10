"""Time helpers used across the agent."""

from datetime import datetime, timezone, timedelta


def in_one_hour_iso() -> str:
    """UTC time one hour from now as ISO 8601 string."""
    return (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
