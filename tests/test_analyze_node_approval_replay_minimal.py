from typing import cast

from langchain_core.messages import AIMessage, HumanMessage

from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.schemas.classification import EmailLabel
from app.workflows.nodes import analyze_node
from app.workflows.state import EmailAgentState, EmailClassification


def test_analyze_replays_exact_pending_tool_calls_after_approve():
    approved_calls = [
        {"name": "send_reply", "args": {"text": "Approved exact text"}, "id": "tc1", "type": "tool_call"}
    ]

    state = cast(EmailAgentState, {
        "email_id": "m1",
        "messages": [
            AIMessage(content="proposal", tool_calls=approved_calls),
            HumanMessage(content="APPROVE"),
        ],
        "raw_content": {},
        "classification": EmailClassification(label=EmailLabel.MEETING_REQUEST, is_urgent=False),
        "analyze_passes": 0,
        "terminal_action_done": False,
        "manager_decision": ApprovalDecision.APPROVE,
        "pending_approval_tool_calls": approved_calls,
        "status": WorkflowStatus.PROCESSING,
        "audit_log": [],
    })

    result = analyze_node(state, {"configurable": {"thread_id": "m1", "email": object(), "llm": object()}})

    replay_msg = result["messages"][0]
    assert isinstance(replay_msg, AIMessage)
    assert replay_msg.tool_calls == approved_calls

