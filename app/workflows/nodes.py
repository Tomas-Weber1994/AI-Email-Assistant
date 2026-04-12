import logging
import json
from typing import Dict, Any, List
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableConfig

from app.settings import settings
from app.utils.email_utils import get_body, get_headers
from app.workflows.tools import get_all_tools, get_sensitive_tool_names
from app.workflows.state import EmailAgentState
from app.workflows.prompts import get_agent_system_prompt

# Strukturovaný audit log pro splnění Non-Functional Requirements (NFR)
audit_logger = logging.getLogger("audit_trail")
node_logger = logging.getLogger(__name__)


def _sanitize_messages_for_openai(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Zajišťuje integritu historie zpráv pro OpenAI API.
    Každá ToolMessage musí následovat po příslušném tool_call v AIMessage.
    """
    result: List[BaseMessage] = []
    pending_ids: set = set()

    for msg in messages:
        if isinstance(msg, AIMessage):
            pending_ids = {tc["id"] for tc in (msg.tool_calls or [])}
            result.append(msg)
        elif isinstance(msg, ToolMessage):
            if msg.tool_call_id in pending_ids:
                pending_ids.discard(msg.tool_call_id)
                result.append(msg)
        else:
            pending_ids = set()
            result.append(msg)
    return result


def ingest_node(state: EmailAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Načte email a okamžitě mu odebere label UNREAD (claim)."""
    email_service = config["configurable"]["email"]
    email_id = state["email_id"]

    raw_msg = email_service.get_message(email_id)
    email_service.modify_labels(email_id, remove=["UNREAD"])

    headers = get_headers(raw_msg)
    content = (
        f"Subject: {headers.get('Subject', 'No Subject')}\n"
        f"From: {headers.get('From', 'Unknown Sender')}\n"
        f"Body: {get_body(raw_msg)}"
    )

    return {
        "messages": [HumanMessage(content=content)],
        "raw_content": raw_msg,
        "status": "processing",
        "audit_log": [f"START: Email {email_id} ingestován."]
    }


def analyze_node(state: EmailAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Jádro agenta: rozhoduje o krocích, volá tooly a zpracovává rozhodnutí manažera."""
    previous_passes = state.get("analyze_passes", 0)
    email_id = state.get("email_id", "unknown")

    if previous_passes >= settings.MAX_ANALYZE_PASSES:
        node_logger.warning("Max passes reached for %s", email_id)
        return {
            "messages": [AIMessage(content="MAX_ANALYZE_PASSES_REACHED")],
            "status": "error",
            "audit_log": [f"ERROR: Max analyze passes dosaženo."]
        }

    llm = config["configurable"]["llm"]
    decision = state.get("approval_decision")

    # DYNAMICKÁ KONFIGURACE MODELU
    # Pokud je schváleno, vynutíme tool_choice, aby model nemohl jen mluvit
    if decision == "APPROVE":
        model = llm.bind_tools(get_all_tools(), tool_choice="required")
    else:
        model = llm.bind_tools(get_all_tools())

    sanitized_history = _sanitize_messages_for_openai(state["messages"])
    messages = [SystemMessage(content=get_agent_system_prompt())] + sanitized_history

    if decision:
        if decision == "APPROVE":
            instruction = (
                "MANAGER DECISION: APPROVE. You are now AUTHORIZED. "
                "Execute the requested action tool (e.g., create_calendar_event) IMMEDIATELY. "
                "Do not reply with text only."
            )
        else:
            instruction = f"MANAGER DECISION: {decision}. Finalize and archive now."

        messages.append(HumanMessage(content=instruction))

    # Volání modelu s agresivním nastavením
    response = model.invoke(messages)

    tool_calls = getattr(response, "tool_calls", []) or []
    sensitive_names = get_sensitive_tool_names()
    has_sensitive = any(tc["name"] in sensitive_names for tc in tool_calls)

    current_status = "processing"
    if has_sensitive and decision is None:
        current_status = "waiting_approval"

    return {
        "messages": [response],
        "analyze_passes": previous_passes + 1,
        "status": current_status
    }


def cleanup_node(state: EmailAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Finalizace a úklid labelů."""
    email_service = config["configurable"]["email"]
    email_id = state["email_id"]
    decision = state.get("approval_decision")
    status = state.get("status")

    executed_actions = [tc["name"] for msg in state["messages"] if isinstance(msg, AIMessage) and msg.tool_calls for tc
                        in msg.tool_calls]
    outcome = "ERROR" if status == "error" else (decision if decision else "SUCCESS")

    audit_entry = {
        "email_id": email_id,
        "actions": executed_actions,
        "outcome": outcome
    }
    audit_logger.info(f"AUDIT_ENTRY: {json.dumps(audit_entry)}")

    # Úklid labelů proběhne pouze při ukončení nebo odmítnutí
    if status == "completed" or decision in ["APPROVE", "REJECT"]:
        remove_labels = ["PENDING_APPROVAL", "APPROVAL_REMINDER_SENT"]
        if status != "error":
            remove_labels.append("INBOX")

        email_service.modify_labels(email_id, remove=remove_labels)
        node_logger.info(f"Cleanup: finished for {email_id}.")
    else:
        node_logger.info(f"Cleanup: waiting state for {email_id}.")

    return {"status": "completed" if status != "error" else "error"}
