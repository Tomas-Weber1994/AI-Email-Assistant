from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from app.workflows.state import EmailAgentState, EmailClassification
from app.workflows.tools import get_all_tools, ToolName
from app.workflows.prompts import get_agent_system_prompt
from app.workflows.policies import apply_sales_outreach_guard
from app.utils.email_utils import get_headers, get_body
from app.settings import settings
from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.schemas.classification import GmailReservedLabel, GmailSystemLabel

import json
import logging
from copy import deepcopy
from typing import Any, TypedDict

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit_trail")


class _RuntimeConfig(TypedDict):
    email: Any
    llm: Any
    thread_id: str | None


def _runtime_config(config: RunnableConfig) -> _RuntimeConfig:
    configurable = config["configurable"]
    return {
        "email": configurable["email"],
        "llm": configurable["llm"],
        "thread_id": configurable.get("thread_id"),
    }


def _sanitize_messages_for_openai(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Remove invalid assistant/tool sequences before sending history back to the LLM."""
    sanitized: list[BaseMessage] = []
    i = 0

    while i < len(messages):
        msg = messages[i]

        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", []) or []
            if not tool_calls:
                sanitized.append(msg)
                i += 1
                continue

            pending_ids = {tc.get("id") for tc in tool_calls if tc.get("id")}
            collected_tools: list[ToolMessage] = []
            j = i + 1

            while j < len(messages):
                next_msg = messages[j]
                if not isinstance(next_msg, ToolMessage):
                    break
                tool_msg = next_msg
                if tool_msg.tool_call_id in pending_ids:
                    pending_ids.remove(tool_msg.tool_call_id)
                    collected_tools.append(tool_msg)
                j += 1

            if not pending_ids:
                sanitized.append(msg)
                sanitized.extend(collected_tools)

            i = j
            continue

        if isinstance(msg, ToolMessage):
            i += 1
            continue

        sanitized.append(msg)
        i += 1

    return sanitized



def _extract_email_parts(raw_msg: dict) -> tuple[str, str, str]:
    """Returns (sender, subject, body) from a raw Gmail message."""
    headers = get_headers(raw_msg)
    sender = raw_msg.get("from") or headers.get("From", "unknown")
    subject = raw_msg.get("subject") or headers.get("Subject", "")
    body = raw_msg.get("body") or get_body(raw_msg)
    return sender, subject, body


def _state_email_id(state: EmailAgentState) -> str | None:
    return state.get("email_id")


def _analyze_guard_result(state: EmailAgentState, analyze_passes: int) -> dict | None:
    email_id = _state_email_id(state)

    if analyze_passes > settings.MAX_ANALYZE_PASSES:
        logger.warning("Pass limit exceeded for email %s", email_id)
        return {
            "status": WorkflowStatus.ERROR,
            "analyze_passes": analyze_passes,
            "audit_log": [f"ANALYZE: Pass limit exceeded ({settings.MAX_ANALYZE_PASSES}), workflow terminated with ERROR."],
        }

    if state.get("terminal_action_done"):
        logger.debug("Terminal action already marked for email %s", email_id)
        return {
            "analyze_passes": analyze_passes,
            "terminal_action_done": True,
            "audit_log": ["ANALYZE: Terminal action already completed."],
        }

    runtime_messages = state.get("messages", [])
    last_runtime_msg = runtime_messages[-1] if runtime_messages else None
    if isinstance(last_runtime_msg, ToolMessage) and last_runtime_msg.name == ToolName.ARCHIVE_AND_LABEL.value:
        logger.debug("Detected terminal tool completion for email %s", email_id)
        return {
            "analyze_passes": analyze_passes,
            "terminal_action_done": True,
            "audit_log": ["ANALYZE: Terminal tool completed, proceeding to cleanup."],
        }

    return None


def _build_analyze_messages(state: EmailAgentState) -> tuple[list[BaseMessage], list[BaseMessage]]:
    history = _sanitize_messages_for_openai(state.get("messages", []))
    messages = [SystemMessage(content=get_agent_system_prompt())] + history
    return history, messages


def _approval_replay_result(
    state: EmailAgentState,
    history: list[BaseMessage],
    messages: list[BaseMessage],
    analyze_passes: int,
) -> dict | None:
    email_id = _state_email_id(state)

    if not history:
        logger.error("Empty message history for email %s", email_id)
        return {
            "status": WorkflowStatus.ERROR,
            "analyze_passes": analyze_passes,
            "audit_log": ["ANALYZE: Empty message history, cannot analyze."],
        }

    last_msg = history[-1]
    if isinstance(last_msg, HumanMessage) and "APPROVE" in last_msg.content.upper():
        approved_snapshot = deepcopy(state.get("pending_approval_tool_calls") or [])
        if approved_snapshot:
            logger.info("Replaying %d manager-approved tool call(s)", len(approved_snapshot))
            return {
                "messages": [AIMessage(content="Replaying manager-approved actions.", tool_calls=approved_snapshot)],
                "analyze_passes": analyze_passes,
                "audit_log": [f"ANALYZE: Replaying approved tools: {[tc.get('name') for tc in approved_snapshot]}"],
            }

        last_ai_msg = next((m for m in reversed(history) if hasattr(m, "tool_calls") and m.tool_calls), None)
        if last_ai_msg:
            approved_tool_names = [tc["name"] for tc in getattr(last_ai_msg, "tool_calls", [])]
            messages.append(SystemMessage(
                content=f"Manager approved the action. Re-generate the same tool_calls for: {approved_tool_names}"
            ))

    return None


def ingest_node(state: EmailAgentState, config: RunnableConfig):
    runtime = _runtime_config(config)
    email_id = state.get("email_id") or runtime["thread_id"]
    email_service = runtime["email"]

    logger.info("Ingesting email %s", email_id)
    raw_msg = email_service.get_message(email_id)
    sender, subject, body = _extract_email_parts(raw_msg)
    content = f"From: {sender}\nSubject: {subject}\nBody: {body}"

    return {
        "email_id": email_id,
        "messages": [HumanMessage(content=content)],
        "raw_content": raw_msg,
        "analyze_passes": 0,
        "terminal_action_done": False,
        "manager_decision": None,
        "status": WorkflowStatus.PROCESSING,
        "audit_log": [f"START: Email {email_id} fetched, workflow started."],
    }


def classify_node(state: EmailAgentState, config: RunnableConfig):
    llm = _runtime_config(config)["llm"].with_structured_output(EmailClassification)
    raw_msg = state.get("raw_content", {})
    sender, subject, body = _extract_email_parts(raw_msg)

    classification = llm.invoke([HumanMessage(content=f"From: {sender}\nSubject: {subject}\nBody: {body}")])
    label_str = f"{classification.label}" + (" + URGENT" if classification.is_urgent else "")

    logger.info("Classified email %s as %s", _state_email_id(state), label_str)

    return {
        "classification": classification,
        "audit_log": [f"CLASSIFY: Email classified as {label_str}."],
    }


def analyze_node(state: EmailAgentState, config: RunnableConfig):
    llm = _runtime_config(config)["llm"]
    model = llm.bind_tools(get_all_tools())
    analyze_passes = int(state.get("analyze_passes", 0)) + 1
    email_id = _state_email_id(state)

    logger.info("Analyzing email %s (pass %d/%d)", email_id, analyze_passes, settings.MAX_ANALYZE_PASSES)

    guard_result = _analyze_guard_result(state, analyze_passes)
    if guard_result:
        return guard_result

    history, messages = _build_analyze_messages(state)

    replay_result = _approval_replay_result(state, history, messages, analyze_passes)
    if replay_result:
        return replay_result

    response = model.invoke(messages)
    response = apply_sales_outreach_guard(response, state)

    proposed = [tc["name"] for tc in getattr(response, "tool_calls", [])]
    logger.debug("Model proposed tools for email %s: %s", email_id, proposed)

    return {
        "messages": [response],
        "analyze_passes": analyze_passes,
        "audit_log": [f"ANALYZE: Model proposed tools: {proposed}"],
    }


def ask_approval_node(state: EmailAgentState, config: RunnableConfig):
    runtime = _runtime_config(config)
    email_service = runtime["email"]
    workflow_id = runtime["thread_id"]
    email_id = state.get("email_id")
    raw_email = state.get("raw_content", {})
    tool_calls = getattr(state["messages"][-1], "tool_calls", [])
    tool_list = [tc["name"] for tc in tool_calls]

    if email_id and email_service.has_label(email_id, GmailSystemLabel.PENDING_APPROVAL.value):
        logger.info("Approval already pending for email %s — tools: %s", email_id, tool_list)
        return {
            "status": WorkflowStatus.WAITING_APPROVAL,
            "pending_approval_tool_calls": deepcopy(tool_calls),
            "audit_log": [f"WAIT: Approval already pending for tools: {tool_list}."],
        }

    if tool_calls:
        action_summary = "; ".join(f"{tc.get('name', 'unknown')}({tc.get('args', {})})" for tc in tool_calls)
        email_service.send_approval_request(raw_email, action_summary, workflow_id)
        if email_id:
            email_service.modify_labels(
                email_id,
                add=[GmailSystemLabel.PENDING_APPROVAL.value],
                remove=[GmailReservedLabel.UNREAD.value],
            )

    logger.info("Approval request sent for email %s — tools: %s", email_id, tool_list)
    return {
        "status": WorkflowStatus.WAITING_APPROVAL,
        "pending_approval_tool_calls": deepcopy(tool_calls),
        "audit_log": [f"WAIT: Approval request sent to manager for tools: {tool_list}."],
    }


def cleanup_node(state: EmailAgentState, config: RunnableConfig | None = None):
    # LangGraph may invoke cleanup with state only depending on node wrapping.
    _ = config
    email_id = state.get("email_id")
    classification = state.get("classification")

    executed_tools = [m.name for m in state["messages"] if isinstance(m, ToolMessage)]

    outcome = "SUCCESS"
    if state.get("manager_decision") == ApprovalDecision.REJECT:
        outcome = "REJECTED_BY_MANAGER"
    if state.get("status") == WorkflowStatus.ERROR:
        outcome = "ERROR"

    audit_entry = {
        "email_id": email_id,
        "label": classification.label if classification else "UNCLASSIFIED",
        "is_urgent": classification.is_urgent if classification else False,
        "actions": executed_tools,
        "outcome": outcome,
        "trace": state.get("audit_log", []),
    }

    audit_logger.info("AUDIT_RECORD: %s", json.dumps(audit_entry, ensure_ascii=False))
    logger.info("Cleanup complete for email %s — outcome: %s", email_id, outcome)

    return {
        "status": WorkflowStatus.COMPLETED,
        "pending_approval_tool_calls": None,
        "audit_log": [f"FINISH: Email processing completed with outcome {outcome}."],
    }
