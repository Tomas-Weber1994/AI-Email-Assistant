from app.services.gmail_service import GmailService


def test_extract_reply_recipient_prefers_reply_to_email_only():
    headers = {
        "Reply-To": 'Paul Sender <paul@example.com>',
        "From": 'Tomas <tomas@example.com>',
    }
    assert GmailService._extract_reply_recipient(headers) == "paul@example.com"


def test_ensure_reply_text_keeps_approved_text_as_is():
    approved = "Hi\n\nI am unavailable at 12:00-13:00.\n\nManager (Automatic reply)"
    assert GmailService._ensure_reply_text(approved) == approved


def test_ensure_reply_text_uses_fallback_for_empty_input():
    assert GmailService._ensure_reply_text("   ") == "Thank you for your message."


