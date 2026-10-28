"""fingerprint config: CloakBrowser-compatible schema + seed generation.

Fingerprint JSON fields (all optional, all applied via --fingerprint-* flags
when the cloakbrowser engine is available):
  seed, platform, brand, brand_version, gpu_vendor, gpu_renderer,
  hardware_concurrency, device_memory, screen_width, screen_height,
  timezone, locale, webrtc_ip, storage_quota_mb, noise (bool),
  user_agent, viewport_w, viewport_h, geoip (bool)
"""
import json
import random

FINGERPRINT_FIELDS = [
    "seed", "platform", "brand", "brand_version", "gpu_vendor", "gpu_renderer",
    "hardware_concurrency", "device_memory", "screen_width", "screen_height",
    "timezone", "locale", "webrtc_ip", "storage_quota_mb", "noise",
    "user_agent", "viewport_w", "viewport_h", "geoip",
]

_PLATFORMS = ["windows", "macos"]
_BRANDS = ["Chrome", "Edge", "Opera", "Vivaldi"]
_BRAND_VERSIONS = list(range(130, 152))
# GPU 与平台强绑定：Direct3D11 只存在于 Windows，Mac 只有 Apple Metal。
# 跨平台混搭（如 macos + D3D11）是检测站一眼识别的硬伤。
# 三元组：(vendor, renderer 完整串, 下拉展示用的短名)
_GPU_COMBOS = {
    "windows": [
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)", "Intel UHD 630"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Arc(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", "Intel Arc Graphics"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)", "Intel Graphics"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)", "GeForce GTX 1660"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4050 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)", "GeForce RTX 4050 Laptop GPU"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)", "GeForce RTX 4060 Laptop GPU"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)", "Radeon RX 580"),
    ],
    "macos": [
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)", "Apple M1"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)", "Apple M2"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)", "Apple M3"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)", "Apple M4"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M5, Unspecified Version)", "Apple M5"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Pro, Unspecified Version)", "Apple M5 Pro"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Max, Unspecified Version)", "Apple M5 Max"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M6, Unspecified Version)", "Apple M6"),
        ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Intel(R) Iris(TM) Plus Graphics 645, Unspecified Version)", "Iris Plus 645"),
    ],
}
# 内置屏幕使用 Apple 当前 MacBook Air/Pro 官方原生分辨率；其余为常见 Mac 外接/缩放分辨率。
_SCREENS = {
    "windows": [
        (1280, 720), (1366, 768), (1440, 900), (1536, 864), (1600, 900), (1920, 1080),
        (1920, 1200), (2880, 1800), (3200, 2000), (3840, 2400),
    ],
    "macos": [
        (1440, 900), (1470, 956), (1512, 982), (1728, 1117), (1920, 1080), (2560, 1440),
        (2560, 1664),  # MacBook Air 13-inch
        (2880, 1864),  # MacBook Air 15-inch
        (3024, 1964),  # MacBook Pro 14-inch
        (3456, 2234),  # MacBook Pro 16-inch
    ],
}
_CORES = {
    "windows": [4, 6, 8, 12, 16],
    "macos": [8, 10, 12, 15, 18],  # M1=8 / Air M5=10 / M6=12 / M5 Pro=15/18 / M5 Max=18
}
_TIMEZONES = ["Asia/Shanghai", "Asia/Tokyo", "America/New_York", "America/Chicago",
              "Europe/London", "Europe/Berlin", "Asia/Singapore", "America/Los_Angeles"]
_LOCALES = ["zh-CN", "en-US", "en-GB", "ja-JP", "ko-KR", "de-DE"]

# 种子区间与引擎自身的生成口径一致：SDK 的 get_default_stealth_args() 用的是
# random.randint(10000, 99999)，文档也把默认值写成 Random (10000–99999)。
# 引擎按 seed 确定性派生 canvas / WebGL / audio / 字体噪声，落在它自己的分布内最稳妥。
SEED_MIN = 10000
SEED_MAX = 99999

# WebRTC 只允许走代理的候选：HTTP 代理没有 UDP 中继，效果等于关掉 WebRTC，
# 但绝不会退回本机网卡去发 STUN，真实出口 IP 不会泄露。
# 注意引擎只认裸开关 --webrtc-ip-handling-policy（实测二进制里没有 force- 前缀变体）。
WEBRTC_POLICY_ARG = "--webrtc-ip-handling-policy=disable_non_proxied_udp"

# 内存档位按平台区分（与 cores / screens / gpus 同一套规则）：
# Mac 报的是统一内存可选档位，Windows 报的是 DDR5/LPDDR5X 物理内存档位。
# 混用一个池会随机出「Windows 36GB」「Mac 4GB 独显本」这类不存在的组合。
_MEMORY = {
    # M6 MacBook Pro 14：16/24/32；MacBook Air M5：16/24/32；
    # M5 Pro：24/48/64；M5 Max：36/48/64/128；8GB 留给存量 M1/M2 机型。
    "macos": [8, 16, 24, 32, 36, 48, 64, 128],
    # 轻薄本 8/16；DDR5 双通道常见 24/32；独显与移动工作站 64/128。
    "windows": [8, 16, 24, 32, 64, 128],
}

