import os
import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "credentials")

TOKEN_PATH = os.path.join(CREDENTIALS_DIR, "token.json")
CREDENTIALS_PATH = os.path.join(CREDENTIALS_DIR, "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar"
]

def _get_authenticated_http():
    """Helper to handle proxy and credentials for any Google service."""
    proxy_host = os.getenv("PROXY_HOST")
    proxy_port = os.getenv("PROXY_PORT")

    if proxy_host and proxy_port:
        proxy_info = httplib2.ProxyInfo(
            proxy_type=3,
            proxy_host=proxy_host,
            proxy_port=int(proxy_port),
            proxy_rdns=True
        )
        http_client = httplib2.Http(proxy_info=proxy_info, timeout=30)
    else:
        http_client = httplib2.Http(timeout=30)

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return AuthorizedHttp(creds, http=http_client)

def get_gmail_service():
    auth_http = _get_authenticated_http()
    return build("gmail", "v1", http=auth_http, cache_discovery=False)

def get_calendar_service():
    auth_http = _get_authenticated_http()
    return build("calendar", "v3", http=auth_http, cache_discovery=False)