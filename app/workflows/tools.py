from enum import Enum
from typing import Annotated, Dict
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedState
from googleapiclient.errors import HttpError
from app.schemas.classification import EmailLabel, GmailReservedLabel, GmailSystemLabel
from app.utils.email_utils import get_headers, get_body


_FINANCE_TOKENS = ("invoice", "receipt", "faktura", "účtenka", "uctenka")
_VALID_PRIMARY_LABELS = {label.value for label in EmailLabel}


class ToolName(str, Enum):
    CHECK_AVAILABILITY = "check_availability"
    CREATE_CALENDAR_EVENT = "create_calendar_event"
    SEND_REPLY = "send_reply"
    ARCHIVE_AND_LABEL = "archive_and_label"
    NOTIFY_MANAGER = "notify_manager"


def _format_tool_error(exc: Exception, detail: str) -> str:
    if isinstance(exc, ValueError):
        return f"INVALID_INPUT: {exc}"
    if isinstance(exc, HttpError):
        return f"API_ERROR {exc.resp.status}: {detail}"
    return f"ERROR: {exc} — {detail}"


def _looks_like_finance_email(raw_content: Dict) -> bool:
    headers = get_headers(raw_content or {})
    haystack = f"{headers.get('Subject', '')}\n{get_body(raw_content or {})}".lower()
    return any(token in haystack for token in _FINANCE_TOKENS)


@tool
def check_availability(start_iso: str, end_iso: str, config: RunnableConfig):
    """Checks calendar availability before proposing a meeting time."""
    calendar = config["configurable"]["calendar"]
    try:
        return "FREE" if calendar.check_availability(start_iso, end_iso) else "BUSY"
    except Exception as exc:
        return _format_tool_error(exc, "availability lookup failed")


@tool
def create_calendar_event(summary: str, start_iso: str, end_iso: str, config: RunnableConfig):
    """Creates a calendar event. Requires manager approval."""
    calendar = config["configurable"]["calendar"]

    try:
        calendar.create_event(summary, start_iso, end_iso)
        return f"SUCCESS: Event '{summary}' created."
    except Exception as exc:
        return _format_tool_error(exc, f"event '{summary}' could not be created")


@tool
def send_reply(text: str, raw_content: Annotated[Dict, InjectedState("raw_content")], config: RunnableConfig):
    """Sends an email reply. Requires manager approval."""
    gmail = config["configurable"]["email"]

    try:
        gmail.send_reply(raw_content, text)
        return "SUCCESS: Reply sent."
    except Exception as exc:
        return _format_tool_error(exc, "reply could not be sent")


@tool
def archive_and_label(
    primary_label: str,
    is_urgent: bool,
    raw_content: Annotated[Dict, InjectedState("raw_content")],
    config: RunnableConfig,
):
    """
    Apply labels and archive the email.
    Always call this as the final step after all other actions.
    """
    gmail = config["configurable"]["email"]
    email_id = (raw_content or {}).get("id") or config["configurable"].get("thread_id")
    if not email_id:
        return "GMAIL_ERROR: missing message id"

    label_to_apply = primary_label if primary_label in _VALID_PRIMARY_LABELS else EmailLabel.INFO_ONLY.value

    if label_to_apply == EmailLabel.SPAM.value:
        try:
            gmail.modify_labels(
                email_id,
                add=[GmailReservedLabel.SPAM.value],
                remove=[GmailReservedLabel.INBOX.value, GmailReservedLabel.UNREAD.value],
            )
            return "SUCCESS: Moved to SPAM."
        except Exception as exc:
            return _format_tool_error(exc, "SPAM labeling failed")

    labels = [label_to_apply]
    if is_urgent:
        labels.append(GmailSystemLabel.URGENT.value)
    if label_to_apply == EmailLabel.INFO_ONLY.value and _looks_like_finance_email(raw_content):
        labels.append(GmailSystemLabel.FINANCE.value)

    try:
        gmail.modify_labels(
            email_id,
            add=labels,
            remove=[GmailReservedLabel.INBOX.value, GmailReservedLabel.UNREAD.value],
        )
        return f"SUCCESS: Archived with labels {labels}. Workflow finished."
    except Exception as exc:
        return _format_tool_error(exc, f"archiving with labels {labels} failed")


@tool
def notify_manager(proposed_action: str):
    """Sends an immediate notification to the manager about an important task."""
    return f"SUCCESS: Manager notified about: {proposed_action}"


def get_all_tools():
    return [check_availability, create_calendar_event, send_reply, archive_and_label, notify_manager]


def get_sensitive_tool_names():
    # Tools that trigger the ask_approval node in routing_logic.
    return [
        ToolName.CREATE_CALENDAR_EVENT.value,
        ToolName.SEND_REPLY.value,
        ToolName.NOTIFY_MANAGER.value,
    ]
