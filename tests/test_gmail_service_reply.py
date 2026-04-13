from app.services.gmail_service import GmailService

def test_ensure_reply_text_keeps_approved_text_as_is():
    approved = "Hi\n\nI am unavailable at 12:00-13:00.\n\nManager (Automatic reply)"
    assert GmailService._ensure_reply_text(approved) == approved
