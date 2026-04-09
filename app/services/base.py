import logging
from abc import ABC, abstractmethod

class GoogleService(ABC):
    def __init__(self):
        self.logger = logging.getLogger(f"{self.__module__}.{self.__class__.__name__}")

    @abstractmethod
    def test_connection(self) -> dict:
        pass
