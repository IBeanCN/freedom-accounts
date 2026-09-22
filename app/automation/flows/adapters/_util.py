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
    return time.strftime("%H:%M:%S")
