from typing import Annotated, Dict
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedState
from googleapiclient.errors import HttpError
from app.utils.email_utils import get_headers, get_body


_FINANCE_TOKENS = ("invoice", "receipt", "faktura", "účtenka", "uctenka")


def _run_calendar_call(fn, value_error_prefix: str, http_error_message: str):
    try:
        return fn()
    except ValueError as exc:
        return f"{value_error_prefix}: {exc}"
    except HttpError:
        return http_error_message


def _looks_like_finance_email(raw_content: Dict) -> bool:
    headers = get_headers(raw_content or {})
    haystack = f"{headers.get('Subject', '')}\n{get_body(raw_content or {})}".lower()
    return any(token in haystack for token in _FINANCE_TOKENS)

@tool
def check_availability(start_iso: str, end_iso: str, config: RunnableConfig):
    """Ověří dostupnost v kalendáři před návrhem schůzky."""
    calendar = config["configurable"]["calendar"]
    def _call():
        is_free = calendar.check_availability(start_iso, end_iso)
        return "FREE" if is_free else "BUSY"

    return _run_calendar_call(_call, "INVALID_DATETIME", "CALENDAR_ERROR: availability lookup failed")

@tool
def create_calendar_event(summary: str, start_iso: str, end_iso: str, config: RunnableConfig):
    """Vytvoří událost v kalendáři. Vyžaduje schválení manažerem."""
    calendar = config["configurable"]["calendar"]
    def _call():
        calendar.create_event(summary, start_iso, end_iso)
        return f"SUCCESS: Event '{summary}' created."

    return _run_calendar_call(
        _call,
        "INVALID_DATETIME",
        f"CALENDAR_ERROR: Event '{summary}' could not be created.",
    )

@tool
def send_reply(text: str, raw_content: Annotated[Dict, InjectedState("raw_content")], config: RunnableConfig):
    """Odešle e-mailovou odpověď. Vyžaduje schválení."""
    gmail = config["configurable"]["email"]
    gmail.send_reply(raw_content, text)
    return "SUCCESS: Reply sent."

@tool
def archive_and_label(
    primary_label: str,
    is_urgent: bool,
    raw_content: Annotated[Dict, InjectedState("raw_content")],
    config: RunnableConfig,
):
    """
    Přiřadí štítky a archivuje e-mail.
    Tento nástroj volejte VŽDY jako úplně poslední krok po všech ostatních akcích.
    """
    gmail = config["configurable"]["email"]
    email_id = config["configurable"]["thread_id"]

    # Mapování labelů dle zadání
    valid_labels = ["MEETING_REQUEST", "TASK", "INFO_ONLY", "SALES_OUTREACH", "MARKETING", "SPAM"]
    label_to_apply = primary_label if primary_label in valid_labels else "INFO_ONLY"

    if label_to_apply == "SPAM":
        gmail.move_to_spam(email_id)
        return "SUCCESS: Moved to SPAM."

    labels = [label_to_apply]
    if is_urgent: labels.append("URGENT")

    if label_to_apply == "INFO_ONLY" and _looks_like_finance_email(raw_content):
        labels.append("Finance")

    gmail.modify_labels(email_id, add=labels, remove=["INBOX", "UNREAD"])
    return f"SUCCESS: Archived with labels {labels}. Workflow finished."

@tool
def notify_manager(proposed_action: str, config: RunnableConfig):
    """Odesílá okamžitou notifikaci manažerovi o důležitém úkolu."""
    return f"SUCCESS: Manager notified about: {proposed_action}"

def get_all_tools():
    return [check_availability, create_calendar_event, send_reply, archive_and_label, notify_manager]

def get_sensitive_tool_names():
    # Seznam nástrojů, u kterých routing_logic vynutí uzel ask_approval
    return ["create_calendar_event", "send_reply", "notify_manager"]
