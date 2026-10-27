"""Notification dispatch and login-event message formatting."""
import logging

from ..core import crypto, settings
from .registry import get_adapter

_log = logging.getLogger("notifications")


async def _build_adapter(channel: str, webhook: str | None = None,
                         secret: str | None = None):
    channel = (channel or "").strip()
    if not channel:
        raise ValueError("通知渠道未配置")
    adapter_cls = get_adapter(channel)
    saved_webhook = await settings.get("notification_dingtalk_webhook") or ""
    saved_secret = await settings.get("notification_dingtalk_secret") or ""
    return adapter_cls({
        "webhook": crypto.decrypt(webhook.strip() if webhook and webhook.strip() else saved_webhook),
        "secret": crypto.decrypt(secret.strip() if secret and secret.strip() else saved_secret),
    })


async def _send(title: str, text: str) -> bool:
    channel = (await settings.get("notification_channel") or "").strip()
    if not channel:
        return False
    try:
        adapter = await _build_adapter(channel)
        await adapter.send_markdown(title, text)
        return True
    except Exception as exc:
        # Notification failures must never make a login task fail or block the scheduler.
        _log.warning("notification send failed channel=%s: %s", channel, exc)
        return False


async def send_test_notification(channel: str, webhook: str = "", secret: str = "") -> None:
    """Send a test message, using unsaved form values when supplied."""
    adapter = await _build_adapter(channel, webhook, secret)
    await adapter.send_markdown(
        "Freedom Accounts 通知测试",
        "### 通知测试\n\n通知配置测试成功。",
    )


async def notify_account_data_refresh(usernames: list[str]) -> bool:
    """Notify once per refresh round when automatic login accounts were queued."""
    names = [str(name or "").strip() for name in usernames if str(name or "").strip()]
    if not names:
        return False
    lines = "\n".join(f"- {name}" for name in names)
    return await _send(
        "账号数据自动刷新",
        f"### 账号数据自动刷新\n\n以下账号需要重新上号，已加入任务队列：\n{lines}",
    )


async def notify_account_login_started(username: str) -> bool:
    username = str(username or "").strip() or "未知账号"
    return await _send(
        "账号上号中",
        f"### 账号上号中\n\n账号：`{username}`",
    )


async def notify_account_login_finished(
    username: str, status: str, *, error: str = "", last_url: str = ""
) -> bool:
    username = str(username or "").strip() or "未知账号"
    success = status == "success"
    label = "成功" if success else "失败"
    lines = [f"### 账号上号{label}", "", f"账号：`{username}`"]
    if not success and last_url:
        lines.extend([f"最后停留页面：{last_url}"])
    if not success and error:
        lines.extend([f"失败原因：{str(error)[:500]}"])
    return await _send("账号上号" + label, "\n".join(lines))
