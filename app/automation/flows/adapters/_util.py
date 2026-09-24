"""FlowAdapter base class & shared TOTP/time helpers."""
import time

import pyotp


def totp_code(secret: str) -> str | None:
    """Current TOTP code, or None when no/invalid secret."""
    secret = (secret or "").strip()
    if not secret:
        return None
    try:
        return pyotp.TOTP(secret.replace(" ", "")).now()
    except Exception:
        return None


def now() -> str:
    # Keep adapter step timestamps in the same format as scheduler task fields.
    return time.strftime("%Y-%m-%d %H:%M:%S")


# 上游账号状态 -> 中文（sub2api 与 cpr 共用同一套语义）
REMOTE_STATUS_MAP = {
    "normal": "正常",
    "quota_exhausted": "配额耗尽",
    "rate_limited": "限流中",
    "disabled": "已停用",
    "error": "错误",
    "refresh_backoff": "退避中",
}


def translate_remote_status(raw) -> str:
    """上游状态枚举转中文；未知值原样返回，空值返回空串。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    return REMOTE_STATUS_MAP.get(s, s)
