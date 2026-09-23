from .base import PhoneProviderAdapter
from .hero_sms import HeroSmsAdapter

PHONE_ADAPTERS: list[type[PhoneProviderAdapter]] = [HeroSmsAdapter]
PHONE_ADAPTER_MAP: dict[str, type[PhoneProviderAdapter]] = {
    adapter.key: adapter for adapter in PHONE_ADAPTERS
}


def get_phone_adapter(key: str) -> type[PhoneProviderAdapter]:
    adapter = PHONE_ADAPTER_MAP.get((key or "").strip())
    if adapter is None:
        raise ValueError(f"unsupported phone provider: {key!r}")
    return adapter
