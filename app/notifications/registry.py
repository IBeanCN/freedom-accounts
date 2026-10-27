"""Notification adapter registry."""
from .adapters.base import NotificationAdapter
from .adapters.dingtalk import DingTalkAdapter

_ADAPTERS: dict[str, type[NotificationAdapter]] = {
    DingTalkAdapter.key: DingTalkAdapter,
}


def get_adapter(key: str) -> type[NotificationAdapter]:
    try:
        return _ADAPTERS[key]
    except KeyError as exc:
        raise ValueError(f"不支持的通知渠道: {key}") from exc


def manifests() -> list[dict]:
    return [{"key": key, "label": adapter.label} for key, adapter in _ADAPTERS.items()]
