from enum import Enum

from pydantic import BaseModel, field_validator


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class WorkflowStatus(str, Enum):
    PROCESSING = "processing"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    ERROR = "error"


class ApprovalPayload(BaseModel):
    workflow_id: str
    decision: ApprovalDecision

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: str) -> str:
        return str(value).strip().upper()

