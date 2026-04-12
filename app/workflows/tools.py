from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedState
from typing import Annotated, Dict, Any

from app.settings import settings
from app.utils.email_utils import get_headers

@tool
def check_availability(
        start_iso: Annotated[str, "Start time in ISO 8601 UTC (e.g. 2026-04-15T14:00:00Z)"],
        end_iso: Annotated[str, "End time in ISO 8601 UTC"],
        config: RunnableConfig
) -> bool:
    """Prohledá kalendář manažera a zjistí, zda je v daný čas volno."""
    calendar = config["configurable"]["calendar"]
    return calendar.check_availability(start_iso, end_iso)


@tool
def create_calendar_event(
        summary: str,
        start_iso: str,
        end_iso: str,
        config: RunnableConfig
):
    """Vytvoří novou událost v kalendáři. VYŽADUJE PŘEDCHOZÍ SCHVÁLENÍ."""
    calendar = config["configurable"]["calendar"]
    if not calendar.check_availability(start_iso, end_iso):
        return f"CONFLICT: Slot {start_iso} - {end_iso} is busy. Event not created."
    calendar.create_event(summary, start_iso, end_iso)
    return f"SUCCESS: Event '{summary}' created for {start_iso}."


@tool
def send_reply(
        text: Annotated[str, "Professional reply text in the language of the original email."],
        raw_content: Annotated[Dict[str, Any], InjectedState("raw_content")],
        config: RunnableConfig
):
    """Odešle odpověď odesílateli. VYŽADUJE PŘEDCHOZÍ SCHVÁLENÍ."""
    gmail = config["configurable"]["email"]
    raw_msg = raw_content or {}

    if not raw_msg:
        # Fallback pokud by tool volal někdo "zvenčí", ale v grafu to nenastane
        raw_msg = gmail.get_message(config["configurable"]["thread_id"])

    gmail.send_reply(raw_msg, text)
    return "SUCCESS: Reply sent to original sender."


@tool
def archive_and_label(
        primary_label: Annotated[str, "MEETING_REQUEST, TASK, INFO_ONLY, SALES_OUTREACH, MARKETING, or SPAM"],
        is_urgent: bool,
        config: RunnableConfig
):
    """Oštítkuje a archivuje email. Bezpečná akce (není třeba schválení)."""
    gmail = config["configurable"]["email"]
    email_id = config["configurable"]["thread_id"]

    labels = [primary_label]
    if is_urgent:
        labels.append("URGENT")
    if primary_label == "INFO_ONLY":
        labels.append("Finance")

    gmail.modify_labels(email_id, add=labels, remove=["INBOX"])
    return f"SUCCESS: Email labeled {labels} and moved to archive."


@tool
def flag_email(config: RunnableConfig):
    """Označí email hvězdičkou (STARRED)."""
    gmail = config["configurable"]["email"]
    email_id = config["configurable"]["thread_id"]
    gmail.modify_labels(email_id, add=["STARRED"])
    return "SUCCESS: Email flagged."


@tool
def notify_manager(
        reason: str,
        config: RunnableConfig
):
    """Upozorní manažera na urgentní věc. VYŽADUJE PŘEDCHOZÍ SCHVÁLENÍ."""
    gmail = config["configurable"]["email"]
    workflow_id = config["configurable"]["thread_id"]

    subject = f"[TASK] Attention Required: WF-{workflow_id}"
    body = f"Manager notification triggered.\nReason: {reason}\nWorkflow ID: {workflow_id}"

    gmail.send_message(settings.MANAGER_EMAIL, subject, body)
    return "SUCCESS: Manager notified."


@tool
def ask_manager_for_approval(
        proposed_action: str,
        reason: str,
        raw_content: Annotated[Dict[str, Any], InjectedState("raw_content")],
        config: RunnableConfig
):
    """
    Sends an approval request to the manager.
    MUST be called before any sensitive action (calendar, reply, notify).
    """
    gmail = config["configurable"]["email"]
    workflow_id = config["configurable"]["thread_id"]

    # Idempotence Check
    if gmail.has_label(workflow_id, "PENDING_APPROVAL"):
        return "SKIP: Approval is already pending. Do not send duplicate requests."

    raw_msg = raw_content or {}
    headers = get_headers(raw_msg) if raw_msg else {}
    subject = headers.get("Subject") or raw_msg.get("snippet") or "Email"

    body = (
        f"The AI Agent is requesting your approval for an action.\n\n"
        f"PROPOSED ACTION: {proposed_action}\n"
        f"REASON: {reason}\n"
        f"WORKFLOW ID: {workflow_id}\n\n"
        f"Please reply to this email with either APPROVE or REJECT."
    )

    gmail.send_message(
        settings.MANAGER_EMAIL,
        f"[APPROVAL REQUIRED] [WF:{workflow_id}] {subject}",
        body
    )
    gmail.modify_labels(workflow_id, add=["PENDING_APPROVAL"])
    return "SUCCESS: Approval request sent. Waiting for manager's response."

def get_tool_sets():
    safe_tools = [
        check_availability,
        archive_and_label,
        flag_email,
        ask_manager_for_approval,
    ]
    sensitive_tools = [create_calendar_event, notify_manager]

    # SALES reply approval is configurable by assignment.
    if settings.SALES_REPLY_REQUIRES_APPROVAL:
        sensitive_tools.append(send_reply)
    else:
        safe_tools.append(send_reply)

    return safe_tools, sensitive_tools


def get_sensitive_tool_names() -> set[str]:
    """Single place for resolving currently sensitive tool names."""
    _, sensitive_tools = get_tool_sets()
    return {tool.name for tool in sensitive_tools}


def get_safe_tool_names() -> set[str]:
    """Single place for resolving currently safe tool names."""
    safe_tools, _ = get_tool_sets()
    return {tool.name for tool in safe_tools}


def get_all_tools():
    """Return currently active tool list in execution order."""
    safe_tools, sensitive_tools = get_tool_sets()
    return safe_tools + sensitive_tools
