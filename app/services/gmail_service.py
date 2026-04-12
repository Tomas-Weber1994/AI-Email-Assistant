import base64
from email.message import EmailMessage
from typing import Any

from app.services.base import GoogleService
from app.utils.email_utils import get_headers


class GmailService(GoogleService):
    USER_ID = "me"
    APPROVAL_SUBJECT_TAG = "[APPROVAL REQUIRED]"

    def __init__(self, auth_http):
        super().__init__("gmail", "v1", auth_http)
        self._label_map: dict[str, str] = {}

    def test_connection(self) -> dict:
        self.logger.info("Testing Gmail connection...")
        profile = self._call_google_api(self.service.users().getProfile(userId=self.USER_ID))
        return {"status": "ok", "email": profile.get("emailAddress")}

    def ensure_labels(self, label_names: list[str]) -> None:
        """Sync local label map with Gmail, creating any missing labels."""
        res = self._call_google_api(self.service.users().labels().list(userId=self.USER_ID))
        existing = {label["name"]: label["id"] for label in res.get("labels", [])}

        for name in label_names:
            if name not in existing:
                self.logger.info("Creating label: %s", name)
                created = self._call_google_api(
                    self.service.users().labels().create(userId=self.USER_ID, body={"name": name})
                )
                existing[name] = created["id"]
            self._label_map[name] = existing[name]

    def list_unread(self, max_results: int = 20) -> list[dict[str, Any]]:
        # Exclude approval control emails from normal inbox processing.
        query = f'label:INBOX is:unread -subject:"{self.APPROVAL_SUBJECT_TAG}"'
        request = self.service.users().messages().list(
            userId=self.USER_ID,
            q=query,
            maxResults=max_results,
        )
        return self._call_google_api(request).get("messages", [])

    def list_approval_replies(self, manager_email: str, max_results: int = 20) -> list[dict[str, Any]]:
        query = (
            f'in:inbox is:unread from:{manager_email} '
            f'subject:"{self.APPROVAL_SUBJECT_TAG}"'
        )
        request = self.service.users().messages().list(
            userId=self.USER_ID,
            q=query,
            maxResults=max_results,
        )
        return self._call_google_api(request).get("messages", [])

    def get_message(self, msg_id: str) -> dict[str, Any]:
        request = self.service.users().messages().get(userId=self.USER_ID, id=msg_id)
        return self._call_google_api(request)

    def get_thread_subject(self, thread_id: str) -> str:
        thread = self._call_google_api(self.service.users().threads().get(userId=self.USER_ID, id=thread_id))
        if not thread.get("messages"):
            return "No Subject"
        return get_headers(thread["messages"][0]).get("Subject", "No Subject")

    def has_label(self, msg_id: str, label_name: str) -> bool:
        request = self.service.users().messages().get(userId=self.USER_ID, id=msg_id, format='minimal')
        msg = self._call_google_api(request)
        label_ids = set(msg.get("labelIds", []))
        expected_label_id = self._label_map.get(label_name, label_name)
        return expected_label_id in label_ids

    def modify_labels(
        self,
        msg_id: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any]:
        body = {
            "addLabelIds": [self._label_map.get(name, name) for name in (add or [])],
            "removeLabelIds": [self._label_map.get(name, name) for name in (remove or [])],
        }
        request = self.service.users().messages().modify(userId=self.USER_ID, id=msg_id, body=body)
        return self._call_google_api(request)

    def send_reply(self, original_msg: dict[str, Any], text: str) -> dict[str, Any]:
        headers = get_headers(original_msg)
        message = EmailMessage()
        message.set_content(text)
        message["To"] = headers.get("From")
        message["Subject"] = f"Re: {headers.get('Subject', '')}"
        if message_id := headers.get("Message-ID"):
            message["In-Reply-To"] = message_id
            message["References"] = message_id
        return self._send_raw(message, thread_id=original_msg.get("threadId"))

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]:
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to
        message["Subject"] = subject
        return self._send_raw(message)

    def _send_raw(self, message: EmailMessage, thread_id: str | None = None) -> dict[str, Any]:
        body = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
        if thread_id:
            body["threadId"] = thread_id
        request = self.service.users().messages().send(userId=self.USER_ID, body=body)
        return self._call_google_api(request)
