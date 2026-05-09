import json
import logging
from copy import deepcopy
from app.schemas.classification import GmailSystemLabel, EmailLabel
from app.schemas.api import WorkflowStatus, ApprovalDecision
from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage
)
from langchain_core.runnables import RunnableConfig

from app.workflows.state import EmailAgentState, EmailClassification
from app.workflows.tools import get_all_tools
from app.workflows import prompts
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
        SystemMessage(content=prompts.get_classification_system_prompt()),
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
        logger.info("Email %s: Manager approved tool execution.", state.get("email_id"))
        return {
            "messages": [AIMessage(content="Executing approved actions.",
                                   tool_calls=state["pending_approval_tool_calls"])],
            "manager_decision": None,
            "pending_approval_tool_calls": None
        }

    runtime = get_runtime_config(config)
    classification = state.get("classification")
    if not classification:
        return {
            "status": WorkflowStatus.ERROR,
            "audit_log": ["ERROR: Missing classification."],
        }

    classification_context = (
        f"Classification: label={classification.label.value}, "
        f"is_urgent={classification.is_urgent}."
    )
    messages = [
        SystemMessage(content=prompts.get_agent_system_prompt()),
        SystemMessage(content=classification_context),
    ] + sanitize_messages_for_openai(state["messages"])

    model = runtime["llm"].bind_tools(get_all_tools())
    logger.debug("Invoking LLM for email %s (Pass %d)", state.get("email_id"), passes)
    response = model.invoke(messages)

    tool_calls = getattr(response, "tool_calls", [])
    if tool_calls:
        tool_names = [tc["name"] for tc in tool_calls]
        logger.info("Email %s: LLM proposed tools %s", state.get("email_id"), tool_names)
    else:
        logger.info("Email %s: LLM proposed no further tools (moving to cleanup).", state.get("email_id"))

    return {
        "messages": [response],
        "analyze_passes": passes,
        "audit_log": [f"ANALYZE: Proposed: {[tc['name'] for tc in tool_calls]}"],
    }


def ask_approval_node(state: EmailAgentState, config: RunnableConfig):
    """Sends a request for manual approval and pauses the workflow."""
    if state.get("status") == WorkflowStatus.WAITING_APPROVAL:
        return {}

    runtime = get_runtime_config(config)
    email_service = runtime["email"]
    email_id = state.get("email_id")
    thread_id = runtime.get("thread_id")
    tool_calls = _latest_tool_calls(state.get("messages"))

    if not tool_calls:
        logger.error("ask_approval_node called without tool_calls.")
        return {"status": WorkflowStatus.ERROR}

    tool_names = [tc["name"] for tc in tool_calls]
    action_summary = json.dumps([{"tool": tc["name"], "args": tc["args"]} for tc in tool_calls])

    try:
        logger.info("Email %s: Requesting manager approval for tools: %s", email_id, tool_names)
        email_service.send_approval_request(state["raw_content"], action_summary, thread_id)

        email_service.modify_labels(
            state["email_id"],
            add=[GmailSystemLabel.PENDING_APPROVAL.value],
        )
    except Exception as e:
        logger.exception(
            "Email %s: Approval request failed; moving workflow to error state.",
            email_id,
        )
        return {
            "status": WorkflowStatus.ERROR,
            "audit_log": [f"ERROR: Approval request failed: {e}"],
        }

    return {
        "status": WorkflowStatus.WAITING_APPROVAL,
        "pending_approval_tool_calls": deepcopy(tool_calls),
        "audit_log": [f"WAIT: Approval requested for: {tool_names}"],
    }


def cleanup_node(state: EmailAgentState, _config: RunnableConfig | None = None):
    """Finalizes the workflow and logs the audit record."""
    email_id = state.get("email_id")
    status = state.get("status")
    decision = state.get("manager_decision")

    if status == WorkflowStatus.ERROR:
        outcome, finish_entry = "ERROR", "FINISH: Outcome ERROR."
    elif decision == ApprovalDecision.REJECT:
        outcome, finish_entry = "REJECTED_BY_MANAGER", "FINISH: Outcome REJECTED_BY_MANAGER."
    elif _archive_succeeded(state.get("messages")):
        outcome, finish_entry = "SUCCESS", "FINISH: Outcome SUCCESS."
    else:
        outcome = "ERROR"
        finish_entry = "ERROR: Missing successful archive_and_label execution before cleanup."

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
        "audit_log": [finish_entry],
    }


def _archive_succeeded(messages) -> bool:
    return any(
        isinstance(message, ToolMessage) and message.name == "archive_and_label"
        and str(message.content).startswith("SUCCESS:")
        for message in (messages or [])
    )


def _latest_tool_calls(messages) -> list[dict]:
    """Return the most recent non-empty tool_calls from message history."""
    for message in reversed(messages or []):
        calls = getattr(message, "tool_calls", None)
        if isinstance(calls, list) and calls:
            return calls
    return []


