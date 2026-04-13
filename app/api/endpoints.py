import logging
from fastapi import APIRouter, HTTPException, Depends
from starlette.concurrency import run_in_threadpool

from app.dependencies import get_gmail, get_calendar, get_workflow_manager
from app.schemas.api import ApprovalPayload, WorkflowStatus
from app.services.calendar_service import CalendarService
from app.services.gmail_service import GmailService
from app.services.workflow_manager import WorkflowManager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", tags=["ops"])
async def health():
    """Basic health check"""
    return {"status": "ok"}


@router.get("/test-connection")
async def test_connection(
        gmail: GmailService = Depends(get_gmail),
        calendar: CalendarService = Depends(get_calendar),
):
    """
    Diagnostic check of services
    Verifies that Gmail and Calendar APIs are reachable and credentials are valid.
    """
    try:
        return {
            "status": "success",
            "data": {
                "gmail": await run_in_threadpool(gmail.test_connection),
                "calendar": await run_in_threadpool(calendar.test_connection),
            },
        }
    except Exception:
        logger.exception("Connection test failed")
        raise HTTPException(status_code=500, detail="Internal connection error")


@router.post("/process-emails")
async def process_emails(manager: WorkflowManager = Depends(get_workflow_manager)):
    """Optional way how to trigger processing emails without poll"""
    try:
        results = await manager.process_unread()
        return {"status": "triggered", "count": len(results), "results": results}
    except Exception:
        logger.exception("Manual process failed")
        raise HTTPException(status_code=500, detail="Manual processing failed")


@router.post("/approve")
async def approve(
        payload: ApprovalPayload,
        manager: WorkflowManager = Depends(get_workflow_manager),
):
    """Optional manual way to approve/reject a workflow from web.based on workflow id"""
    try:
        logger.info("API Approve: workflow=%s decision=%s", payload.workflow_id, payload.decision)
        result = await manager.resume_with_decision(payload.workflow_id, payload.decision)

        if result.get("status") == WorkflowStatus.ERROR:
            raise HTTPException(status_code=500, detail="Approval resume failed")

        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Approval resume failed")
        raise HTTPException(status_code=500, detail="Approval resume failed")
