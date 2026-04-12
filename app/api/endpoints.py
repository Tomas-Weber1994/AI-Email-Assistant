import logging
from fastapi import APIRouter, HTTPException, Depends
from starlette.concurrency import run_in_threadpool

from app.dependencies import get_gmail, get_calendar, get_workflow_manager
from app.schemas.api import ApprovalPayload
from app.services.calendar_service import CalendarService
from app.services.gmail_service import GmailService
from app.services.workflow_manager import WorkflowManager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test-connection")
async def test_connection(
        gmail: GmailService = Depends(get_gmail),
        calendar: CalendarService = Depends(get_calendar),
):
    """Diagnostický endpoint pro ověření spojení s Google API."""
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
    """Manuální trigger pro okamžité prohledání inboxu."""
    try:
        results = await manager.process_unread()
        return {"status": "triggered", "count": len(results)}
    except Exception:
        logger.exception("Manual process failed")
        raise HTTPException(status_code=500, detail="Manual processing failed")


@router.post("/approve")
async def approve(
        payload: ApprovalPayload,
        manager: WorkflowManager = Depends(get_workflow_manager)
):
    """
    Endpoint pro schválení/zamítnutí akce (např. z UI nebo webhooku).
    Využívá mechanismus Command(resume=...) k probuzení grafu.
    """
    try:
        logger.info(f"API Approve: workflow={payload.workflow_id} decision={payload.decision}")

        # Předpokládáme, že payload.workflow_id odpovídá email_id (thread_id v LangGraphu)
        result = await manager.resume_approval(payload.workflow_id, payload.decision.upper())

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail="Approval resume failed")

        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Approval resume failed")
        raise HTTPException(status_code=500, detail="Approval resume failed")
