"""DingTalk custom robot notification adapter."""
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .base import NotificationAdapter


class DingTalkAdapter(NotificationAdapter):
    key = "dingtalk"
    label = "钉钉"
    TIMEOUT_SECONDS = 10

    @staticmethod
    def _signed_url(webhook: str, secret: str) -> str:
        """Append DingTalk's timestamp/signature without losing the copied token."""
        if not webhook.strip():
            raise ValueError("钉钉 Webhook 地址不能为空")
        if not secret.strip():
            raise ValueError("钉钉机器人密钥不能为空")
        parts = urlsplit(webhook.strip())
        if not parts.scheme or not parts.netloc:
            raise ValueError("钉钉 Webhook 地址格式不正确")
        timestamp = str(int(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
        ).digest()
        sign = quote(base64.b64encode(digest).decode("utf-8"), safe="")
        query = parts.query
        separator = "&" if query else ""
        query = f"{query}{separator}timestamp={timestamp}&sign={sign}"
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    async def send_markdown(self, title: str, text: str) -> None:
        webhook = self.config.get("webhook", "")
        secret = self.config.get("secret", "")
        url = self._signed_url(webhook, secret)
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        }
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS, trust_env=False) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                try:
                    result = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    raise RuntimeError("钉钉通知返回了无法解析的响应") from exc
        except httpx.HTTPError as exc:
            # Do not expose the signed webhook URL (which contains credentials).
            raise RuntimeError("钉钉通知请求失败") from exc
        if result.get("errcode") not in (0, "0"):
            message = result.get("errmsg") or "未知错误"
            raise RuntimeError(f"钉钉通知失败: {message}")
