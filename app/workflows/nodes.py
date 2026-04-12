from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from app.workflows.state import EmailAgentState, EmailClassification
from app.workflows.tools import get_all_tools
from app.utils.email_utils import get_headers, get_body

import json
import logging
from copy import deepcopy
import uuid

# Logger pro audit trail (NFR requirement)
audit_logger = logging.getLogger("audit_trail")


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


def _apply_sales_outreach_guard(response: AIMessage, classification: EmailClassification | None) -> AIMessage:
    """Ensure SALES_OUTREACH always includes send_reply + archive_and_label."""
    if not classification or classification.label != "SALES_OUTREACH":
        return response

    current_calls = list(getattr(response, "tool_calls", []) or [])
    current_names = [tc.get("name") for tc in current_calls]

    if "send_reply" not in current_names:
        decline_text = (
            "Hello,\n\n"
            "Thank you for your message. We are not interested at this time.\n\n"
            "Best regards,\n"
            "Manager (Automatic reply)"
        )
        current_calls.insert(0, {
            "name": "send_reply",
            "args": {"text": decline_text},
            "id": f"sales_reply_{uuid.uuid4().hex[:8]}",
            "type": "tool_call",
        })

    if "archive_and_label" not in current_names:
        current_calls.append({
            "name": "archive_and_label",
            "args": {
                "primary_label": "SALES_OUTREACH",
                "is_urgent": bool(classification.is_urgent),
            },
            "id": f"sales_archive_{uuid.uuid4().hex[:8]}",
            "type": "tool_call",
        })

    return AIMessage(content="Applying SALES_OUTREACH guard.", tool_calls=current_calls)


def ingest_node(state: EmailAgentState, config: RunnableConfig):
    email_id = state.get("email_id") or config["configurable"].get("thread_id")
    email_service = config["configurable"]["email"]

    raw_msg = email_service.get_message(email_id)
    headers = get_headers(raw_msg)
    sender = raw_msg.get("from") or headers.get("From", "unknown")
    subject = raw_msg.get("subject") or headers.get("Subject", "")
    body = raw_msg.get("body") or get_body(raw_msg)
    content = f"From: {sender}\nSubject: {subject}\nBody: {body}"

    return {
        "email_id": email_id,
        "messages": [HumanMessage(content=content)],
        "raw_content": raw_msg,
        "status": "processing",
        "audit_log": [f"START: Email {email_id} stažen a zahájeno zpracování."]
    }


def classify_node(state: EmailAgentState, config: RunnableConfig):
    llm = config["configurable"]["llm"].with_structured_output(EmailClassification)
    raw_msg = state.get("raw_content", {})
    headers = get_headers(raw_msg)
    sender = raw_msg.get("from") or headers.get("From", "unknown")
    subject = raw_msg.get("subject") or headers.get("Subject", "")
    body = raw_msg.get("body") or get_body(raw_msg)

    classify_input = [HumanMessage(content=f"From: {sender}\nSubject: {subject}\nBody: {body}")]
    classification = llm.invoke(classify_input)

    label_str = f"{classification.label}" + (" + URGENT" if classification.is_urgent else "")

    return {
        "classification": classification,
        "audit_log": [f"CLASSIFY: Email klasifikován jako {label_str}."]
    }


def analyze_node(state: EmailAgentState, config: RunnableConfig):
    llm = config["configurable"]["llm"]
    model = llm.bind_tools(get_all_tools())

    # Načtení systémového promptu s aktuálním časem
    from app.workflows.prompts import get_agent_system_prompt
    sys_prompt = get_agent_system_prompt()

    # Sestavení zpráv: systémový prompt musí být první a historie musí být validní pro OpenAI.
    history = _sanitize_messages_for_openai(state.get("messages", []))
    messages = [SystemMessage(content=sys_prompt)] + history

    # Logika pro schválení (ponechat tak, jak máte)
    if not history:
        return {
            "status": "error",
            "audit_log": ["ANALYZE: Chybí historie zpráv, workflow nelze analyzovat."],
        }

    last_msg = history[-1]
    if isinstance(last_msg, HumanMessage) and "APPROVE" in last_msg.content.upper():
        approved_snapshot = deepcopy(state.get("pending_approval_tool_calls") or [])
        if approved_snapshot:
            return {
                "messages": [AIMessage(content="Replaying manager-approved actions.", tool_calls=approved_snapshot)],
                "audit_log": [
                    f"ANALYZE: Replaying approved tools: {[tc.get('name') for tc in approved_snapshot]}"
                ],
            }

        last_ai_msg = next((m for m in reversed(history) if hasattr(m, "tool_calls") and m.tool_calls), None)
        if last_ai_msg:
            approved_tool_names = [tc["name"] for tc in getattr(last_ai_msg, "tool_calls", [])]
            messages.append(SystemMessage(
                content=f"Manažer schválil akci. Znovu vygeneruj stejné tool_calls pro: {approved_tool_names}"
            ))

    response = model.invoke(messages)

    response = _apply_sales_outreach_guard(response, state.get("classification"))

    return {
        "messages": [response],
        "audit_log": [f"ANALYZE: Model navrhl nástroje: {[tc['name'] for tc in getattr(response, 'tool_calls', [])]}"]
    }




