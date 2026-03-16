from abc import ABC, abstractmethod
from datetime import datetime


class BaseFetcher(ABC):
    """The strict blueprint for all Project Hestia fetchers."""

    @abstractmethod
    def __init__(self):
        # Fetchers must load their own credentials from os.getenv() here!
        pass

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def fetch_new_data(self, since_date: datetime, custom_filter: str) -> list:
        pass

    @abstractmethod
    def disconnect(self):
        pass
