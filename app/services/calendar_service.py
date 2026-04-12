from typing import Any

from app.services.base import GoogleService


class CalendarService(GoogleService):
    PRIMARY_CALENDAR = "primary"

    def __init__(self, auth_http):
        super().__init__("calendar", "v3", auth_http)

    def test_connection(self) -> dict:
        self.logger.info("Testing Calendar connection...")
        res = self._call_google_api(self.service.calendarList().list())
        return {"status": "ok", "count": len(res.get("items", []))}

    def create_event(self, summary: str, start: str, end: str) -> dict[str, Any]:
        event_body = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        }
        request = self.service.events().insert(calendarId=self.PRIMARY_CALENDAR, body=event_body)
        return self._call_google_api(request)

    def check_availability(self, start: str, end: str) -> bool:
        body = {
            "timeMin": start,
            "timeMax": end,
            "items": [{"id": self.PRIMARY_CALENDAR}],
        }
        res = self._call_google_api(self.service.freebusy().query(body=body))
        busy_slots = res.get("calendars", {}).get(self.PRIMARY_CALENDAR, {}).get("busy", [])
        return not busy_slots