def ask_approval_node(state: EmailAgentState, config: RunnableConfig):
    email_service = config["configurable"]["email"]
    workflow_id = config["configurable"].get("thread_id")
    email_id = state.get("email_id")
    raw_email = state.get("raw_content", {})
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", [])

    if email_id and email_service.has_label(email_id, "PENDING_APPROVAL"):
        tool_list = [tc['name'] for tc in tool_calls]
        return {
            "status": "waiting_approval",
            "pending_approval_tool_calls": deepcopy(tool_calls),
            "audit_log": [f"WAIT: Schválení už čeká pro nástroje: {tool_list}."]
        }

    # Odeslání skutečného e-mailu manažerovi
    if tool_calls:
        summary_parts = []
        for tc in tool_calls:
            name = tc.get("name", "unknown")
            args = tc.get("args", {})
            summary_parts.append(f"{name}({args})")
        action_summary = "; ".join(summary_parts)
        email_service.send_approval_request(raw_email, action_summary, workflow_id)
        if email_id:
            email_service.modify_labels(email_id, add=["PENDING_APPROVAL"], remove=["UNREAD"])

    tool_list = [tc['name'] for tc in tool_calls]

    return {
        "status": "waiting_approval",
        "pending_approval_tool_calls": deepcopy(tool_calls),
        "audit_log": [f"WAIT: Odeslána žádost o schválení manažerovi pro nástroje: {tool_list}."]
    }


def cleanup_node(state: EmailAgentState, config: RunnableConfig):
    email_id = state.get("email_id")
    classification = state.get("classification")

    # 1. Analýza provedených akcí pro audit log (ToolMessage potvrzuje skutečné vykonání)
    executed_tools = [
        m.name for m in state["messages"]
        if isinstance(m, ToolMessage)
    ]

    # 2. Určení výsledku (Outcome) na základě historie zpráv
    outcome = "SUCCESS"
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage) and "REJECT" in msg.content.upper():
            outcome = "REJECTED_BY_MANAGER"
            break

    if state.get("status") == "error":
        outcome = "ERROR"

    # 3. Vytvoření strukturovaného logu dle zadání (label, action, outcome)
    # Tento JSON je klíčový pro splnění NFR (Non-Functional Requirements)
    audit_entry = {
        "email_id": email_id,
        "label": classification.label if classification else "UNCLASSIFIED",
        "is_urgent": classification.is_urgent if classification else False,
        "actions": executed_tools,
        "outcome": outcome,
        "trace": state.get("audit_log", [])  # Přidáme i chronologickou stopu
    }

    # Finální zápis do produkčního logu
    audit_logger.info(f"AUDIT_RECORD: {json.dumps(audit_entry, ensure_ascii=False)}")

    # 4. Úklid štítků v Gmailu
    try:
        email_service = config["configurable"]["email"]
        # Příklad: odstranění INBOX labelu až po úspěšném zpracování (pokud už neproběhlo v toolu)
        # email_service.modify_labels(email_id, remove=["INBOX"])
    except Exception as e:
        audit_logger.error(f"Cleanup Gmail error for {email_id}: {str(e)}")

    return {
        "status": "completed",
        "pending_approval_tool_calls": None,
        "audit_log": [f"FINISH: Zpracování emailu dokončeno s výsledkem {outcome}."]
    }
