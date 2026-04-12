from app.services.workflow_manager import WorkflowManager


def test_extract_decision_and_workflow_id_from_subject():
    decision, workflow_id = WorkflowManager._extract_decision_and_workflow_id(
        "APPROVE\nLooks good.",
        "Re: [APPROVAL REQUIRED] [WF:a1b2c3d4] Quarterly planning",
    )

    assert decision == "APPROVE"
    assert workflow_id == "a1b2c3d4"


def test_extract_decision_and_workflow_id_from_subject_fallback():
    decision, workflow_id = WorkflowManager._extract_decision_and_workflow_id(
        "Please proceed when ready.",
        "Re: Approval needed [WF:deadbeef]",
    )

    assert decision is None
    assert workflow_id == "deadbeef"


def test_extract_decision_handles_token_with_trailing_punctuation():
    decision, workflow_id = WorkflowManager._extract_decision_and_workflow_id(
        "Approve.",
        "Re: [APPROVAL REQUIRED] [WF:aabbccdd] Quarterly planning",
    )

    assert decision == "APPROVE"
    assert workflow_id == "aabbccdd"


def test_extract_decision_does_not_accept_free_text_phrase():
    decision, workflow_id = WorkflowManager._extract_decision_and_workflow_id(
        "I reject this request for now.",
        "Re: [APPROVAL REQUIRED] [WF:1234abcd] Quarterly planning",
    )

    assert decision is None
    assert workflow_id == "1234abcd"


def test_extract_workflow_id_does_not_fallback_to_body_anymore():
    decision, workflow_id = WorkflowManager._extract_decision_and_workflow_id(
        "APPROVE\nWORKFLOW ID: cafebabe"
    )

    assert decision == "APPROVE"
    assert workflow_id is None


