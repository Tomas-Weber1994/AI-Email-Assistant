"""FastAPI dependency factories — wires together auth + services."""

from fastapi import Request

from app.auth import get_authorized_http
from app.services.calendar_service import CalendarService
from app.services.gmail_service import GmailService
from app.services.workflow_manager import WorkflowManager


def get_gmail() -> GmailService:
    return GmailService(get_authorized_http())


def get_calendar() -> CalendarService:
    return CalendarService(get_authorized_http())


def get_workflow_manager(request: Request) -> WorkflowManager:
    manager = getattr(request.app.state, "workflow_manager", None)
    if manager is None:
        raise RuntimeError("WorkflowManager is not initialized.")
    return manager


