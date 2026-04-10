"""
Atomic Gmail/Calendar actions called by LangGraph nodes.
These functions have no decision logic — they simply execute their single responsibility
and return an audit string. All routing decisions belong in the graph layer (graph.py).
"""

from app.schemas.classification import EmailClassification, EmailLabel
from app.services.google import GmailService, CalendarService
from app.settings import settings


def apply_labels_and_archive(gmail: GmailService, msg_id: str, cls: EmailClassification) -> str:
    """Applies classification labels, removes UNREAD, and archives (removes INBOX)."""
    labels_to_add = [cls.primary_label.value] + (["URGENT"] if cls.is_urgent else [])

    # INFO_ONLY invoices/receipts get the Finance label
    if cls.primary_label == EmailLabel.INFO_ONLY:
        labels_to_add.append("Finance")

    gmail.modify_labels(msg_id, add=labels_to_add, remove=["INBOX", "UNREAD"])
    return f"Labels applied: {labels_to_add}, archived."


def log_spam(gmail: GmailService, msg_id: str) -> str:
    """Moves the message to Gmail's system SPAM folder and logs it."""
    gmail.modify_labels(msg_id, add=["SPAM"], remove=["INBOX", "UNREAD"])
    return "Moved to SPAM folder and logged."


def flag_and_notify(gmail: GmailService, msg_id: str, cls: EmailClassification) -> str:
    """Flags the message with STARRED and notifies the manager via email."""
    labels_to_add = [cls.primary_label.value, "STARRED"] + (["URGENT"] if cls.is_urgent else [])
    gmail.modify_labels(msg_id, add=labels_to_add, remove=["UNREAD"])

    gmail.send_message(
        to=settings.MANAGER_EMAIL,
        subject=f"[URGENT] Action required — flagged email",
        body=(
            f"An email has been flagged as {cls.primary_label.value}"
            f"{' + URGENT' if cls.is_urgent else ''} and requires your attention.\n\n"
            f"Reason: {cls.justification}"
        ),
    )
    return f"Flagged (STARRED) and manager notified at {settings.MANAGER_EMAIL}."


def send_auto_reply(gmail: GmailService, raw_msg: dict, reply_text: str) -> str:
    """Sends an auto-reply within the original thread."""
    gmail.send_reply(raw_msg, reply_text)
    return "Sent auto-reply."


def create_calendar_event(calendar: CalendarService, cls: EmailClassification, subject: str) -> str:
    """Creates a calendar event after checking availability."""
    start = cls.meeting_start
    end = cls.meeting_end

    if not start or not end:
        raise ValueError("Missing meeting time for calendar event.")

    if not calendar.check_availability(start, end):
        raise RuntimeError(f"Calendar conflict detected for slot {start} - {end}")

    calendar.create_event(summary=subject, start=start, end=end)
    return f"Calendar event created: {start} → {end}"
