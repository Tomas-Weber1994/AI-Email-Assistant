import asyncio
from unittest.mock import MagicMock

from app.schemas.api import ApprovalDecision, WorkflowStatus
from app.services.workflow_manager import WorkflowManager


class _Manager(WorkflowManager):
    def __init__(self, email, graph=None):
        super().__init__(
            email=email,
            calendar=MagicMock(),
            llm=MagicMock(),
            checkpointer=None,
        )
        if graph is not None:
            self.graph = graph


def test_pending_skips_and_keeps_unread():
    email = MagicMock()
    email.list_unread.return_value = [{"id": "m1", "threadId": "t1"}]
    email.has_label.return_value = True

    manager = _Manager(email)

    async def should_not_be_called(*_):
        raise AssertionError("Pending email should not be processed")

    manager._process_new_email = should_not_be_called
    result = asyncio.run(manager.process_unread())
    assert result == []
    email.modify_labels.assert_not_called()


def test_success_removes_unread():
    email = MagicMock()
    email.list_unread.return_value = [{"id": "m1", "threadId": "t1"}]
    email.has_label.return_value = False

    manager = _Manager(email)

    async def fake_process(email_id: str, thread_id: str):
        return {"status": WorkflowStatus.COMPLETED, "email_id": email_id, "thread_id": thread_id}

    manager._process_new_email = fake_process
    result = asyncio.run(manager.process_unread())
    assert result == [{"status": WorkflowStatus.COMPLETED, "email_id": "m1", "thread_id": "t1"}]
    email.modify_labels.assert_called_once_with("m1", remove=["UNREAD"])


def test_error_keeps_unread():
    email = MagicMock()
    email.list_unread.return_value = [{"id": "m2", "threadId": "t2"}]
    email.has_label.return_value = False

    manager = _Manager(email)

    async def fake_process(email_id: str, thread_id: str):
        return {"status": WorkflowStatus.ERROR, "email_id": email_id, "thread_id": thread_id}

    manager._process_new_email = fake_process
    result = asyncio.run(manager.process_unread())
    assert result == [{"status": WorkflowStatus.ERROR, "email_id": "m2", "thread_id": "t2"}]
    email.modify_labels.assert_not_called()


def test_approve_resumes_workflow_and_clears_pending():
    email = MagicMock()
    graph = MagicMock()

    snapshot = MagicMock()
    snapshot.values = {"email_id": "m1"}
    graph.get_state.return_value = snapshot
    graph.invoke.return_value = {"status": WorkflowStatus.COMPLETED}

    manager = _Manager(email, graph=graph)
    result = asyncio.run(manager.resume_with_decision("thread-1", ApprovalDecision.APPROVE))
    config = graph.get_state.call_args.args[0]
    state_update = graph.update_state.call_args.args[1]
    assert result == {"status": WorkflowStatus.COMPLETED}
    assert state_update["manager_decision"] == ApprovalDecision.APPROVE
    assert state_update["messages"][0].content == ApprovalDecision.APPROVE.value
    graph.invoke.assert_called_once_with(None, config)
    email.modify_labels.assert_called_once_with("m1", remove=["PENDING_APPROVAL"])
