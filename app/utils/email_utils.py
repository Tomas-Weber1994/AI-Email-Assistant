"""Email parsing and formatting helpers."""

import base64

from app.schemas.classification import EmailClassification
from app.utils.time_utils import in_one_hour_iso


def get_headers(raw_msg: dict) -> dict:
    """Returns Gmail message headers as a plain dict."""
    return {h["name"]: h["value"] for h in raw_msg.get("payload", {}).get("headers", [])}


def get_body(raw_msg: dict) -> str:
    """Extracts plain-text body from Gmail message; handles both single-part and multipart."""
    payload = raw_msg.get("payload", {})

    # Single-part message: body is directly in payload.body.data
    body_data = payload.get("body", {}).get("data", "")
    if body_data and payload.get("mimeType", "").startswith("text/plain"):
        return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="ignore")

    # Multipart message: iterate parts
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

    return raw_msg.get("snippet", "")


def build_approval_email(headers: dict, cls: EmailClassification) -> str:
    """Builds the approval request email body sent to the manager."""
    lines = [
        "AI Agent — Approval Required",
        "",
        f"From:    {headers.get('From', 'unknown')}",
        f"Subject: {headers.get('Subject', '')}",
        f"Label:   {cls.primary_label.value}{' + URGENT' if cls.is_urgent else ''}",
        f"Action:  {cls.proposed_action.value}",
        f"Reason:  {cls.justification}",
    ]
    if cls.meeting_start:
        lines.append(f"Meeting: {cls.meeting_start} → {cls.meeting_end or in_one_hour_iso()}")
    if cls.suggested_reply:
        lines += ["", "Suggested reply:", cls.suggested_reply]
    lines += ["", "Reply APPROVE or REJECT to this email."]
    return "\n".join(lines)
