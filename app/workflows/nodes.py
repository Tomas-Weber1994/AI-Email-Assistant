import json
import logging
from copy import deepcopy

from langchain_core.messages import (
    AIMessage, HumanMessage, ToolMessage, SystemMessage
)
from langchain_core.runnables import RunnableConfig

from app.workflows.state import EmailAgentState, EmailClassification
from app.workflows.tools import get_all_tools, ToolName
from app.workflows.prompts import get_agent_system_prompt
from app.workflows.policies import apply_sales_outreach_guard
from app.schemas.classification import GmailSystemLabel
from app.workflows.utils import (
    get_runtime_config, extract_email_parts,
    sanitize_messages_for_openai
)
from app.settings import settings
from app.schemas.api import ApprovalDecision, WorkflowStatus

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit_trail")


def ingest_node(state: EmailAgentState, config: RunnableConfig):
    """Initializes the state with email content and metadata."""
    runtime = get_runtime_config(config)
    email_id = state.get("email_id") or runtime["thread_id"]

    logger.info("Ingesting email %s", email_id)
    raw_msg = runtime["email"].get_message(email_id)
    sender, subject, body = extract_email_parts(raw_msg)

    return {
        "email_id": email_id,
        "messages": [HumanMessage(content=f"From: {sender}\nSubject: {subject}\nBody: {body}")],
        "raw_content": raw_msg,
        "analyze_passes": 0,
        "terminal_action_done": False,
        "manager_decision": None,
        "status": WorkflowStatus.PROCESSING,
        "audit_log": [f"START: Email {email_id} ingested."],
    }


def classify_node(state: EmailAgentState, config: RunnableConfig):
    """Categorizes the email and sets urgency flags."""
    runtime = get_runtime_config(config)
    llm = runtime["llm"].with_structured_output(EmailClassification)
    sender, subject, body = extract_email_parts(state["raw_content"])

    logger.debug("Invoking LLM for classification of email %s", state["email_id"])
    classification = llm.invoke([
        HumanMessage(content=f"From: {sender}\nSubject: {subject}\nBody: {body}")
    ])

    label_str = f"{classification.label}" + (" + URGENT" if classification.is_urgent else "")
    logger.info("Classified email %s as %s", state["email_id"], label_str)

    return {
        "classification": classification,
        "audit_log": [f"CLASSIFY: Email classified as {label_str}."],
    }


def analyze_node(state: EmailAgentState, config: RunnableConfig):
    """The brain of the agent. Decides the next action based on message history."""
    passes = int(state.get("analyze_passes", 0)) + 1

    # Safety guard for infinite loops
    if passes > settings.MAX_ANALYZE_PASSES:
        return {"status": WorkflowStatus.ERROR, "audit_log": ["ERROR: Max passes reached."]}

    # Check the last message
    last_msg = state["messages"][-1] if state["messages"] else None

    # On explicit APPROVE, replay the exact approved tool calls (no LLM re-generation).
    pending = state.get("pending_approval_tool_calls") or []
    if (
        state.get("manager_decision") == ApprovalDecision.APPROVE
        and isinstance(last_msg, HumanMessage)
        and str(last_msg.content).strip().upper().startswith(ApprovalDecision.APPROVE.value)
        and pending
    ):
        return {
            "messages": [AIMessage(content="Replaying manager-approved actions.", tool_calls=deepcopy(pending))],
            "analyze_passes": passes,
            "audit_log": [f"ANALYZE: Replaying approved tools: {[tc['name'] for tc in pending]}"],
        }

    # Check for terminal state
    if isinstance(last_msg, ToolMessage) and last_msg.name == ToolName.ARCHIVE_AND_LABEL.value:
        return {"terminal_action_done": True, "audit_log": ["ANALYZE: Terminal tool finished."]}

    # PREPARE HISTORY
    history = sanitize_messages_for_openai(state["messages"])

    if isinstance(last_msg, ToolMessage) and last_msg.name == ToolName.SEND_REPLY.value:
        history.append(SystemMessage(
            content="You have successfully sent the reply. Now you MUST call archive_and_label to finish this email processing."))

    messages = [SystemMessage(content=get_agent_system_prompt())] + history

    runtime = get_runtime_config(config)
    model = runtime["llm"].bind_tools(get_all_tools())

    logger.debug("Invoking LLM for email %s (pass %d)", state["email_id"], passes)
    response = model.invoke(messages)
    response = apply_sales_outreach_guard(response, state)

    proposed = [tc["name"] for tc in getattr(response, "tool_calls", [])]
    return {
        "messages": [response],
        "analyze_passes": passes,
        "audit_log": [f"ANALYZE: Proposed: {proposed}"],
    }


def ask_approval_node(state: EmailAgentState, config: RunnableConfig):
    """Sends a request for manual approval for sensitive actions."""
    runtime = get_runtime_config(config)
    email_service = runtime["email"]

    # Retrieve tool calls from the last AI message
    last_ai_msg = next((m for m in reversed(state["messages"]) if hasattr(m, "tool_calls")), None)
    tool_calls = getattr(last_ai_msg, "tool_calls", []) if last_ai_msg else []

    if not tool_calls:
        return {"status": WorkflowStatus.ERROR}

    # If we are already waiting for approval for the same pending actions, do not resend.
    pending = state.get("pending_approval_tool_calls") or []
    if state.get("status") == WorkflowStatus.WAITING_APPROVAL and pending == tool_calls:
        return {
            "status": WorkflowStatus.WAITING_APPROVAL,
            "audit_log": ["WAIT: Approval already requested; skipping duplicate notification."],
        }

    action_summary = json.dumps([{"tool": tc["name"], "args": tc["args"]} for tc in tool_calls])
    email_service.send_approval_request(state["raw_content"], action_summary, runtime.get("thread_id"))

    # Mark the source email as pending approval so unread polling does not re-ingest it.
    email_service.modify_labels(
        state["email_id"],
        add=[GmailSystemLabel.PENDING_APPROVAL.value],
    )

    return {
        "status": WorkflowStatus.WAITING_APPROVAL,
        "pending_approval_tool_calls": deepcopy(tool_calls),
        "audit_log": [f"WAIT: Approval requested for: {[tc['name'] for tc in tool_calls]}"],
    }


def cleanup_node(state: EmailAgentState, config: RunnableConfig | None = None):
    """Finalizes the workflow and logs the outcome."""
    email_id = state.get("email_id")
    outcome = "SUCCESS"

    if state.get("status") == WorkflowStatus.ERROR:
        outcome = "ERROR"
    elif state.get("manager_decision") == ApprovalDecision.REJECT:
        outcome = "REJECTED_BY_MANAGER"

    audit_record = {
        "email_id": email_id,
        "outcome": outcome,
        "label": state["classification"].label if state.get("classification") else "N/A",
        "trace": state.get("audit_log", [])
    }

    audit_logger.info("AUDIT_RECORD: %s", json.dumps(audit_record, ensure_ascii=False))
    logger.info("Cleanup complete for %s. Outcome: %s", email_id, outcome)

    return {
        "status": WorkflowStatus.COMPLETED,
        "pending_approval_tool_calls": None,
        "manager_decision": None,
        "audit_log": [f"FINISH: Outcome {outcome}."]
    }
