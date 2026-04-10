from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator

class EmailLabel(str, Enum):
    MEETING_REQUEST = "MEETING_REQUEST"
    TASK = "TASK"
    INFO_ONLY = "INFO_ONLY"
    SALES_OUTREACH = "SALES_OUTREACH"
    MARKETING = "MARKETING"
    SPAM = "SPAM"

class AgentAction(str, Enum):
    ARCHIVE = "archive"
    CREATE_EVENT = "create_event"
    SEND_REPLY = "send_reply"
    FLAG_NOTIFY = "flag_notify"
    LOG_SPAM = "log_spam"
    NONE = "none"

class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class EmailClassification(BaseModel):
    """Straightforward output from LLM with logic validation."""
    primary_label: EmailLabel
    is_urgent: bool = False
    justification: str
    proposed_action: AgentAction
    requires_approval: bool = False
    suggested_reply: Optional[str] = None
    meeting_start: Optional[str] = Field(None, description="ISO 8601 datetime, e.g. 2026-04-15T14:00:00Z")
    meeting_end: Optional[str] = Field(None, description="ISO 8601 datetime, e.g. 2026-04-15T15:00:00Z")

    @model_validator(mode="after")
    def validate_urgent_spam(self) -> "EmailClassification":
        if self.primary_label == EmailLabel.SPAM and self.is_urgent:
            self.is_urgent = False
        return self

class EmailRecord(BaseModel):
    """The internal state we keep in DB / LangGraph."""
    email_id: str
    thread_id: str = ""
    classification: Optional[EmailClassification] = None
    status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED
    approval_thread_id: Optional[str] = None
    audit_trail: List[str] = Field(default_factory=list)

    def to_response(self) -> "AgentResponse":
        """Converts the internal record to a structured API response."""
        cls = self.classification
        return AgentResponse(
            email_id=self.email_id,
            thread_id=self.thread_id,
            label=f"{cls.primary_label.value}{' + URGENT' if cls.is_urgent else ''}" if cls else "unclassified",
            action=cls.proposed_action if cls else AgentAction.NONE,
            status=self.status,
            audit_trail=self.audit_trail,
        )


class AgentResponse(BaseModel):
    """Structured log entry returned by the API for every processed email."""
    email_id: str
    thread_id: str
    label: str
    action: AgentAction
    status: ApprovalStatus
    audit_trail: List[str]


