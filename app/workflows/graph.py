import functools
import logging
from typing import Literal

from langchain_core.messages import ToolMessage
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
    """
    Determines if the proposed tools can run, need approval, or if the workflow should terminate.
    Includes protection against duplicate approvals for already executed tools.
    """

    # 1. Exit on terminal state or error
    if state.get("terminal_action_done") or state.get("status") == WorkflowStatus.ERROR:
        return "cleanup"

    # 2. Get tool calls from the latest AI message
    messages = state.get("messages", [])
    last_ai_msg = next((m for m in reversed(messages) if hasattr(m, "tool_calls")), None)
    tool_calls = getattr(last_ai_msg, "tool_calls", []) if last_ai_msg else []

    if not tool_calls:
        return "cleanup"

    # 3. Check for already executed tools to prevent loops (especially for send_reply)
    executed_tool_names = [m.name for m in messages if isinstance(m, ToolMessage)]

    for tc in tool_calls:
        # If LLM tries to send a reply again after one was already sent, terminate to avoid spamming manager
        if tc["name"] == ToolName.SEND_REPLY.value and ToolName.SEND_REPLY.value in executed_tool_names:
            logger.warning("LLM attempted duplicate send_reply. Routing to cleanup.")
            return "cleanup"

    # 4. Bypass policy only when current calls match explicitly approved pending calls.
    if state.get("manager_decision") == ApprovalDecision.APPROVE:
        pending = state.get("pending_approval_tool_calls") or []
        if pending == tool_calls:
            return "tools"
        logger.debug("Manager APPROVE present, but tool calls changed; re-evaluating policy.")

    # 5. Delegate approval decision to the injected policy
    if policy.requires_approval(state, tool_calls):
        logger.debug("Routing to ask_approval (policy blocked): %s", [tc["name"] for tc in tool_calls])
        return "ask_approval"

    return "tools"


def create_email_graph(checkpointer, policy: ApprovalPolicy | None = None):
    """
    Builds and compiles the email processing LangGraph with Human-in-the-loop support.
    """

    if policy is None:
        policy = StandardApprovalPolicy(get_sensitive_tool_names())

    # Create the router with injected policy
    router = functools.partial(routing_logic, policy=policy)

    workflow = StateGraph(EmailAgentState)

    # Register Nodes
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("tools", ToolNode(get_all_tools(), handle_tool_errors=True))
    workflow.add_node("ask_approval", ask_approval_node)
    workflow.add_node("cleanup", cleanup_node)

    # Define Workflow Edges
    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "classify")
    workflow.add_edge("classify", "analyze")

    # Branching from Analyze based on router logic
    workflow.add_conditional_edges(
        "analyze",
        router,
        {"tools": "tools", "ask_approval": "ask_approval", "cleanup": "cleanup"}
    )

    # Branching from Ask Approval after manager intervention
    workflow.add_conditional_edges(
        "ask_approval",
        lambda state: "tools" if state.get("manager_decision") == ApprovalDecision.APPROVE else "cleanup",
        {"tools": "tools", "cleanup": "cleanup"}
    )

    # Cycle back to analyze after tool execution to allow LLM to evaluate results
    workflow.add_edge("tools", "analyze")
    workflow.add_edge("cleanup", END)

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["ask_approval"]
    )
