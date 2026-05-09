from unittest.mock import Mock

from langchain_core.messages import AIMessage, ToolMessage

from app.schemas.api import WorkflowStatus, ApprovalDecision
from app.schemas.classification import EmailLabel
from app.workflows.nodes import ask_approval_node, cleanup_node
from app.workflows.state import EmailAgentState, EmailClassification
def _base_state(**overrides) -> EmailAgentState:
    return {
        "email_id": "m1",
        "messages": [],
        "raw_content": {"id": "m1"},
        "classification": EmailClassification(label=EmailLabel.INFO_ONLY, is_urgent=False),
        "analyze_passes": 1,
        "manager_decision": None,
        "pending_approval_tool_calls": None,
        "status": WorkflowStatus.PROCESSING,
        "audit_log": [],
        **overrides,
    }


def test_cleanup_node_completes_even_without_archive_success():
    state = _base_state(messages=[AIMessage(content="done", tool_calls=[])])
    result = cleanup_node(state)
    assert result["status"] == WorkflowStatus.COMPLETED
    assert result["audit_log"] == ["FINISH: Outcome SUCCESS."]


def test_cleanup_node_marks_rejected_when_manager_rejects():
    state = _base_state(
        manager_decision=ApprovalDecision.REJECT,
        messages=[ToolMessage(content="ignored", tool_call_id="tool-1", name="archive_and_label")],
    )
    result = cleanup_node(state)
    assert result["status"] == WorkflowStatus.COMPLETED
    assert result["audit_log"] == ["FINISH: Outcome REJECTED_BY_MANAGER."]


def test_ask_approval_node_waits_when_request_cannot_be_sent():
    email_service = Mock()
    email_service.send_approval_request.side_effect = RuntimeError("SMTP unavailable")
    email_service.modify_labels = Mock()
    calendar = Mock()
    tool_calls = [{"name": "send_reply", "args": {"text": "ok"}, "id": "t1", "type": "tool_call"}]
    state = _base_state(messages=[
        AIMessage(
            content="approval needed",
            tool_calls=tool_calls,
        )
    ])

    result = ask_approval_node(state, {"configurable": {
        "email": email_service,
        "llm": object(),
        "calendar": calendar,
        "thread_id": "thread-1",
    }})
    assert result["status"] == WorkflowStatus.WAITING_APPROVAL
    assert result["audit_log"] == ["WAIT_ERROR: Network failed during approval request. Manager check needed."]
    assert result["pending_approval_tool_calls"] == tool_calls
    email_service.modify_labels.assert_not_called()


def test_ask_approval_node_returns_error_when_no_tool_calls():
    state = _base_state(messages=[AIMessage(content="no tools", tool_calls=[])])
    result = ask_approval_node(state, {"configurable": {
        "email": Mock(),
        "llm": object(),
        "calendar": Mock(),
        "thread_id": "thread-1",
    }})
    assert result["status"] == WorkflowStatus.ERROR


def test_ask_approval_node_is_idempotent_while_waiting_approval():
    state = _base_state(
        status=WorkflowStatus.WAITING_APPROVAL,
        messages=[AIMessage(content="approval needed", tool_calls=[{"name": "send_reply", "args": {"text": "ok"}, "id": "t2", "type": "tool_call"}])],
    )
    result = ask_approval_node(state, {"configurable": {
        "email": Mock(),
        "llm": object(),
        "calendar": Mock(),
        "thread_id": "thread-1",
    }})
    assert result == {}
