import logging
import ssl
import socket
import time
from abc import ABC, abstractmethod
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


_RETRYABLE = (ssl.SSLError, socket.timeout, TimeoutError, ConnectionError)

_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.5


class GoogleService(ABC):
    def __init__(self, service_name: str, version: str, auth_http):
        self.logger = logging.getLogger(f"{self.__module__}.{self.__class__.__name__}")
        self.service: Any = build(
            service_name, version, http=auth_http, cache_discovery=False
        )

    def _call_google_api(self, request):
        """
        Execute a Google API request with standardized error logging.
        Try again up to _MAX_RETRIES times.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return request.execute()
            except HttpError as e:
                self.logger.error("Google API error status=%s: %s", e.resp.status, e.content)
                raise
            except _RETRYABLE as e:
                last_exc = e
                if attempt < _MAX_RETRIES - 1:
                    delay = _BACKOFF_BASE_S * (2 ** attempt)
                    self.logger.warning(
                        "Transient network error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, _MAX_RETRIES, delay, e,
                    )
                    time.sleep(delay)
            except Exception as e:
                self.logger.error("Unexpected error during API call: %s", e)
                raise

        self.logger.error(
            "Google API call failed after %d attempts: %s", _MAX_RETRIES, last_exc
        )
        raise last_exc  # type: ignore[misc]

    @abstractmethod
    def test_connection(self) -> dict: ...
