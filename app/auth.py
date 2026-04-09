import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from app.settings import settings
from app.services.google import GmailService, CalendarService

SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar"]


def get_authorized_http() -> AuthorizedHttp:
    proxy_info = None
    if settings.proxy_url:
        proxy_info = httplib2.ProxyInfo(
            proxy_type=3,  # HTTP_PROXY
            proxy_host=settings.PROXY_HOST,
            proxy_port=settings.PROXY_PORT,
            proxy_rdns=True
        )

    http_client = httplib2.Http(proxy_info=proxy_info, timeout=30)

    if not settings.TOKEN_PATH.exists():
        raise RuntimeError(f"Token missing at {settings.TOKEN_PATH}. Run auth flow locally first.")

    creds = Credentials.from_authorized_user_file(str(settings.TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(settings.TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())
        else:
            raise RuntimeError("Credentials expired and no refresh token available.")

    return AuthorizedHttp(creds, http=http_client)


def get_gmail_provider() -> GmailService:
    return GmailService(get_authorized_http())


def get_calendar_provider() -> CalendarService:
    return CalendarService(get_authorized_http())
