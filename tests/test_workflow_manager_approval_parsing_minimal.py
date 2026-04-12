from app.schemas.api import ApprovalDecision
from app.services.workflow_manager import WorkflowManager


def test_extract_manager_decision_accepts_punctuation():
    text = "APPROVE.\n\nThanks"
    assert WorkflowManager._extract_manager_decision(text) == ApprovalDecision.APPROVE


def test_extract_manager_decision_accepts_reject_with_sentence():
    text = "REJECT - please do not send this"
    assert WorkflowManager._extract_manager_decision(text) == ApprovalDecision.REJECT


def test_extract_manager_decision_ignores_non_decision_lines():
    text = "Hello manager here\nPlease proceed"
    assert WorkflowManager._extract_manager_decision(text) is None