# 合法选项池：/api/meta 下发给前端做下拉选择，前端「随机生成」也读这份数据，
# 保证表单可选项、前端随机、后端 generate_fingerprint 三处永远一致。
FP_OPTIONS = {
    "platforms": _PLATFORMS,
    "brands": _BRANDS,
    "brand_versions": _BRAND_VERSIONS,
    "gpus": {
        p: [{"vendor": v, "renderer": r, "label": lb} for v, r, lb in combos]
        for p, combos in _GPU_COMBOS.items()
    },
    "screens": {
        p: [{"width": w, "height": h} for w, h in ss]
        for p, ss in _SCREENS.items()
    },
    "cores": _CORES,
    "memory": _MEMORY,
    "timezones": _TIMEZONES,
    "locales": _LOCALES,
}


def random_seed() -> int:
    """5-digit seed, same range the engine generates for itself."""
    return random.randint(SEED_MIN, SEED_MAX)


def generate_fingerprint() -> dict:
    """Random but self-consistent fingerprint config."""
    platform = random.choice(_PLATFORMS)
    gpu = random.choice(_GPU_COMBOS[platform])
    width, height = random.choice(_SCREENS[platform])
    fp = {
        "seed": random_seed(),
        "platform": platform,
        "brand": random.choice(_BRANDS),
        "brand_version": random.choice(_BRAND_VERSIONS),
        "gpu_vendor": gpu[0],
        "gpu_renderer": gpu[1],
        "hardware_concurrency": random.choice(_CORES[platform]),
        "device_memory": random.choice(_MEMORY[platform]),
        "screen_width": width,
        "screen_height": height,
        "timezone": random.choice(_TIMEZONES),
        "locale": random.choice(_LOCALES),
        "webrtc_ip": "auto",
        "noise": True,
        "geoip": True,
    }
    return fp


def generate_from_template(template: dict | str | None) -> dict:
    """Build an account fingerprint from a group-level template.

    Company machines are bought/installed in batches, so accounts in one group
    usually share the same platform/screen/GPU/timezone; only the seed (and any
    fields the template omits) must vary per account. The template never
    carries a seed — one is always randomized here.
    """
    base = {k: v for k, v in sanitize(template).items() if k != "seed"}
    base["seed"] = random_seed()
    return base


def as_template(raw: dict | str | None) -> dict:
    """Normalize a user-supplied template for storage: known fields only, no seed."""
    tpl = sanitize(raw)
    tpl.pop("seed", None)
    return tpl


def sanitize(fp: dict | str | None) -> dict:
    """Keep only known fields; accept JSON string input."""
    if fp is None or fp == "":
        return {}
    if isinstance(fp, str):
        try:
            fp = json.loads(fp)
        except Exception:
            return {}
    if not isinstance(fp, dict):
        return {}
    return {k: fp[k] for k in FINGERPRINT_FIELDS if k in fp and fp[k] not in (None, "")}


def cloak_args(fp: dict) -> list[str]:
    """Map fingerprint dict to CloakBrowser --fingerprint-* command line flags."""
    # WebRTC 策略与指纹字段无关，任何启动都要带上。
    args: list[str] = [WEBRTC_POLICY_ARG]
    if not fp:
        return args
    m = {
        # seed 是引擎的主开关 --fingerprint=<seed>（没有 --fingerprint-seed 这个开关；
        # 用错名字会被静默忽略，SDK 自带的随机 seed 反而生效，账号声明的种子形同虚设）。
        "seed": "--fingerprint",
        "platform": "--fingerprint-platform",
        "brand": "--fingerprint-brand",
        "brand_version": "--fingerprint-brand-version",
        "gpu_vendor": "--fingerprint-gpu-vendor",
        "gpu_renderer": "--fingerprint-gpu-renderer",
        "hardware_concurrency": "--fingerprint-hardware-concurrency",
        "device_memory": "--fingerprint-device-memory",
        "screen_width": "--fingerprint-screen-width",
        "screen_height": "--fingerprint-screen-height",
        "timezone": "--fingerprint-timezone",
        "locale": "--fingerprint-locale",
        "webrtc_ip": "--fingerprint-webrtc-ip",
        "storage_quota_mb": "--fingerprint-storage-quota",
    }
    for key, flag in m.items():
        v = fp.get(key)
        if v not in (None, ""):
            # single token "flag=value": Playwright rejects bare values as pages
            args.append(f"{flag}={v}")
    if fp.get("noise") is False:
        args.append("--fingerprint-noise=false")
    return args


def context_kwargs(fp: dict) -> dict:
    """Playwright browser-context level settings from the fingerprint dict."""
    kw: dict = {}
    if fp.get("user_agent"):
        kw["user_agent"] = fp["user_agent"]
    if fp.get("locale"):
        kw["locale"] = fp["locale"]
    if fp.get("timezone"):
        kw["timezone_id"] = fp["timezone"]
    vw, vh = fp.get("viewport_w"), fp.get("viewport_h")
    if not (vw and vh) and fp.get("screen_width") and fp.get("screen_height"):
        vw, vh = fp.get("screen_width"), fp.get("screen_height")
    if vw and vh:
        kw["viewport"] = {"width": int(vw), "height": int(vh)}
    return kw
