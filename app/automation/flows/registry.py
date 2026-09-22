"""Flow adapter registration. Add a new login type in three steps:

1. create `adapters/<key>.py` with a class exposing
   key/label/description/run_sync/run_async (subclass FlowAdapter or duck-type);
2. import it below and append the class to `ADAPTERS`;
3. done — registry manifest feeds `/api/meta`, validation and dispatch.
"""
from .adapters.base import FlowAdapter
from .adapters.password import PasswordAdapter
from .adapters.sub2api import Sub2ApiAdapter
from .adapters.cpr import CprAdapter

# ---- registry (order defines dropdown order) -------------------------------
ADAPTERS: list[type] = [PasswordAdapter, Sub2ApiAdapter, CprAdapter]

ADAPTER_MAP: dict[str, type] = {a.key: a for a in ADAPTERS}

# login types exposed to the frontend dropdown (label shown, key stored)
LOGIN_TYPES: list[dict] = [a.manifest() for a in ADAPTERS]


def pick_flow(login_type: str, sync: bool):
    """Return the flow callable for `login_type`.

    Unknown / legacy values (e.g. old free-text "password / oauth" rows)
    fall back to the generic password adapter so existing groups keep running.
    """
    cls = ADAPTER_MAP.get((login_type or "").strip().lower(), PasswordAdapter)
    return cls.run_sync if sync else cls.run_async


def validate_login_type(value: str) -> str:
    v = (value or "").strip().lower()
    if v not in ADAPTER_MAP:
        raise ValueError(f"unknown login_type: {value!r}; valid: {sorted(ADAPTER_MAP)}")
    return v


def get_adapter(login_type: str):
    """Return the adapter class for `login_type` (falls back to password)."""
    return ADAPTER_MAP.get((login_type or "").strip().lower(), PasswordAdapter)


async def run_flow(login_type: str, ctx, username: str, password: str,
                   totp_secret: str, login_url: str, steps: list) -> dict:
    """Async entry used by the scheduler (all engines are native async now)."""
    fn = pick_flow(login_type, sync=False)
    return await fn(ctx, username, password, totp_secret, login_url, steps)
