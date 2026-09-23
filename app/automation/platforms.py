"""Group-type (platform) registry — dropdown source & future per-platform hooks.

目前只有 OpenAI；扩展新平台时在 `PLATFORMS` 追加一个条目即可，
前端下拉、后端校验、`/api/meta` 全部自动跟随。

预留钩子（当前未启用，需要时在 PlatformSpec 上加字段/方法）：
  - default_login_type: 新建分组时前端默认选中的任务类型
  - login_url_hint:     任务地址占位提示
  - 未来可扩展：平台专属指纹模板、专属流程后处理、回调 payload 变换……
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlatformSpec:
    key: str                 # stored in groups.group_type
    label: str               # dropdown label
    description: str = ""
    default_login_type: str = "sub2api"
    login_url_hint: str = "https://"


PLATFORMS: list[PlatformSpec] = [
    PlatformSpec(
        key="OpenAI-openai",
        label="OpenAI",
        description="OpenAI / ChatGPT 账号池",
        default_login_type="sub2api",
        login_url_hint="https://auth.openai.com/或 sub2api 站点地址",
    ),
]

PLATFORM_MAP: dict[str, PlatformSpec] = {p.key: p for p in PLATFORMS}

# frontend dropdown manifest
GROUP_TYPES: list[dict] = [
    {"key": p.key, "label": p.label, "description": p.description,
     "default_login_type": p.default_login_type, "login_url_hint": p.login_url_hint}
    for p in PLATFORMS
]

# allow legacy free-text values already stored in DB; new values must register
KNOWN_TYPE_KEYS = set(PLATFORM_MAP)


def is_known_group_type(value: str) -> bool:
    return (value or "").strip() in KNOWN_TYPE_KEYS


def default_login_url_hint(group_type: str) -> str:
    p = PLATFORM_MAP.get((group_type or "").strip())
    return p.login_url_hint if p else "https://"
