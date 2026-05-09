"""FastAPI dependency factories — wires together auth + services."""
from typing import Optional
from fastapi import Request

from app.services.ports import EmailProvider, CalendarProvider
from app.services.workflow_manager import WorkflowManager


class ServiceRegistry:
    """Simple service registry for singleton caching of services."""
    _email: Optional[EmailProvider] = None
    _calendar: Optional[CalendarProvider] = None

    @classmethod
    def initialize(cls, email: EmailProvider, calendar: CalendarProvider) -> None:
        """Initialize service instances (called once in lifespan)."""
        cls._email = email
        cls._calendar = calendar

    @classmethod
    def get_email(cls) -> EmailProvider:
        """Get cached email provider."""
        if cls._email is None:
            raise RuntimeError("Services not initialized. Call initialize() in lifespan.")
        return cls._email

    @classmethod
    def get_calendar(cls) -> CalendarProvider:
        """Get cached calendar provider."""
        if cls._calendar is None:
            raise RuntimeError("Services not initialized. Call initialize() in lifespan.")
        return cls._calendar


# FastAPI Depends callables
def get_email() -> EmailProvider:
    return ServiceRegistry.get_email()


def get_calendar() -> CalendarProvider:
    return ServiceRegistry.get_calendar()


def get_workflow_manager(request: Request) -> WorkflowManager:
    manager = getattr(request.app.state, "workflow_manager", None)
    if manager is None:
        raise RuntimeError("WorkflowManager is not initialized.")
    return manager
