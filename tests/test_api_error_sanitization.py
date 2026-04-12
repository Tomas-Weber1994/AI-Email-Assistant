from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from app.api.endpoints import approve, process_emails
from app.schemas.api import ApprovalPayload


class TestApiErrorSanitization(IsolatedAsyncioTestCase):
    async def test_process_emails_masks_internal_exception_details(self):
        manager = Mock()
        manager.process_unread = AsyncMock(side_effect=Exception("provider timeout secret"))

        with self.assertRaises(HTTPException) as ctx:
            await process_emails(manager=manager)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.detail, "Manual processing failed")

    async def test_approve_masks_internal_manager_error_payload_details(self):
        manager = Mock()
        manager.resume_approval = AsyncMock(return_value={"status": "error", "detail": "internal stack"})
        payload = ApprovalPayload(workflow_id="abc123", decision="APPROVE")

        with self.assertRaises(HTTPException) as ctx:
            await approve(payload=payload, manager=manager)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.detail, "Approval resume failed")

    async def test_approve_masks_internal_exception_details(self):
        manager = Mock()
        manager.resume_approval = AsyncMock(side_effect=Exception("sensitive internals"))
        payload = ApprovalPayload(workflow_id="abc123", decision="REJECT")

        with self.assertRaises(HTTPException) as ctx:
            await approve(payload=payload, manager=manager)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.detail, "Approval resume failed")

