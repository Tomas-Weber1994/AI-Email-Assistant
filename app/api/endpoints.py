import logging
from fastapi import APIRouter, HTTPException, Depends
from starlette.concurrency import run_in_threadpool
from app.auth import get_gmail_provider, get_calendar_provider
from app.services.google import GmailService, CalendarService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test-connection")
async def test_connection(
        gmail: GmailService = Depends(get_gmail_provider),
        calendar: CalendarService = Depends(get_calendar_provider)
):
    logger.info("Starting connection test for all Google services.")
    try:
        gmail_results = await run_in_threadpool(gmail.test_connection)
        calendar_results = await run_in_threadpool(calendar.test_connection)

        logger.info("Connection test completed successfully.")
        return {
            "status": "success",
            "data": {"gmail": gmail_results, "calendar": calendar_results}
        }
    except Exception:
        logger.exception("Unexpected error during connection test")
        raise HTTPException(status_code=500, detail="Internal connection error")
