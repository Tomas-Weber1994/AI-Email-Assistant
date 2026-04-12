"""Email parsing and formatting helpers."""

import base64


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

