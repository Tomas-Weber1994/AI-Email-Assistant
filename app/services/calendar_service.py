from typing import Any

from app.services.base import GoogleService
from app.utils.time_utils import normalize_time_range


class CalendarService(GoogleService):
    PRIMARY_CALENDAR = "primary"
    LOCAL_TIMEZONE = "Europe/Prague"

    def __init__(self, auth_http):
        super().__init__("calendar", "v3", auth_http)

    def test_connection(self) -> dict:
        self.logger.info("Testing Calendar connection...")
        res = self._call_google_api(self.service.calendarList().list())
        return {"status": "ok", "count": len(res.get("items", []))}

    def create_event(self, summary: str, start: str, end: str) -> dict[str, Any]:
        normalized_start, normalized_end = normalize_time_range(start, end)
        event_body = {
            "summary": summary,
            "start": {"dateTime": normalized_start, "timeZone": self.LOCAL_TIMEZONE},
            "end": {"dateTime": normalized_end, "timeZone": self.LOCAL_TIMEZONE},
        }
        request = self.service.events().insert(calendarId=self.PRIMARY_CALENDAR, body=event_body)
        result = self._call_google_api(request)
        self.logger.info("Calendar: Event '%s' successfully created at %s", summary, normalized_start)
        return result

    def check_availability(self, start: str, end: str) -> bool:
        normalized_start, normalized_end = normalize_time_range(start, end)
        body = {
            "timeMin": normalized_start,
            "timeMax": normalized_end,
            "timeZone": self.LOCAL_TIMEZONE,
            "items": [{"id": self.PRIMARY_CALENDAR}],
        }
        res = self._call_google_api(self.service.freebusy().query(body=body))
        busy_slots = res.get("calendars", {}).get(self.PRIMARY_CALENDAR, {}).get("busy", [])
        self.logger.info("CALENDAR: Check %s - %s -> %s", normalized_start, normalized_end, "BUSY" if busy_slots else "FREE")
        return not busy_slots
