from typing import Literal

from pydantic import BaseModel, field_validator


class ApprovalPayload(BaseModel):
    workflow_id: str
    decision: Literal["APPROVE", "REJECT"]

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: str) -> str:
        return str(value).strip().upper()


class ManagerReplyDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    workflow_id: str

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow_id(cls, value: str) -> str:
        workflow_id = str(value or "").strip()
        if not workflow_id:
            raise ValueError("workflow_id is required")
        if any(ch not in "0123456789abcdefABCDEF" for ch in workflow_id):
            raise ValueError("workflow_id must be hexadecimal")
        return workflow_id


