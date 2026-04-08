import os
import logging
from fastapi import FastAPI
from dotenv import load_dotenv
from app.auth import get_gmail_service, get_calendar_service

load_dotenv()

# Global config (Proxy & OAuth)
if os.getenv("PROXY_HOST") and os.getenv("PROXY_PORT"):
    proxy_url = f"http://{os.getenv('PROXY_HOST')}:{os.getenv('PROXY_PORT')}"
    os.environ.update({
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "NO_PROXY": "localhost,127.0.0.1"
    })
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

app = FastAPI(title="AI Email Agent API")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@app.get("/")
def read_root():
    return {"status": "online", "agent": "AiEmailAgent"}


@app.get("/test-connection")
def test_connection():
    """Endpoint to verify both Gmail and Calendar API connectivity."""
    results = {}
    try:
        # Check Gmail
        gmail_service = get_gmail_service()
        labels = gmail_service.users().labels().list(userId="me").execute()
        results["gmail"] = {"status": "ok", "labels_found": len(labels.get("labels", []))}

        # Check Calendar
        calendar_service = get_calendar_service()
        calendar_list = calendar_service.calendarList().list().execute()
        results["calendar"] = {"status": "ok", "calendars_found": len(calendar_list.get("items", []))}

        return {"status": "success", "data": results}
    except Exception as e:
        logging.error(f"Connection test failed: {e}")
        return {"status": "error", "detail": str(e)}
