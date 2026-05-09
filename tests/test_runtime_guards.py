from unittest.mock import Mock

from langchain_core.messages import AIMessage, ToolMessage

from app.schemas.api import WorkflowStatus
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


def test_cleanup_node_errors_when_archive_and_label_did_not_succeed():
    state = _base_state(messages=[AIMessage(content="done", tool_calls=[])])
    result = cleanup_node(state)
    assert result["status"] == WorkflowStatus.ERROR
    assert result["audit_log"] == [
        "ERROR: Missing successful archive_and_label execution before cleanup."
    ]


def test_cleanup_node_completes_after_successful_archive_and_label():
    state = _base_state(messages=[
        ToolMessage(
            content="SUCCESS: Archived with labels ['INFO_ONLY']. Workflow finished.",
            tool_call_id="tool-1",
            name="archive_and_label",
        )
    ])
    result = cleanup_node(state)
    assert result["status"] == WorkflowStatus.COMPLETED
    assert result["audit_log"] == ["FINISH: Outcome SUCCESS."]


def test_ask_approval_node_returns_error_when_request_cannot_be_sent():
    email_service = Mock()
    email_service.send_approval_request.side_effect = RuntimeError("SMTP unavailable")
    email_service.modify_labels = Mock()
    calendar = Mock()
    state = _base_state(messages=[
        AIMessage(
            content="approval needed",
            tool_calls=[{"name": "send_reply", "args": {"text": "ok"}, "id": "t1", "type": "tool_call"}],
        )
    ])

    result = ask_approval_node(state, {"configurable": {
        "email": email_service,
        "llm": object(),
        "calendar": calendar,
        "thread_id": "thread-1",
    }})
    assert result["status"] == WorkflowStatus.ERROR
    assert result["audit_log"] == ["ERROR: Approval request failed: SMTP unavailable"]
    email_service.modify_labels.assert_not_called()
