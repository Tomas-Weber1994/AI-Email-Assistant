# app/agent/graph.py
from typing import Literal
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes import (
    ingest_node,
    classify_node,
    action_node,
    approval_node,
    calendar_node,
    reply_node
)
from app.schemas.classification import AgentAction


# --- ROUTERS (graph decision logic) ---

def _start_router(state: AgentState) -> Literal["classify", "action"]:
    """Skip classification on retry — we already have a classification from the first run."""
    if state.get("is_retry") and state["record"].classification:
        return "action"
    return "classify"


def _classify_router(state: AgentState) -> Literal["approval", "action", "end"]:
    """Route based on LLM classification: approval-required vs. autonomous action."""
    if state.get("error"):
        return "end"

    cls = state["record"].classification
    if not cls:
        return "end"

    return "approval" if cls.requires_approval else "action"


def _action_router(state: AgentState) -> Literal["calendar", "reply", "end"]:
    """After action_node (labels/archive/spam/flag), decide next step."""
    if state.get("error"):
        return "end"

    cls = state["record"].classification

    # SPAM and FLAG_NOTIFY are terminal — no further steps needed
    if cls.proposed_action in (AgentAction.LOG_SPAM, AgentAction.FLAG_NOTIFY):
        return "end"

    # Calendar events for meeting requests
    if cls.proposed_action == AgentAction.CREATE_EVENT:
        return "calendar"

    # Auto-reply (e.g. SALES_OUTREACH polite decline, MARKETING acknowledgement)
    if cls.suggested_reply:
        return "reply"

    return "end"


def _post_calendar_router(state: AgentState) -> Literal["reply", "end"]:
    """After calendar event creation, send a reply if one was prepared."""
    cls = state["record"].classification
    if cls and cls.suggested_reply:
        return "reply"
    return "end"


# --- GRAPH CONSTRUCTION ---

workflow = StateGraph(AgentState)

# Nodes
workflow.add_node("ingest", ingest_node)
workflow.add_node("classify", classify_node)
workflow.add_node("action", action_node)
workflow.add_node("approval", approval_node)
workflow.add_node("calendar", calendar_node)
workflow.add_node("reply", reply_node)

# Edges
workflow.set_entry_point("ingest")

# 1. After Ingest: classify new emails, skip to action for retries
workflow.add_conditional_edges("ingest", _start_router, {
    "classify": "classify",
    "action": "action"
})

# 2. After Classification: approval required or autonomous action?
workflow.add_conditional_edges("classify", _classify_router, {
    "approval": "approval",
    "action": "action",
    "end": END
})

# 3. Approval request sent → workflow pauses until manager responds
workflow.add_edge("approval", END)

# 4. After action: calendar / reply / done
workflow.add_conditional_edges("action", _action_router, {
    "calendar": "calendar",
    "reply": "reply",
    "end": END
})

# 5. After calendar: optional reply, then done
workflow.add_conditional_edges("calendar", _post_calendar_router, {
    "reply": "reply",
    "end": END
})

# 6. Reply → done
workflow.add_edge("reply", END)

# Compile
app = workflow.compile()
