"""Common notification adapter contract."""
from abc import ABC, abstractmethod


class NotificationAdapter(ABC):
    """Send one markdown notification through a configured channel."""

    key = ""
    label = ""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def send_markdown(self, title: str, text: str) -> None:
        """Send a markdown message or raise when the channel rejects it."""
