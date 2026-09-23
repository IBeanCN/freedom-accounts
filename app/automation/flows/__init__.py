"""Login flow adapters & group-type registries.

任务类型（login_type）= 流程适配器：sub2api / cpr，见 registry.py。
分组类型（group_type）= 平台注册表：目前 OpenAI，见 app/automation/platforms.py。

Adapter contract (see base.py):
  - `pick_flow(login_type, sync)` returns the flow callable
    `(ctx, username, password, totp_secret, login_url, steps) -> dict`;
  - unknown / retired login_type raises ValueError so incompatible flows never run.
"""
from .registry import (ADAPTERS, LOGIN_TYPES, get_adapter, pick_flow, run_flow,
                       requires_openai_credentials, validate_login_type)
from ..platforms import GROUP_TYPES, PLATFORMS

__all__ = ["ADAPTERS", "LOGIN_TYPES", "GROUP_TYPES", "PLATFORMS",
           "get_adapter", "pick_flow", "requires_openai_credentials",
           "run_flow", "validate_login_type"]
