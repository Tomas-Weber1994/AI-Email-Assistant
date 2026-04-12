# app/services/base.py
import logging
from abc import ABC, abstractmethod
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GoogleService(ABC):
    def __init__(self, service_name: str, version: str, auth_http):
        self.logger = logging.getLogger(f"{self.__module__}.{self.__class__.__name__}")
        self.service: Any = build(
            service_name, version, http=auth_http, cache_discovery=False
        )

    def _call_google_api(self, request):
        """Execute a Google API request with standardized error logging."""
        try:
            return request.execute()
        except HttpError as e:
            self.logger.error("Google API error status=%s: %s", e.resp.status, e.content)
            raise
        except Exception as e:
            self.logger.error("Unexpected error during API call: %s", e)
            raise

    @abstractmethod
    def test_connection(self) -> dict:
        raise NotImplementedError
