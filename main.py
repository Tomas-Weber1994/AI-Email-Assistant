import os
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.endpoints import router
from app.settings import settings
from app.utils.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.proxy_url:
        os.environ["HTTP_PROXY"] = settings.proxy_url
        os.environ["HTTPS_PROXY"] = settings.proxy_url
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"

    logger.info("Starting AI Email Agent")
    yield
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
        reload=True,
        access_log=True,
    )
