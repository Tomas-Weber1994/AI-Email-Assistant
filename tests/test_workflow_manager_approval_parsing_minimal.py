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


def test_extract_workflow_id_from_subject_tag():
    msg = {
        "threadId": "gmail-thread-1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Re: [APPROVAL REQUIRED] [WF:wf-123] Test"},
            ]
        },
        "snippet": "APPROVE",
    }
    assert WorkflowManager._extract_workflow_id(msg) == "wf-123"


def test_extract_workflow_id_falls_back_to_thread_id_without_tag():
    msg = {
        "threadId": "gmail-thread-legacy",
        "payload": {"headers": [{"name": "Subject", "value": "Re: Approval"}]},
        "snippet": "APPROVE",
    }
    assert WorkflowManager._extract_workflow_id(msg) == "gmail-thread-legacy"


