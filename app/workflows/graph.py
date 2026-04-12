from typing import Literal
import logging
import functools

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.workflows.state import EmailAgentState
from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.workflows.nodes import (
    ingest_node,
    classify_node,
    ask_approval_node,
    cleanup_node,
    analyze_node,
)
from app.workflows.tools import get_all_tools, get_sensitive_tool_names
from app.workflows.policies import ApprovalPolicy, StandardApprovalPolicy

logger = logging.getLogger(__name__)


# --- ROUTING LOGIC ---

def routing_logic(state: EmailAgentState, policy: ApprovalPolicy) -> Literal["tools", "ask_approval", "cleanup"]:
    """
    Determines the next node from analyze.
    Policy encapsulates all label-specific approval rules;
    the router only handles universal flow-control conditions.
    """
    classification = state.get("classification")
    messages = state.get("messages", [])

    # Guard: abort on missing classification or error state.
    if not classification or state.get("status") == WorkflowStatus.ERROR:
        logger.debug("Routing to cleanup (no classification or error state)")
        return "cleanup"

    # 1. Explicit terminal flag set by analyze after terminal tool completion.
    if state.get("terminal_action_done"):
        logger.debug("Routing to cleanup (terminal_action_done=true)")
        return "cleanup"

    # 2. Explicit manager rejection short-circuits to cleanup.
    manager_decision = state.get("manager_decision")
    if manager_decision == ApprovalDecision.REJECT:
        logger.debug("Routing to cleanup (manager rejected)")
        return "cleanup"

    # 3. Check for pending tool calls from the last LLM output.
    last_ai_msg = next((m for m in reversed(messages) if hasattr(m, "tool_calls")), None)
    tool_calls = list(getattr(last_ai_msg, "tool_calls", []) or []) if last_ai_msg else []
    if not tool_calls:
        logger.debug("Routing to cleanup (no tool calls proposed)")
        return "cleanup"

    # Already approved — bypass policy check.
    if manager_decision == ApprovalDecision.APPROVE:
        logger.debug("Routing to tools (manager approved): %s", [tc["name"] for tc in tool_calls])
        return "tools"

    # Delegate approval decision to the injected policy.
    if policy.requires_approval(state, tool_calls):
        logger.debug("Routing to ask_approval (policy blocked): %s", [tc["name"] for tc in tool_calls])
        return "ask_approval"

    logger.debug("Routing to tools: %s", [tc["name"] for tc in tool_calls])
    return "tools"


# --- GRAPH CONSTRUCTION ---

def create_email_graph(checkpointer, policy: ApprovalPolicy | None = None):
    """
    Builds and compiles the email-processing LangGraph.
    An optional ApprovalPolicy can be injected; defaults to StandardApprovalPolicy.
    """
    if policy is None:
        policy = StandardApprovalPolicy(get_sensitive_tool_names())

    # Bind policy into routing_logic, producing a plain (state) -> str callable.
    router = functools.partial(routing_logic, policy=policy)

    workflow = StateGraph(EmailAgentState)

    # Register nodes
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("tools", ToolNode(get_all_tools(), handle_tool_errors=True))
    workflow.add_node("ask_approval", ask_approval_node)
    workflow.add_node("cleanup", cleanup_node)

    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "classify")
    workflow.add_edge("classify", "analyze")

    # analyze is the central routing hub
    workflow.add_conditional_edges(
        "analyze",
        router,
        {"tools": "tools", "ask_approval": "ask_approval", "cleanup": "cleanup"},
    )

    # Loop back to analyze for re-evaluation after tools or approval.
    workflow.add_edge("ask_approval", "analyze")
    workflow.add_edge("tools", "analyze")

    workflow.add_edge("cleanup", END)

    # Compile with checkpointer; interrupt after ask_approval for human-in-the-loop.
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["ask_approval"],
    )
