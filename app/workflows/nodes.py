import time
import json
import logging
from copy import deepcopy
from app.schemas.classification import GmailSystemLabel, EmailLabel
from app.schemas.api import WorkflowStatus, ApprovalDecision
from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage
)
from langchain_core.runnables import RunnableConfig

from app.workflows.state import EmailAgentState, EmailClassification
from app.workflows.tools import get_all_tools
from app.workflows.prompts import get_agent_system_prompt
from app.workflows.utils import (
    extract_email_parts, get_runtime_config, sanitize_messages_for_openai
)
from app.settings import settings

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
    if classification.label == EmailLabel.SPAM:
        classification.is_urgent = False

    label_str = f"{classification.label}" + (" + URGENT" if classification.is_urgent else "")
    logger.info("Classified email %s as %s", state["email_id"], label_str)

    return {
        "classification": classification,
        "audit_log": [f"CLASSIFY: Email classified as {label_str}."],
    }


def analyze_node(state: EmailAgentState, config: RunnableConfig):
    """The brain of the agent. Pure LLM decision-making."""
    passes = int(state.get("analyze_passes", 0)) + 1
    if passes > settings.MAX_ANALYZE_PASSES:
        return {"status": WorkflowStatus.ERROR, "audit_log": ["ERROR: Max passes reached."]}

    # If APPROVE then replay the approved tool calls exactly, bypassing LLM
    if state.get("manager_decision") == ApprovalDecision.APPROVE:
        return {
            "messages": [AIMessage(content="Executing approved actions.",
                                   tool_calls=state["pending_approval_tool_calls"])],
            "manager_decision": None,
            "pending_approval_tool_calls": None
        }

    runtime = get_runtime_config(config)
    messages = [SystemMessage(content=get_agent_system_prompt())] + \
               sanitize_messages_for_openai(state["messages"])

    model = runtime["llm"].bind_tools(get_all_tools())
    logger.debug("Invoking LLM for email %s (Pass %d)", state.get("email_id"), passes)
    response = model.invoke(messages)

    tool_calls = getattr(response, "tool_calls", [])
    if tool_calls:
        tool_names = [tc["name"] for tc in tool_calls]
        logger.info("Email %s: LLM proposed tools %s", state.get("email_id"), tool_names)
    else:
        logger.info("Email %s: LLM proposed no further tools (moving to cleanup).", state.get("email_id"))
    # ------------------------------------

    return {
        "messages": [response],
        "analyze_passes": passes,
        "audit_log": [f"ANALYZE: Proposed: {[tc['name'] for tc in tool_calls]}"],
    }


def ask_approval_node(state: EmailAgentState, config: RunnableConfig):
    """Sends a request for manual approval and pauses the workflow."""
    runtime = get_runtime_config(config)
    email_service = runtime["email"]

    last_ai_msg = next((m for m in reversed(state["messages"]) if hasattr(m, "tool_calls") and m.tool_calls), None)
    tool_calls = getattr(last_ai_msg, "tool_calls", []) if last_ai_msg else []

    if not tool_calls:
        logger.error("ask_approval_node called without tool_calls.")
        return {"status": WorkflowStatus.ERROR}

    if state.get("status") == WorkflowStatus.WAITING_APPROVAL:
        return {}

    tool_names = [tc["name"] for tc in tool_calls]
    action_summary = json.dumps([{"tool": tc["name"], "args": tc["args"]} for tc in tool_calls])

    try:
        logger.info("Email %s: Requesting manager approval for tools: %s", state.get("email_id"), tool_names)
        email_service.send_approval_request(state["raw_content"], action_summary, runtime.get("thread_id"))

        email_service.modify_labels(
            state["email_id"],
            add=[GmailSystemLabel.PENDING_APPROVAL.value],
        )
        audit_msg = f"WAIT: Approval requested for: {tool_names}"

    except Exception as e:
        logger.warning("Email %s: Approval request failed (network error): %s. Forcing wait state.",
                       state.get("email_id"), e)
        audit_msg = f"WAIT_ERROR: Network failed during approval request. Manager check needed."

    return {
        "status": WorkflowStatus.WAITING_APPROVAL,
        "pending_approval_tool_calls": deepcopy(tool_calls),
        "audit_log": [audit_msg],
    }


def cleanup_node(state: EmailAgentState, config: RunnableConfig | None = None):
    """Finalizes the workflow and logs the audit record."""
    email_id = state.get("email_id")

    if state.get("status") == WorkflowStatus.ERROR:
        outcome = "ERROR"
    elif state.get("manager_decision") == ApprovalDecision.REJECT:
        outcome = "REJECTED_BY_MANAGER"
    else:
        outcome = "SUCCESS"

    audit_record = {
        "email_id": email_id,
        "outcome": outcome,
        "label": state["classification"].label if state.get("classification") else "N/A",
        "trace": state.get("audit_log", [])
    }

    audit_logger.info("AUDIT_RECORD: %s", json.dumps(audit_record, ensure_ascii=False))
    logger.info("Cleanup complete for %s. Outcome: %s", email_id, outcome)

    return {
        "status": WorkflowStatus.COMPLETED if outcome != "ERROR" else WorkflowStatus.ERROR,
        "pending_approval_tool_calls": None,
        "manager_decision": None,
        "audit_log": [f"FINISH: Outcome {outcome}."]
    }
