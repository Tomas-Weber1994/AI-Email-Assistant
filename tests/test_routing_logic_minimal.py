from typing import cast

from langchain_core.messages import AIMessage

from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.schemas.classification import EmailLabel
from app.workflows.graph import routing_logic
from app.workflows.policies import ApprovalPolicy
from app.workflows.state import EmailClassification, EmailAgentState


class StubPolicy(ApprovalPolicy):
    def __init__(self, value: bool):
        self.value = value
        self.called = False

    def requires_approval(self, state, tool_calls):
        self.called = True
        return self.value


def _base_state() -> EmailAgentState:
    return cast(EmailAgentState, {
        "email_id": "m1",
        "messages": [],
        "raw_content": {},
        "classification": EmailClassification(label=EmailLabel.TASK, is_urgent=False),
        "analyze_passes": 1,
        "terminal_action_done": False,
        "manager_decision": None,
        "pending_approval_tool_calls": None,
        "status": WorkflowStatus.PROCESSING,
        "audit_log": [],
    })


def test_routing_goes_cleanup_when_no_tool_calls():
    state = _base_state()
    policy = StubPolicy(value=True)

    decision = routing_logic(state, policy)

    assert decision == "cleanup"
    assert policy.called is False


def test_routing_bypasses_policy_when_manager_approved():
    state = _base_state()
    state["manager_decision"] = ApprovalDecision.APPROVE
    state["messages"] = [
        AIMessage(
            content="run",
            tool_calls=[{"name": "send_reply", "args": {"text": "ok"}, "id": "t1", "type": "tool_call"}],
        )
    ]
    policy = StubPolicy(value=True)

    decision = routing_logic(state, policy)

    assert decision == "tools"
    assert policy.called is False


def test_routing_sends_to_ask_approval_when_policy_blocks():
    state = _base_state()
    state["messages"] = [
        AIMessage(
            content="run",
            tool_calls=[{"name": "send_reply", "args": {"text": "ok"}, "id": "t2", "type": "tool_call"}],
        )
    ]
    policy = StubPolicy(value=True)

    decision = routing_logic(state, policy)

    assert decision == "ask_approval"
    assert policy.called is True

