import os
import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.endpoints import router
from app.auth import get_authorized_http
from app.database import db  # noqa: F401 — initialises DB on import
from app.services.agent_runner import AgentRunner
from app.services.approval import ApprovalService
from app.services.google import GmailService, CalendarService
from app.settings import settings
from app.utils.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("app.main")


async def _poll_loop(gmail: GmailService, calendar: CalendarService):
    """Background loop that monitors the inbox and checks approvals periodically."""
    await asyncio.sleep(5)
    while True:
        try:
            runner = AgentRunner(gmail, calendar)
            results = await runner.process_unread()
            if results:
                logger.info(f"Poll: processed {len(results)} email(s).")

            resolved = await ApprovalService(gmail).process_pending()
            if resolved:
                logger.info(f"Poll: resolved {len(resolved)} approval(s).")

        except Exception:
            logger.exception("Poll cycle failed — will retry next interval.")

        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.proxy_url:
        os.environ["HTTP_PROXY"] = settings.proxy_url
        os.environ["HTTPS_PROXY"] = settings.proxy_url
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    logger.info("Starting AI Email Agent")
    logger.info("Database: %s", settings.DB_PATH)
    logger.info("Poll interval: %ds", settings.POLL_INTERVAL_SECONDS)

    auth = get_authorized_http()
    gmail = GmailService(auth)
    calendar = CalendarService(auth)

    try:
        gmail.ensure_labels([
            "MEETING_REQUEST", "TASK", "INFO_ONLY",
            "SALES_OUTREACH", "MARKETING", "URGENT", "Finance"
        ])
        logger.info("Gmail labels synced.")
    except Exception as e:
        logger.warning("Could not sync Gmail labels: %s", e)

    poll_task = asyncio.create_task(_poll_loop(gmail, calendar))
    logger.info("Background inbox monitor started.")

    yield

    poll_task.cancel()
    db.close()
    logger.info("Database connection closed.")
    logger.info("Shutting down AI Email Agent")

app = FastAPI(
    title="AI Email Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=False,
        access_log=True,
    )
