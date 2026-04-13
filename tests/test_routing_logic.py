from typing import cast

from langchain_core.messages import AIMessage

from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.schemas.classification import EmailLabel
from app.workflows.graph import routing_logic
from app.workflows.policies import ApprovalPolicy
from app.workflows.state import EmailClassification, EmailAgentState


class DeterministicApprovalPolicy(ApprovalPolicy):
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
    state["messages"] = [AIMessage(content="done", tool_calls=[])]
    policy = DeterministicApprovalPolicy(value=True)

    decision = routing_logic(state, policy)

    assert decision == "cleanup"
    assert policy.called is False


def test_routing_routes_to_ask_approval_and_calls_policy_when_manager_approved():
    state = _base_state()
    state["manager_decision"] = ApprovalDecision.APPROVE
    approved_calls = [{"name": "send_reply", "args": {"text": "ok"}, "id": "t1", "type": "tool_call"}]
    state["pending_approval_tool_calls"] = approved_calls
    state["messages"] = [
        AIMessage(
            content="Executing approved actions.",
            tool_calls=approved_calls,
        )
    ]
    policy = DeterministicApprovalPolicy(value=True)

    decision = routing_logic(state, policy)

    assert decision == "ask_approval"
    assert policy.called is True


def test_routing_rechecks_policy_when_manager_approved_but_calls_changed():
    state = _base_state()
    state["manager_decision"] = ApprovalDecision.APPROVE
    state["pending_approval_tool_calls"] = [
        {"name": "send_reply", "args": {"text": "old"}, "id": "t-old", "type": "tool_call"}
    ]
    state["messages"] = [
        AIMessage(
            content="run",
            tool_calls=[{"name": "send_reply", "args": {"text": "new"}, "id": "t-new", "type": "tool_call"}],
        )
    ]
    policy = DeterministicApprovalPolicy(value=True)

    decision = routing_logic(state, policy)

    assert decision == "ask_approval"
    assert policy.called is True


def test_routing_sends_to_ask_approval_when_policy_blocks():
    state = _base_state()
    state["messages"] = [
        AIMessage(
            content="run",
            tool_calls=[{"name": "send_reply", "args": {"text": "ok"}, "id": "t2", "type": "tool_call"}],
        )
    ]
    policy = DeterministicApprovalPolicy(value=True)

    decision = routing_logic(state, policy)

    assert decision == "ask_approval"
    assert policy.called is True

