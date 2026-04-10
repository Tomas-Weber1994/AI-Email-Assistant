import logging
from fastapi import APIRouter, HTTPException, Depends
from starlette.concurrency import run_in_threadpool

from app.dependencies import get_gmail, get_calendar, get_agent_runner, get_approval_service
from app.services.agent_runner import AgentRunner
from app.services.approval import ApprovalService
from app.services.google import GmailService, CalendarService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test-connection")
async def test_connection(
        gmail: GmailService = Depends(get_gmail),
        calendar: CalendarService = Depends(get_calendar),
):
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
async def process_emails(runner: AgentRunner = Depends(get_agent_runner)):
    try:
        results = await runner.process_unread()
        return {"processed_count": len(results), "results": results}
    except Exception as e:
        logger.exception("Agent execution failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-approvals")
async def check_approvals(approval_service: ApprovalService = Depends(get_approval_service)):
    resolved = await approval_service.process_pending()
    return {"resolved": resolved}
