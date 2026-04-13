from enum import Enum


class EmailLabel(str, Enum):
    MEETING_REQUEST = "MEETING_REQUEST"
    TASK = "TASK"
    INFO_ONLY = "INFO_ONLY"
    SALES_OUTREACH = "SALES_OUTREACH"
    MARKETING = "MARKETING"
    SPAM = "SPAM"


class GmailSystemLabel(str, Enum):
    URGENT = "URGENT"
    FINANCE = "Finance"
    PENDING_APPROVAL = "PENDING_APPROVAL"


class GmailReservedLabel(str, Enum):
    INBOX = "INBOX"
    UNREAD = "UNREAD"
    SPAM = "SPAM"


def required_gmail_labels() -> list[str]:
    return [lbl.value for lbl in EmailLabel] + [lbl.value for lbl in GmailSystemLabel]
