import functools
import logging
from typing import Literal

from langchain_core.messages import ToolMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.workflows.nodes import (
    ingest_node, classify_node, analyze_node,
    ask_approval_node, cleanup_node
)
from app.workflows.state import EmailAgentState
from app.workflows.tools import get_all_tools, get_sensitive_tool_names, ToolName
from app.workflows.policies import ApprovalPolicy, StandardApprovalPolicy

logger = logging.getLogger(__name__)

def routing_logic(state: EmailAgentState, policy: ApprovalPolicy) -> Literal["tools", "ask_approval", "cleanup"]:
    # 1. Konec na terminal nebo chybu
    if state.get("terminal_action_done") or state.get("status") == WorkflowStatus.ERROR:
        return "cleanup"

    # 2. Získání tool calls
    messages = state.get("messages", [])
    last_ai_msg = next((m for m in reversed(messages) if hasattr(m, "tool_calls")), None)
    tool_calls = getattr(last_ai_msg, "tool_calls", []) if last_ai_msg else []

    if not tool_calls:
        return "cleanup"

    # 3. Prevence duplicit (např. odeslání odpovědi)
    executed_tool_names = [m.name for m in messages if isinstance(m, ToolMessage)]
    for tc in tool_calls:
        if tc["name"] == ToolName.SEND_REPLY.value and ToolName.SEND_REPLY.value in executed_tool_names:
            return "cleanup"

    # 4. DETEKCE REPLAYE (Klíčová změna)
    # Pokud poslední zpráva je náš replay z analyze_node, jdeme rovnou do tools
    if isinstance(last_ai_msg, AIMessage) and "manager-approved" in str(last_ai_msg.content):
        return "tools"

    # 5. Policy Check
    if policy.requires_approval(state, tool_calls):
        # Pokud už manažer v tomto běhu schválil (ale ještě jsme neudělali replay), pustíme to
        if state.get("manager_decision") == ApprovalDecision.APPROVE:
            return "tools"
        return "ask_approval"

    return "tools"

def create_email_graph(checkpointer, policy: ApprovalPolicy | None = None):
    if policy is None:
        policy = StandardApprovalPolicy(get_sensitive_tool_names())

    router = functools.partial(routing_logic, policy=policy)
    workflow = StateGraph(EmailAgentState)

    workflow.add_node("ingest", ingest_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("tools", ToolNode(get_all_tools(), handle_tool_errors=True))
    workflow.add_node("ask_approval", ask_approval_node)
    workflow.add_node("cleanup", cleanup_node)

    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "classify")
    workflow.add_edge("classify", "analyze")

    # Z analýzy do routeru
    workflow.add_conditional_edges(
        "analyze",
        router,
        {"tools": "tools", "ask_approval": "ask_approval", "cleanup": "cleanup"}
    )

    # Z ask_approval se vracíme do ANALYZE (aby proběhl ten replay kód)
    workflow.add_conditional_edges(
        "ask_approval",
        lambda state: "analyze" if state.get("manager_decision") == ApprovalDecision.APPROVE else "cleanup",
        {"analyze": "analyze", "cleanup": "cleanup"}
    )

    workflow.add_edge("tools", "analyze")
    workflow.add_edge("cleanup", END)

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["ask_approval"]
    )