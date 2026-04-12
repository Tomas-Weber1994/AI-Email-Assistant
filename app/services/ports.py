from typing import Any, Protocol


class EmailProvider(Protocol):
    """Port for inbox and outbound email operations."""

    def list_unread(self, max_results: int = 20) -> list[dict[str, Any]]: ...

    def list_approval_replies(self, manager_email: str, max_results: int = 20) -> list[dict[str, Any]]: ...

    def get_message(self, msg_id: str) -> dict[str, Any]: ...

    def get_thread_subject(self, thread_id: str) -> str: ...

    def has_label(self, msg_id: str, label_name: str) -> bool: ...

    def modify_labels(
        self,
        msg_id: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any]: ...

    def send_reply(self, original_msg: dict[str, Any], text: str) -> dict[str, Any]: ...

    def send_message(self, to: str, subject: str, body: str) -> dict[str, Any]: ...

    def send_approval_request(
        self,
        original_msg: dict[str, Any],
        action_summary: str,
        workflow_id: str | None,
    ) -> dict[str, Any]: ...


class CalendarProvider(Protocol):
    """Port for calendar availability and event creation."""

    def check_availability(self, start: str, end: str) -> bool: ...

    def create_event(self, summary: str, start: str, end: str) -> dict[str, Any]: ...

