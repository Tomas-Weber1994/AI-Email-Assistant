from typing import Annotated, TypedDict, Optional, List
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, Field
from app.schemas.classification import EmailLabel
from app.schemas.api import ApprovalDecision, WorkflowStatus


def merge_messages(existing: List[BaseMessage], new: List[BaseMessage]) -> List[BaseMessage]:
    """Append conversation history, but reset on a fresh ingest HumanMessage."""
    current = list(existing or [])
    incoming = list(new or [])

    if not incoming:
        return current

    first_msg = incoming[0]
    if isinstance(first_msg, HumanMessage) and isinstance(first_msg.content, str) and first_msg.content.startswith("From: "):
        return incoming

    return current + incoming


def merge_audit_log(existing: List[str], new: List[str]) -> List[str]:
    """Append audit trail, but reset on a fresh workflow START entry."""
    current = list(existing or [])
    incoming = list(new or [])

    if not incoming:
        return current

    if incoming[0].startswith("START:"):
        return incoming

    return current + incoming

class EmailClassification(BaseModel):
    label: EmailLabel
    is_urgent: bool = Field(default=False)


class EmailAgentState(TypedDict):
    email_id: str
    messages: Annotated[List[BaseMessage], merge_messages]
    raw_content: dict
    classification: Optional[EmailClassification]
    analyze_passes: int
    terminal_action_done: bool
    manager_decision: Optional[ApprovalDecision]
    pending_approval_tool_calls: Optional[List[dict]]
    status: WorkflowStatus
    audit_log: Annotated[List[str], merge_audit_log]
