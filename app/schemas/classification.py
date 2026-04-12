from enum import Enum

class EmailLabel(str, Enum):
    MEETING_REQUEST = "MEETING_REQUEST"
    TASK = "TASK"
    INFO_ONLY = "INFO_ONLY"
    SALES_OUTREACH = "SALES_OUTREACH"
    MARKETING = "MARKETING"
    SPAM = "SPAM"

def required_gmail_labels() -> list[str]:
    return [l.value for l in EmailLabel] + ["URGENT", "Finance", "PENDING_APPROVAL", "APPROVAL_REMINDER_SENT"]
