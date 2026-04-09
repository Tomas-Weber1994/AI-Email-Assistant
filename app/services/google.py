from googleapiclient.discovery import build
from app.services.base import GoogleService

class GmailService(GoogleService):
    def __init__(self, auth_http):
        super().__init__()
        self._service = build("gmail", "v1", http=auth_http, cache_discovery=False)

    def test_connection(self) -> dict:
        self.logger.info("Testing Gmail...")
        labels = self._service.users().labels().list(userId="me").execute()  # type: ignore
        return {"status": "ok", "count": len(labels.get("labels", []))}

class CalendarService(GoogleService):
    def __init__(self, auth_http):
        super().__init__()
        self._service = build("calendar", "v3", http=auth_http, cache_discovery=False)

    def test_connection(self) -> dict:
        self.logger.info("Testing Calendar...")
        calendar_list = self._service.calendarList().list().execute()  # type: ignore
        return {"status": "ok", "count": len(calendar_list.get("items", []))}
