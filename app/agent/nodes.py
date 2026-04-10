import logging
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig

from app.agent.actions import (
    apply_labels_and_archive, log_spam, flag_and_notify,
    create_calendar_event, send_auto_reply,
)
from app.agent.prompts import classify_email_prompt
from app.agent.state import AgentState
from app.database import db
from app.schemas.classification import EmailClassification, ApprovalStatus, AgentAction
from app.settings import settings
from app.utils.email_utils import get_headers, get_body, build_approval_email

logger = logging.getLogger(__name__)


# --- HELPERS ---

def safe_execute(state: AgentState, action_name: str, func, *args, **kwargs):
    """Universal wrapper for nodes: handles error state, audit log, and persistence."""
    if state.get("error"):
        return state
    try:
        result_audit = func(*args, **kwargs)
        if result_audit:
            state["record"].audit_trail.append(result_audit)
    except Exception as e:
        state["error"] = f"{action_name} failed: {e}"
        logger.error(state["error"])

    db.save(state["record"])
    return state


# --- NODES ---

def ingest_node(state: AgentState, config: RunnableConfig) -> AgentState:
    gmail = config["configurable"]["gmail"]
    msg_id = state["record"].email_id

    def _logic():
        raw = gmail.get_message(msg_id)
        state["raw_email"] = raw
        state["record"].thread_id = raw.get("threadId", "")
        return f"Fetched email {msg_id}"

    return safe_execute(state, "Ingest", _logic)


def classify_node(state: AgentState, config: RunnableConfig) -> AgentState:
    llm = ChatOpenAI(
        model=settings.MODEL_NAME,
        api_key=settings.OPENAI_API_KEY,
    ).with_structured_output(EmailClassification)

    def _logic():
        headers = get_headers(state["raw_email"])
        body = get_body(state["raw_email"])
        cls = llm.invoke(classify_email_prompt(headers, body))

        state["record"].classification = cls
        if cls.requires_approval:
            state["record"].status = ApprovalStatus.PENDING

        return f"Classified as {cls.primary_label.value} (Approval: {cls.requires_approval})"

    return safe_execute(state, "Classification", _logic)


def approval_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """Sends an approval request email to the manager."""
    gmail = config["configurable"]["gmail"]
    rec = state["record"]
    headers = get_headers(state["raw_email"])

    def _logic():
        sent = gmail.send_message(
            to=settings.MANAGER_EMAIL,
            subject=f"[APPROVAL] {headers.get('Subject', 'Request')}",
            body=build_approval_email(headers, rec.classification),
        )
        rec.approval_thread_id = sent.get("threadId", "")
        return f"Approval request sent to {settings.MANAGER_EMAIL}"

    return safe_execute(state, "Approval", _logic)


def action_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """Dispatches the correct Gmail action based on the LLM's proposed_action."""
    gmail = config["configurable"]["gmail"]
    cls = state["record"].classification
    msg_id = state["record"].email_id

    action = cls.proposed_action

    if action == AgentAction.LOG_SPAM:
        return safe_execute(state, "Spam", log_spam, gmail, msg_id)
    elif action == AgentAction.FLAG_NOTIFY:
        return safe_execute(state, "Flag+Notify", flag_and_notify, gmail, msg_id, cls)
    else:
        # ARCHIVE, SEND_REPLY, CREATE_EVENT, NONE — all get labels + archive first
        return safe_execute(
            state, "Labels+Archive",
            apply_labels_and_archive, gmail, msg_id, cls
        )


def calendar_node(state: AgentState, config: RunnableConfig) -> AgentState:
    calendar = config["configurable"]["calendar"]
    gmail = config["configurable"]["gmail"]

    def _logic():
        cls = state["record"].classification
        if not cls.meeting_start:
            raise ValueError("No time parsed from email to check availability.")

        subject = gmail.get_thread_subject(state["record"].thread_id)

        try:
            return create_calendar_event(calendar, cls, subject)
        except RuntimeError as e:
            if "conflict detected" in str(e):
                cls.suggested_reply = (
                    "Thank you for your request. Unfortunately, the proposed time is not available. "
                    "Could you please suggest another time slot?"
                )
                return f"Conflict handled: {e}. Prepared apology reply."
            raise e

    return safe_execute(state, "Calendar", _logic)


def reply_node(state: AgentState, config: RunnableConfig) -> AgentState:
    gmail = config["configurable"]["gmail"]

    def _logic():
        return send_auto_reply(
            gmail, state["raw_email"], state["record"].classification.suggested_reply
        )

    return safe_execute(state, "Reply", _logic)
