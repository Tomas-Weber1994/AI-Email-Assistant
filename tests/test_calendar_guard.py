from typing import Any, cast
from unittest.mock import Mock

from app.workflows.tools import create_calendar_event


create_calendar_event_tool = cast(Any, create_calendar_event)


class DummyCalendar:
    def __init__(self, available: bool):
        self._available = available
        self.create_event = Mock()

    def check_availability(self, start_iso: str, end_iso: str) -> bool:
        return self._available


def test_create_calendar_event_skips_when_slot_is_busy():
    calendar = DummyCalendar(available=False)

    result = create_calendar_event_tool.invoke(
        {
            "summary": "1:1 Sync",
            "start_iso": "2026-04-15T14:00:00Z",
            "end_iso": "2026-04-15T14:30:00Z",
        },
        config={"configurable": {"calendar": calendar}},
    )

    assert result.startswith("CONFLICT:")
    calendar.create_event.assert_not_called()


def test_create_calendar_event_creates_event_when_slot_is_free():
    calendar = DummyCalendar(available=True)

    result = create_calendar_event_tool.invoke(
        {
            "summary": "1:1 Sync",
            "start_iso": "2026-04-15T14:00:00Z",
            "end_iso": "2026-04-15T14:30:00Z",
        },
        config={"configurable": {"calendar": calendar}},
    )

    assert result.startswith("SUCCESS:")
    calendar.create_event.assert_called_once_with(
        "1:1 Sync",
        "2026-04-15T14:00:00Z",
        "2026-04-15T14:30:00Z",
    )



