import logging
from abc import ABC, abstractmethod
from langchain_core.messages import AIMessage
from app.schemas.classification import EmailLabel
from app.settings import settings
from app.workflows.state import EmailAgentState
from app.workflows.tools import ToolName
from app.workflows.nodes import APPROVED_REPLAY_MESSAGE

logger = logging.getLogger(__name__)


class ApprovalPolicy(ABC):
    @abstractmethod
    def requires_approval(self, state: EmailAgentState, tool_calls: list[dict]) -> bool:
        ...


class StandardApprovalPolicy(ApprovalPolicy):
    def __init__(self, sensitive_tools: list[str]):
        self._sensitive_tools = frozenset(sensitive_tools)

    def requires_approval(self, state: EmailAgentState, tool_calls: list[dict]) -> bool:
        # Skip re-approval when replaying manager-approved actions.
        # manager_decision is already None by now, so we check message content.
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and APPROVED_REPLAY_MESSAGE in str(last_msg.content):
            return False

        sensitive = set(self._sensitive_tools)
        classification = state.get("classification")

        # Configurable Sales Outreach send reply exemption
        if (
            classification
            and classification.label == EmailLabel.SALES_OUTREACH
            and not settings.SALES_REPLY_REQUIRES_APPROVAL
        ):
            sensitive.discard(ToolName.SEND_REPLY.value)

        requires_approval = any(tc["name"] in sensitive for tc in tool_calls)
        logger.debug("Policy check — tools: %s, requires_approval: %s",
                     [tc["name"] for tc in tool_calls], requires_approval)
        return requires_approval
