import base64
import logging
from email.message import EmailMessage
from typing import List, Optional, Dict, Any

from app.services.base import GoogleService

logger = logging.getLogger(__name__)


class GmailService(GoogleService):
    USER_ID = "me"

    def __init__(self, auth_http):
        super().__init__("gmail", "v1", auth_http)
        self._label_map: Dict[str, str] = {}

    def test_connection(self) -> dict:
        self.logger.info("Testing Gmail connection...")
        profile = self._call_google_api(self.service.users().getProfile(userId=self.USER_ID))
        return {"status": "ok", "email": profile.get("emailAddress")}

    def ensure_labels(self, label_names: List[str]) -> None:
        """Syncs local label map with Gmail, creating any missing labels."""
        res = self._call_google_api(self.service.users().labels().list(userId=self.USER_ID))
        existing = {l['name']: l['id'] for l in res.get('labels', [])}

        for name in label_names:
            if name not in existing:
                self.logger.info(f"Creating label: {name}")
                new_label = self._call_google_api(self.service.users().labels().create(
                    userId=self.USER_ID,
                    body={'name': name}
                ))
                existing[name] = new_label['id']
            self._label_map[name] = existing[name]

    def list_unread(self, max_results: int = 20) -> List[Dict[str, Any]]:
        query = "label:INBOX is:unread"
        request = self.service.users().messages().list(
            userId=self.USER_ID, q=query, maxResults=max_results
        )
        return self._call_google_api(request).get("messages", [])

    def get_message(self, msg_id: str) -> Dict[str, Any]:
        return self._call_google_api(self.service.users().messages().get(
            userId=self.USER_ID, id=msg_id
        ))

    def get_thread(self, thread_id: str) -> Dict[str, Any]:
        return self._call_google_api(self.service.users().threads().get(
            userId=self.USER_ID, id=thread_id
        ))

    def get_thread_subject(self, thread_id: str) -> str:
        """Extracts the subject from the first message in a thread."""
        thread = self.get_thread(thread_id)
        if not thread.get("messages"):
            return "No Subject"

        headers = thread["messages"][0].get("payload", {}).get("headers", [])
        return next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")

    def modify_labels(self, msg_id: str, add: List[str] = None, remove: List[str] = None) -> Dict[str, Any]:
        """Modifies message labels (maps custom names to IDs, passes system labels as-is)."""
        add_ids = [self._label_map.get(n, n) for n in (add or [])]
        remove_ids = [self._label_map.get(n, n) for n in (remove or [])]

        body = {
            "addLabelIds": add_ids,
            "removeLabelIds": remove_ids
        }
        return self._call_google_api(self.service.users().messages().modify(
            userId=self.USER_ID, id=msg_id, body=body
        ))

    def send_reply(self, original_msg: Dict[str, Any], text: str) -> Dict[str, Any]:
        """Creates and sends an RFC-compliant reply within the original thread."""
        headers = {h['name']: h['value'] for h in original_msg.get('payload', {}).get('headers', [])}

        msg = EmailMessage()
        msg.set_content(text)
        msg["To"] = headers.get('From')
        msg["Subject"] = f"Re: {headers.get('Subject', '')}"
        msg["In-Reply-To"] = headers.get('Message-ID')
        msg["References"] = headers.get('Message-ID')

        return self._send_raw(msg, thread_id=original_msg.get('threadId'))

    def send_message(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        msg = EmailMessage()
        msg.set_content(body)
        msg["To"] = to
        msg["Subject"] = subject
        return self._send_raw(msg)

    def _send_raw(self, msg: EmailMessage, thread_id: Optional[str] = None) -> Dict[str, Any]:
        raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body = {"raw": raw_b64}
        if thread_id:
            body["threadId"] = thread_id

        return self._call_google_api(self.service.users().messages().send(
            userId=self.USER_ID, body=body
        ))


class CalendarService(GoogleService):
    PRIMARY_CALENDAR = "primary"

    def __init__(self, auth_http):
        super().__init__("calendar", "v3", auth_http)

    def test_connection(self) -> dict:
        self.logger.info("Testing Calendar connection...")
        res = self._call_google_api(self.service.calendarList().list())
        return {"status": "ok", "count": len(res.get("items", []))}

    def create_event(self, summary: str, start: str, end: str) -> Dict[str, Any]:
        """Creates a calendar event (expects ISO datetime strings)."""
        event_body = {
            'summary': summary,
            'start': {'dateTime': start, 'timeZone': 'UTC'},
            'end': {'dateTime': end, 'timeZone': 'UTC'}
        }
        return self._call_google_api(self.service.events().insert(
            calendarId=self.PRIMARY_CALENDAR,
            body=event_body
        ))

    def check_availability(self, start: str, end: str) -> bool:
        """Returns True if the time slot is free (no conflicting events)."""
        body = {
            "timeMin": start,
            "timeMax": end,
            "items": [{"id": self.PRIMARY_CALENDAR}]
        }
        res = self._call_google_api(
            self.service.freebusy().query(body=body)
        )

        busy_slots = res.get("calendars", {}).get(self.PRIMARY_CALENDAR, {}).get("busy", [])
        return len(busy_slots) == 0
