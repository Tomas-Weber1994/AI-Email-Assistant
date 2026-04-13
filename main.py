import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.api.endpoints import router
from app.auth import get_authorized_http
from app.schemas.classification import required_gmail_labels
from app.services.calendar_service import CalendarService
from app.services.gmail_service import GmailService
from app.services.workflow_manager import WorkflowManager
from app.settings import settings
from app.utils.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("app.main")


async def _poll_loop(manager: WorkflowManager):
    await asyncio.sleep(5)
    while True:
        try:
            # Spouštíme v try-except bloku uvnitř while, aby loop nikdy nezemřel
            logger.debug("Starting poll interval...")
            await manager.process_pending_approvals()
            await manager.process_unread()
        except asyncio.CancelledError:
            # Důležité pro korektní vypnutí při yield v lifespanu
            break
        except Exception as e:
            # Detailní logování chyby, aby bylo jasné, PROČ se to zastavilo
            logger.error(f"CRITICAL POLL ERROR: {str(e)}", exc_info=True)

        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("Starting AI Email Agent")

    # Init Checkpointer for workflow state persistence.
    db_path = settings.CHECKPOINT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("app.workflows.state", "EmailClassification"),
            ("app.schemas.classification", "EmailLabel"),
            ("app.schemas.api", "WorkflowStatus"),
            ("app.schemas.api", "ApprovalDecision"),
        ]
    )
    checkpointer = SqliteSaver(conn, serde=serde)

    # Init services
    auth = get_authorized_http()
    gmail = GmailService(auth)
    calendar = CalendarService(auth)

    # Init Manager with Checkpointer
    manager = WorkflowManager(
        email=gmail,
        calendar=calendar,
        llm=ChatOpenAI(model=settings.MODEL_NAME, api_key=settings.OPENAI_API_KEY),
        checkpointer=checkpointer
    )
    app.state.workflow_manager = manager

    try:
        gmail.ensure_labels(required_gmail_labels())
    except Exception as e:
        logger.warning("Could not sync Gmail labels: %s", e)

    poll_task = asyncio.create_task(_poll_loop(manager))
    yield
    poll_task.cancel()
    conn.close()
    logger.info("Shutting down AI Email Agent")


app = FastAPI(title="AI Email Agent API", lifespan=lifespan)
app.include_router(router, prefix="/api/v1")

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=False)