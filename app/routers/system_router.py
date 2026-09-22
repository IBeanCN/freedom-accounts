"""Tasks & settings & system routers."""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core import database, settings
from ..automation import browser as browser_mod
from .deps import require_admin

router = APIRouter(prefix="/api", tags=["system"])


# ---------------- meta (registries for frontend dropdowns) ----------------
@router.get("/meta")
async def get_meta():
    """Adapter/registry manifests: login types (flow adapters) & group types (platforms)."""
    from ..automation.flows import LOGIN_TYPES
    from ..automation.platforms import GROUP_TYPES
    return {"login_types": LOGIN_TYPES, "group_types": GROUP_TYPES}


# ---------------- tasks ----------------
@router.get("/tasks")
async def list_tasks(group_id: int | None = None, status: str | None = None,
                     limit: int = 100):
    db = await database.get_db()
    sql = """SELECT t.*, a.username, g.name AS group_name
             FROM tasks t LEFT JOIN accounts a ON a.id=t.account_id
             LEFT JOIN groups g ON g.id=t.group_id WHERE 1=1"""
    args: list = []
    if group_id is not None:
        sql += " AND t.group_id=?"; args.append(group_id)
    if status:
        sql += " AND t.status=?"; args.append(status)
    sql += " ORDER BY t.id DESC LIMIT ?"; args.append(min(limit, 500))
    rows = await db.execute(sql, tuple(args))
    tasks = []
    for r in await rows.fetchall():
        d = dict(r)
        for k in ("steps", "result_json", "fingerprint_json"):
            try:
                d[k] = json.loads(d.get(k) or ("{}" if k != "steps" else "[]"))
            except Exception:
                pass
        tasks.append(d)
    return {"tasks": tasks}


@router.get("/tasks/{task_id}")
async def get_task(task_id: int):
    db = await database.get_db()
    row = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    t = await row.fetchone()
    if not t:
        from fastapi import HTTPException
        raise HTTPException(404, "task not found")
    return dict(t)


# ---------------- settings ----------------
class SettingsBody(BaseModel):
    global_browser_mode: str | None = Field(default=None, pattern="^(headless|headed)$")
    cloak_cdp_url: str | None = None
    log_retention_days: int | None = Field(default=None, ge=1, le=365)
    fp_check_url: str | None = None
    default_geo_country: str | None = Field(default=None, max_length=2)
    default_geo_region: str | None = None
    default_geo_city: str | None = None
    default_geo_timezone: str | None = None
    default_geo_locale: str | None = None


@router.get("/settings")
async def get_settings(_: None = Depends(require_admin)):
    cdp = await settings.get("cloak_cdp_url") or ""
    try:
        retention = max(1, int(await settings.get("log_retention_days") or 3))
    except ValueError:
        retention = 3
    return {
        "global_browser_mode": await settings.get("global_browser_mode") or "headless",
        "cloak_cdp_url": cdp,
        "log_retention_days": retention,
        "fp_check_url": await settings.get("fp_check_url") or "",
        "default_geo_country": await settings.get("default_geo_country") or "",
        "default_geo_region": await settings.get("default_geo_region") or "",
        "default_geo_city": await settings.get("default_geo_city") or "",
        "default_geo_timezone": await settings.get("default_geo_timezone") or "",
        "default_geo_locale": await settings.get("default_geo_locale") or "",
        "cloak_license_key_set": bool(browser_mod.license_key_source() != "none"),
        "engine": {**browser_mod.engine_info(), "cloak_version": browser_mod.cloak_version(),
                   "cdp_version": await browser_mod.cdp_version(cdp)},
    }


@router.put("/settings")
async def update_settings(body: SettingsBody, _: None = Depends(require_admin)):
    if body.global_browser_mode:
        await settings.set_value("global_browser_mode", body.global_browser_mode)
    if body.cloak_cdp_url is not None:
        await settings.set_value("cloak_cdp_url", body.cloak_cdp_url.strip())
    if body.log_retention_days is not None:
        await settings.set_value("log_retention_days", str(body.log_retention_days))
    if body.fp_check_url is not None:
        await settings.set_value("fp_check_url", body.fp_check_url.strip())
    for key in ("default_geo_country", "default_geo_region", "default_geo_city",
                "default_geo_timezone", "default_geo_locale"):
        val = getattr(body, key)
        if val is not None:
            await settings.set_value(key, val.strip())
    return {"ok": True}


