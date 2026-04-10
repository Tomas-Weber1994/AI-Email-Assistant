# app/services/base.py
import logging
from typing import Any
from abc import ABC, abstractmethod
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

class GoogleService(ABC):
    def __init__(self, service_name: str, version: str, auth_http):
        self.logger = logging.getLogger(f"{self.__module__}.{self.__class__.__name__}")
        self.service: Any = build(
            service_name, version, http=auth_http, cache_discovery=False
        )

    def _call_google_api(self, request):
        """
        Calls a Google API request with standardized error handling.
        """
        try:
            return request.execute()
        except HttpError as e:
            self.logger.error(f"Google API Error: {e.content}")
            raise e
        except Exception as e:
            self.logger.error(f"Unexpected error during API call: {e}")
            raise e

    @abstractmethod
    def test_connection(self) -> dict:
        """Each service must implement its own connection test method."""
        pass
