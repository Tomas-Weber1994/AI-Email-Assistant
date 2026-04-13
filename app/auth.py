"""Google OAuth2 authentication — returns an authorized httplib2 client."""

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from app.settings import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar"]


def get_authorized_http() -> AuthorizedHttp:
    http_client = httplib2.Http(timeout=30)

    if not settings.TOKEN_PATH.exists():
        raise RuntimeError(f"Token missing at {settings.TOKEN_PATH}. Run auth flow locally first.")

    creds = Credentials.from_authorized_user_file(str(settings.TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            settings.TOKEN_PATH.write_text(creds.to_json())
        else:
            raise RuntimeError("Credentials expired and no refresh token available.")

    return AuthorizedHttp(creds, http=http_client)
