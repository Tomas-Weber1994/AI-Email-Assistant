"""FastAPI dependency factories — wires together auth + services."""

from app.auth import get_authorized_http
from app.services.agent_runner import AgentRunner
from app.services.approval import ApprovalService
from app.services.google import GmailService, CalendarService


def get_gmail() -> GmailService:
    return GmailService(get_authorized_http())


def get_calendar() -> CalendarService:
    return CalendarService(get_authorized_http())


def get_agent_runner() -> AgentRunner:
    auth = get_authorized_http()
    return AgentRunner(GmailService(auth), CalendarService(auth))


def get_approval_service() -> ApprovalService:
    return ApprovalService(GmailService(get_authorized_http()))


