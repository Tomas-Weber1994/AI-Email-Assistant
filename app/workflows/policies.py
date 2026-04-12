"""
Approval policies and output guards for the email workflow.

Centralises all policy logic so the graph router stays label-agnostic
and individual nodes remain focused on their primary responsibility.
"""
import logging
import uuid
from abc import ABC, abstractmethod

from langchain_core.messages import AIMessage

from app.schemas.classification import EmailLabel
from app.settings import settings
from app.workflows.state import EmailAgentState
from app.workflows.tools import ToolName

logger = logging.getLogger(__name__)

_SALES_OUTREACH_DECLINE = (
    "Hello,\n\n"
    "Thank you for your message. We are not interested at this time.\n\n"
    "Best regards,\n"
    "Manager (Automatic reply)"
)


class ApprovalPolicy(ABC):
    """Determines whether a proposed set of tool calls requires manager approval."""

    @abstractmethod
    def requires_approval(self, state: EmailAgentState, tool_calls: list[dict]) -> bool: ...


class StandardApprovalPolicy(ApprovalPolicy):
    """
    Default policy: gates sensitive tools behind approval.
    SALES_OUTREACH replies can bypass approval depending on configuration.
    """

    def __init__(self, sensitive_tools: list[str]):
        self._sensitive_tools = frozenset(sensitive_tools)

    def requires_approval(self, state: EmailAgentState, tool_calls: list[dict]) -> bool:
        sensitive = set(self._sensitive_tools)
        classification = state.get("classification")

        # SALES_OUTREACH replies may bypass approval depending on config.
        if (
            classification
            and classification.label == EmailLabel.SALES_OUTREACH
            and not settings.SALES_REPLY_REQUIRES_APPROVAL
        ):
            sensitive.discard(ToolName.SEND_REPLY.value)

        needs = any(tc["name"] in sensitive for tc in tool_calls)
        logger.debug(
            "Policy check — tools: %s, requires_approval: %s",
            [tc["name"] for tc in tool_calls],
            needs,
        )
        return needs


def apply_sales_outreach_guard(response: AIMessage, state: EmailAgentState) -> AIMessage:
    """
    Ensures SALES_OUTREACH emails always include send_reply + archive_and_label.
    Called after the LLM response in analyze_node as a deterministic safety net.
    Returns the original response unchanged for all other classifications.
    """
    classification = state.get("classification")
    if not classification or classification.label != EmailLabel.SALES_OUTREACH:
        return response

    current_calls = list(getattr(response, "tool_calls", []) or [])
    current_names = [tc.get("name") for tc in current_calls]

    if ToolName.SEND_REPLY.value not in current_names:
        current_calls.insert(0, {
            "name": ToolName.SEND_REPLY.value,
            "args": {"text": _SALES_OUTREACH_DECLINE},
            "id": f"sales_reply_{uuid.uuid4().hex[:8]}",
            "type": "tool_call",
        })

    if ToolName.ARCHIVE_AND_LABEL.value not in current_names:
        current_calls.append({
            "name": ToolName.ARCHIVE_AND_LABEL.value,
            "args": {
                "primary_label": EmailLabel.SALES_OUTREACH.value,
                "is_urgent": bool(classification.is_urgent),
            },
            "id": f"sales_archive_{uuid.uuid4().hex[:8]}",
            "type": "tool_call",
        })

    if len(current_calls) == len(getattr(response, "tool_calls", []) or []):
        return response  # No injection was needed.

    logger.debug("Sales outreach guard injected missing tool calls.")
    return AIMessage(content="Applying SALES_OUTREACH guard.", tool_calls=current_calls)