# ---------------- geo lookup (ipwho.is) ----------------
_GEO_ENDPOINT = "https://ipwho.is/{ip}"

# 国家代码 -> BCP47 语言。指纹 locale 用：浏览器语言需与出口 IP 所在地一致，
# 否时区/语言组合本身就是风控特征。未命中的国家回退 en-US。
_COUNTRY_LOCALE = {
    "CN": "zh-CN", "TW": "zh-TW", "HK": "zh-HK", "SG": "zh-SG",
    "JP": "ja-JP", "KR": "ko-KR",
    "US": "en-US", "GB": "en-GB", "AU": "en-AU", "CA": "en-CA",
    "IN": "en-IN", "PH": "en-PH", "SG_": "en-SG",
    "DE": "de-DE", "AT": "de-AT", "CH": "de-CH",
    "FR": "fr-FR", "BE": "fr-BE",
    "ES": "es-ES", "MX": "es-MX", "AR": "es-AR",
    "PT": "pt-PT", "BR": "pt-BR",
    "IT": "it-IT", "NL": "nl-NL", "SE": "sv-SE", "NO": "nb-NO",
    "DK": "da-DK", "FI": "fi-FI", "PL": "pl-PL", "RU": "ru-RU",
    "UA": "uk-UA", "CZ": "cs-CZ", "TR": "tr-TR",
    "TH": "th-TH", "VN": "vi-VN", "ID": "id-ID", "MY": "ms-MY",
    "SA": "ar-SA", "AE": "ar-AE", "IL": "he-IL",
}


def locale_for_country(country_code: str) -> str:
    """Country code -> best-match BCP47 locale; unknown falls back to en-US."""
    cc = (country_code or "").strip().upper()
    if cc in _COUNTRY_LOCALE:
        return _COUNTRY_LOCALE[cc]
    # same-language fallback: two-letter country == language code (de-DE style)
    return f"{cc.lower()}-{cc}" if len(cc) == 2 else "en-US"


@router.get("/geo/lookup")
async def geo_lookup(ip: str = ""):
    """Resolve an exit IP (or this server's own exit IP when omitted) to geo info.

    Chain: with an explicit ip -> ipwho.is/{ip}. Without one -> learn the exit
    IP via ipify first, then resolve it; when ipify is unreachable, fall back to
    a bare https://ipwho.is/ call, which resolves the caller's own exit IP.
    Returns {ok, ip, country, region, city, timezone, locale, error}.
    """
    import httpx

    ip = (ip or "").strip()
    async with httpx.AsyncClient(timeout=12, trust_env=False) as c:
        if ip:
            return _geo_parse(ip, await _geo_fetch(c, ip))        # 1) learn own exit IP via ipify, then resolve it
        try:
            r = await c.get("https://api.ipify.org?format=json")
            r.raise_for_status()
            learned = str((r.json() or {}).get("ip") or "").strip()
            if learned:
                return _geo_parse(learned, await _geo_fetch(c, learned))
        except Exception:
            pass
        # 2) fallback: bare ipwho.is resolves the caller's exit IP directly
        d = await _geo_fetch(c, "")
        if d.get("success", True) and d.get("ip"):
            return _geo_parse(str(d["ip"]), d)
        return {"ok": False, "ip": "", "error": "获取出口 IP 失败"}


async def _geo_fetch(c: "httpx.AsyncClient", ip: str) -> dict:
    try:
        r = await c.get(_GEO_ENDPOINT.format(ip=ip))
        r.raise_for_status()
        return r.json() or {}
    except Exception:
        return {}


def _geo_parse(ip: str, d: dict) -> dict:
    if not d or not d.get("success", True):
        return {"ok": False, "ip": ip,
                "error": str((d or {}).get("message") or "解析失败")}
    tz = d.get("timezone")
    tz_id = (tz.get("id") or "").strip() if isinstance(tz, dict) else str(tz or "").strip()
    country = (d.get("country_code") or "").strip()
    return {
        "ok": True,
        "ip": ip,
        "country": country,
        "region": (d.get("region") or "").strip(),
        "city": (d.get("city") or "").strip(),
        "timezone": tz_id,
        "locale": locale_for_country(country),
        "error": "",
    }


# ---------------- log maintenance ----------------
@router.post("/logs/prune")
async def prune_logs_now(_: None = Depends(require_admin)):
    """Manually sweep expired logs (normally done hourly by the pruner)."""
    from ..core import maintenance
    return await maintenance.prune_once()
