"""Adapter contract shared by every phone-number platform."""
import asyncio
from collections import deque
from dataclasses import dataclass
import hashlib
import time

from .countries import COUNTRY_BY_ISO2

REQUEST_RATE_LIMIT = 50
REQUEST_RATE_WINDOW_SECONDS = 1.0

# Provider accounts are commonly shared by multiple adapter instances and task
# coroutines, so reserve slots globally per adapter + API key, not per object.
_REQUEST_SLOTS: dict[tuple[str, str], deque[float]] = {}


def _request_bucket(adapter_key: str, api_key: str) -> tuple[str, str]:
    """Keep the API key out of shared-state representations by hashing it."""
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return adapter_key, digest


class PhoneProviderNoNumbers(RuntimeError):
    """Provider returned no inventory; callers must stop instead of manual fallback."""


@dataclass(frozen=True)
class PhoneOrder:
    """Normalized provider order; ``provider_order_id`` is platform-specific."""
    phone: str
    provider_order_id: str


@dataclass(frozen=True)
class PhoneCountry:
    """A provider-supported country; code is the value passed to get_number."""
    code: str
    name: str = ""


class PhoneProviderAdapter:
    """A phone platform implements the operations used by the gate."""

    key: str = ""
    label: str = ""

    async def _acquire_request_slot(self, api_key: str) -> None:
        """Acquire one slot in the shared sliding-window provider rate limit."""
        bucket = _request_bucket(self.key, api_key)
        slots = _REQUEST_SLOTS.setdefault(bucket, deque())
        while True:
            now = time.monotonic()
            while slots and slots[0] <= now - REQUEST_RATE_WINDOW_SECONDS:
                slots.popleft()
            if len(slots) < REQUEST_RATE_LIMIT:
                slots.append(now)
                return
            await asyncio.sleep(
                max(0.0, slots[0] + REQUEST_RATE_WINDOW_SECONDS - now))

    async def get_countries(self, api_key: str) -> list[PhoneCountry]:
        """Fallback to ISO countries until a provider-specific API is implemented."""
        del api_key
        return [
            PhoneCountry(code=iso2, name=info["zh"] or info["en"])
            for iso2, info in COUNTRY_BY_ISO2.items()
        ]

    async def get_balance(self, api_key: str) -> str:
        """Return a human-readable remaining balance, e.g. ``12.30 USD``."""
        raise NotImplementedError

    async def get_number(self, api_key: str, country: str,
                         page_country: str = "") -> PhoneOrder:
        """Reserve a number for OpenAI in the provider's country identifier."""
        raise NotImplementedError

    async def get_code(self, api_key: str, order: PhoneOrder) -> str:
        """Return the SMS code, or an empty string while it is still pending."""
        raise NotImplementedError

    async def confirm_received(self, api_key: str, order: PhoneOrder) -> None:
        """Acknowledge a received SMS so the provider can finalize the order."""
        raise NotImplementedError

    async def cancel_order(self, api_key: str, order: PhoneOrder) -> None:
        """Cancel an activation when the SMS code does not arrive in time."""
        raise NotImplementedError
