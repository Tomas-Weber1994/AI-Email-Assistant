from typing import cast

from app.schemas.api import WorkflowStatus
from app.workflows.nodes import cleanup_node
from app.workflows.state import EmailAgentState


def test_cleanup_node_accepts_state_only_call():
    state = cast(EmailAgentState, {
        "email_id": "msg-1",
        "messages": [],
        "raw_content": {},
        "classification": None,
        "analyze_passes": 1,
        "terminal_action_done": True,
        "manager_decision": None,
        "pending_approval_tool_calls": [{"name": "send_reply"}],
        "status": WorkflowStatus.PROCESSING,
        "audit_log": ["START: test"],
    })

    result = cleanup_node(state)

    assert result["status"] == WorkflowStatus.COMPLETED
    assert result["pending_approval_tool_calls"] is None
