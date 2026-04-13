import functools
import logging
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.workflows.nodes import (
    ingest_node, classify_node, analyze_node,
    ask_approval_node, cleanup_node
)
from app.workflows.state import EmailAgentState
from app.workflows.tools import get_all_tools, get_sensitive_tool_names
from app.workflows.policies import ApprovalPolicy, StandardApprovalPolicy

logger = logging.getLogger(__name__)


def routing_logic(state: EmailAgentState, policy: ApprovalPolicy) -> Literal["tools", "ask_approval", "cleanup"]:
    if state.get("terminal_action_done") or state.get("status") == WorkflowStatus.ERROR:
        return "cleanup"

    # Get tools proposed in the last message (if any)
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", [])
    if not tool_calls:
        return "cleanup"

    # If policy requires approval for any proposed tool calls, route to ask_approval
    if policy.requires_approval(state, tool_calls):
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

    workflow.add_conditional_edges("analyze", router)
    workflow.add_conditional_edges(
        "ask_approval",
        lambda s: "analyze" if s.get("manager_decision") == ApprovalDecision.APPROVE else "cleanup"
    )
    workflow.add_edge("tools", "analyze")
    workflow.add_edge("cleanup", END)

    return workflow.compile(checkpointer=checkpointer,
                            interrupt_after=["ask_approval"])
