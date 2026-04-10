from typing import Optional, TypedDict
from app.schemas.classification import EmailRecord

class AgentState(TypedDict):
    """
    Workflow state for the LangGraph email agent.
    - record: Domain model (EmailRecord) for DB persistence and classification.
    - raw_email: Original Gmail API response payload.
    - is_retry: Flag indicating if we are resuming a previously classified email.
    - error: Error message for routing and debugging.
    """
    record: EmailRecord
    raw_email: dict
    is_retry: bool
    error: Optional[str]
