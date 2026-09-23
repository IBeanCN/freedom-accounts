"""Flow adapter registration. Add a new login type in three steps:

1. create `adapters/<key>.py` with a class exposing
   key/label/description/run_sync/run_async (subclass FlowAdapter or duck-type);
2. import it below and append the class to `ADAPTERS`;
3. done — registry manifest feeds `/api/meta`, validation and dispatch.
"""
import inspect

from .adapters.base import FlowAdapter
from .adapters.sub2api import Sub2ApiAdapter
from .adapters.cpr import CprAdapter

# ---- registry (order defines dropdown order) -------------------------------
ADAPTERS: list[type] = [Sub2ApiAdapter, CprAdapter]

ADAPTER_MAP: dict[str, type] = {a.key: a for a in ADAPTERS}
_RUN_CONTEXT_SUPPORTED: dict[object, bool] = {}

# login types exposed to the frontend dropdown (label shown, key stored)
LOGIN_TYPES: list[dict] = [a.manifest() for a in ADAPTERS]

# OpenAI 授权流程必须有账号密码；TOTP 可选，但已配置时必须可用。
OPENAI_AUTH_TYPES = {"sub2api", "cpr"}


def pick_flow(login_type: str, sync: bool):
    """Return the flow callable for `login_type`.

    The generic password adapter has been retired; unknown or legacy values
    fail fast instead of running an incompatible flow.
    """
    key = (login_type or "").strip().lower()
    if key not in ADAPTER_MAP:
        raise ValueError(f"unsupported login_type: {login_type!r}; valid: {sorted(ADAPTER_MAP)}")
    cls = ADAPTER_MAP[key]
    return cls.run_sync if sync else cls.run_async


def validate_login_type(value: str) -> str:
    v = (value or "").strip().lower()
    if v not in ADAPTER_MAP:
        raise ValueError(f"unknown login_type: {value!r}; valid: {sorted(ADAPTER_MAP)}")
    return v


def get_adapter(login_type: str):
    """Return the adapter class; unknown / retired types fail fast."""
    key = (login_type or "").strip().lower()
    if key not in ADAPTER_MAP:
        raise ValueError(f"unsupported login_type: {login_type!r}; valid: {sorted(ADAPTER_MAP)}")
    return ADAPTER_MAP[key]


def requires_openai_credentials(login_type: str) -> bool:
    """Whether a flow performs the shared OpenAI browser auth sequence."""
    return (login_type or "").strip().lower() in OPENAI_AUTH_TYPES


async def run_flow(login_type: str, ctx, username: str, password: str,
                   totp_secret: str, login_url: str, steps: list,
                   group: dict | None = None, account: dict | None = None,
                   cdp_engine: bool = False, phone_handler=None) -> dict:
    """Async entry used by the scheduler (all engines are native async now).

    ``group`` / ``account`` carry the DB rows (extra kwargs, keyword-only in
    spirit): adapters needing upstream context (e.g. sub2api OAuth via
    upstream_key / remote_id) read them; legacy adapters ignore them.
    ``cdp_engine`` / ``phone_handler`` carry engine policy and the optional
    automatic phone-enrollment provider into OpenAI flows.
    """
    fn = pick_flow(login_type, sync=False)
    supports_context = _RUN_CONTEXT_SUPPORTED.get(fn)
    if supports_context is None:
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        supports_context = any(
            name in ("group", "account", "cdp_engine", "phone_handler")
            or param.kind == inspect.Parameter.VAR_KEYWORD
            for name, param in params.items()
        )
        _RUN_CONTEXT_SUPPORTED[fn] = supports_context
    if supports_context:
        return await fn(ctx, username, password, totp_secret, login_url, steps,
                        group=group, account=account, cdp_engine=cdp_engine,
                        phone_handler=phone_handler)
    return await fn(ctx, username, password, totp_secret, login_url, steps)
