from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch

from app.services.workflow_manager import WorkflowManager


class TestWorkflowManagerResumeApproval(IsolatedAsyncioTestCase):
    async def test_resume_approval_returns_success_and_cleans_pending_label(self):
        email = Mock()
        email.has_label = Mock(return_value=True)
        email.modify_labels = Mock()
        calendar = Mock()
        llm = Mock()
        graph = Mock()
        graph.invoke = Mock(return_value={"status": "completed"})

        with patch("app.services.workflow_manager.create_email_graph", return_value=graph):
            manager = WorkflowManager(email=email, calendar=calendar, llm=llm, checkpointer=Mock())

        result = await manager.resume_approval("abc123", " approve ")

        self.assertEqual(result, {"status": "success", "decision": "APPROVE"})
        graph.invoke.assert_called_once()
        email.modify_labels.assert_called_once_with("abc123", None, ["PENDING_APPROVAL"])
        self.assertEqual([call[0] for call in graph.mock_calls], ["invoke"])

    async def test_resume_approval_returns_skipped_when_no_pending_label_exists(self):
        email = Mock()
        email.has_label = Mock(return_value=False)
        email.modify_labels = Mock()
        calendar = Mock()
        llm = Mock()
        graph = Mock()
        graph.invoke = Mock()

        with patch("app.services.workflow_manager.create_email_graph", return_value=graph):
            manager = WorkflowManager(email=email, calendar=calendar, llm=llm, checkpointer=Mock())

        result = await manager.resume_approval("abc123", "REJECT")

        self.assertEqual(result, {"status": "skipped", "reason": "No pending approval found."})
        graph.invoke.assert_not_called()
        email.modify_labels.assert_not_called()

    async def test_resume_approval_returns_error_when_graph_ends_in_error(self):
        email = Mock()
        email.has_label = Mock(return_value=True)
        email.modify_labels = Mock()
        calendar = Mock()
        llm = Mock()
        graph = Mock()
        graph.invoke = Mock(return_value={"status": "error"})

        with patch("app.services.workflow_manager.create_email_graph", return_value=graph):
            manager = WorkflowManager(email=email, calendar=calendar, llm=llm, checkpointer=Mock())

        result = await manager.resume_approval("abc123", "APPROVE")

        self.assertEqual(
            result,
            {
                "status": "error",
                "detail": "Workflow ended in error state after resume.",
                "graph_status": "error",
            },
        )
        graph.invoke.assert_called_once()
        email.modify_labels.assert_not_called()

    async def test_send_approval_reminder_uses_required_subject_tag(self):
        email = Mock()
        email.has_label = Mock(side_effect=[True, False])
        email.get_message = Mock(
            return_value={
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Quarterly planning"},
                    ]
                }
            }
        )
        email.send_message = Mock()
        email.modify_labels = Mock()
        calendar = Mock()
        llm = Mock()
        graph = Mock()

        with patch("app.services.workflow_manager.create_email_graph", return_value=graph):
            manager = WorkflowManager(email=email, calendar=calendar, llm=llm, checkpointer=Mock())

        result = await manager._send_approval_reminder("abc123")

        self.assertEqual(result, {"status": "success", "workflow_id": "abc123"})
        email.send_message.assert_called_once()
        _, subject, _ = email.send_message.call_args[0]
        self.assertTrue(subject.startswith("[APPROVAL REQUIRED]"))
        self.assertIn("[WF:abc123]", subject)
        email.modify_labels.assert_called_once_with("abc123", ["APPROVAL_REMINDER_SENT"], None)

