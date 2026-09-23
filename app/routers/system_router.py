"""Tasks & settings & system routers."""
import ipaddress
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import crypto, database, settings
from ..core import tasks
from ..automation import browser as browser_mod
from ..automation.phone import get_phone_adapter
from ..automation.phone.countries import COUNTRY_BY_ISO2
from .deps import require_admin

router = APIRouter(prefix="/api", tags=["system"])


# ---------------- meta (registries for authenticated frontend dropdowns) ----------------
@router.get("/meta")
async def get_meta(_: None = Depends(require_admin)):
    """Adapter/registry manifests: login types (flow adapters), group types (platforms), fingerprint option pools."""
    from ..automation.flows import LOGIN_TYPES
    from ..automation.platforms import GROUP_TYPES
    from ..automation.fingerprint import FP_OPTIONS
    return {"login_types": LOGIN_TYPES, "group_types": GROUP_TYPES, "fp_options": FP_OPTIONS}


# ---------------- tasks ----------------
@router.get("/tasks")
async def list_tasks(group_id: int | None = None, status: str | None = None,
                     limit: int = 100, _: None = Depends(require_admin)):
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
async def get_task(task_id: int, _: None = Depends(require_admin)):
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
    token_refresh_interval_seconds: int | None = Field(
        default=None, ge=60, le=2_592_000)
    fp_check_url: str | None = None
    phone_verification_mode: str | None = Field(
        default=None, pattern="^(manual|auto)$")
    phone_verification_platform: str | None = None
    phone_verification_country: str | None = Field(default=None, max_length=16)
    phone_verification_page_country: str | None = Field(default=None, max_length=2)
    phone_verification_api_key: str | None = None
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
    try:
        token_interval = max(60, int(await settings.get(
            "token_refresh_interval_seconds") or 3600))
    except ValueError:
        token_interval = 3600
    return {
        "global_browser_mode": await settings.get("global_browser_mode") or "headless",
        "cloak_cdp_url": cdp,
        "log_retention_days": retention,
        "token_refresh_interval_seconds": token_interval,
        "fp_check_url": await settings.get("fp_check_url") or "",
        "phone_verification_mode": await settings.get("phone_verification_mode") or "manual",
        "phone_verification_platform": await settings.get("phone_verification_platform") or "hero_sms",
        "phone_verification_country": await settings.get("phone_verification_country") or "",
        "phone_verification_page_country": await settings.get("phone_verification_page_country") or "",
        "phone_verification_api_key_set": bool(
            await settings.get("phone_verification_api_key")),
        "default_geo_country": await settings.get("default_geo_country") or "",
        "default_geo_region": await settings.get("default_geo_region") or "",
        "default_geo_city": await settings.get("default_geo_city") or "",
        "default_geo_timezone": await settings.get("default_geo_timezone") or "",
        "default_geo_locale": await settings.get("default_geo_locale") or "",
        "cloak_license_key_set": bool(browser_mod.license_key_source() != "none"),
        "engine": {**browser_mod.engine_info(), "cloak_version": browser_mod.cloak_version(),
                   "cdp_version": await browser_mod.cdp_version(cdp)},
    }


async def _resolve_api_key(api_key_override: str = "") -> str:
    """Caller-provided key wins; otherwise fall back to the saved encrypted key."""
    if api_key_override.strip():
        return api_key_override.strip()
    encrypted_key = await settings.get("phone_verification_api_key") or ""
    return crypto.decrypt(encrypted_key) if encrypted_key else ""


async def _list_phone_countries(platform: str, api_key: str) -> list[dict]:
    """Read provider countries; raises so the caller can report the reason."""
    if not platform or not api_key:
        return []
    adapter = get_phone_adapter(platform)()
    countries = await adapter.get_countries(api_key)
    normalized: dict[str, dict] = {}
    for item in countries:
        code = str(getattr(item, "code", "") or "").strip()
        if not code:
            continue
        name = str(getattr(item, "name", "") or "").strip()
        normalized.setdefault(code.upper(), {"code": code, "name": name})
    return sorted(normalized.values(),
                  key=lambda item: (item["name"] or item["code"]).lower())


@router.get("/settings/phone-countries")
async def get_phone_countries(platform: str = "",
                              api_key: str = "",
                              _: None = Depends(require_admin)):
    if not platform.strip():
        platform = await settings.get("phone_verification_platform") or ""
    key = await _resolve_api_key(api_key)
    try:
        countries = await _list_phone_countries(platform, key)
    except Exception as e:
        return {"countries": [], "error": str(e)}
    return {"countries": countries}


@router.get("/settings/phone-balance")
async def get_phone_balance(platform: str = "",
                            api_key: str = "",
                            _: None = Depends(require_admin)):
    """Query the provider balance; optional api_key overrides the saved key."""
    if not platform.strip():
        platform = await settings.get("phone_verification_platform") or ""
    key = await _resolve_api_key(api_key)
    if not platform or not key:
        return {"balance": ""}
    try:
        adapter = get_phone_adapter(platform)()
        return {"balance": await adapter.get_balance(key)}
    except Exception as e:
        raise HTTPException(502, f"余额查询失败: {e}")


@router.get("/settings/page-countries")
async def get_page_countries(_: None = Depends(require_admin)):
    """Return OpenAI page countries separately from SMS-provider country IDs."""
    countries = [
        {"code": iso2, "name": info["zh"] or info["en"], "dial_code": info["dial_code"]}
        for iso2, info in COUNTRY_BY_ISO2.items()
    ]
    countries.sort(key=lambda item: (item["name"], item["code"]))
    return {"countries": countries}


@router.put("/settings")
async def update_settings(body: SettingsBody, _: None = Depends(require_admin)):
    if body.phone_verification_mode == "auto":
        platform = body.phone_verification_platform
        platform = (platform if platform is not None
                    else await settings.get("phone_verification_platform") or "hero_sms")
        try:
            get_phone_adapter(platform)
        except ValueError as e:
            raise HTTPException(400, str(e))
        country = body.phone_verification_country
        country = (country if country is not None
                   else await settings.get("phone_verification_country")).strip()
        raw_key = (body.phone_verification_api_key if body.phone_verification_api_key is not None
                   else await settings.get("phone_verification_api_key"))
        api_key = crypto.decrypt(raw_key or "").strip()
        if not country:
            raise HTTPException(400, "自动手机号验证需要选择国家")
        if not api_key:
            raise HTTPException(400, "自动手机号验证需要 API Key")
        page_country = body.phone_verification_page_country
        page_country = (page_country if page_country is not None
                        else await settings.get("phone_verification_page_country") or "")
        page_country = page_country.strip().upper()
        if len(page_country) != 2 or not page_country.isalpha():
            raise HTTPException(400, "自动手机号验证需要两位国家编码")
        if page_country not in COUNTRY_BY_ISO2:
            raise HTTPException(400, f"不支持的国家编码: {page_country}")
    if body.global_browser_mode:
        await settings.set_value("global_browser_mode", body.global_browser_mode)
    if body.cloak_cdp_url is not None:
        await settings.set_value("cloak_cdp_url", body.cloak_cdp_url.strip())
    if body.log_retention_days is not None:
        await settings.set_value("log_retention_days", str(body.log_retention_days))
    if body.token_refresh_interval_seconds is not None:
        await settings.set_value(
            "token_refresh_interval_seconds", str(body.token_refresh_interval_seconds))
    if body.fp_check_url is not None:
        await settings.set_value("fp_check_url", body.fp_check_url.strip())
    if body.phone_verification_mode is not None:
        await settings.set_value("phone_verification_mode", body.phone_verification_mode)
    if body.phone_verification_platform is not None:
        await settings.set_value(
            "phone_verification_platform", body.phone_verification_platform.strip())
    if body.phone_verification_country is not None:
        await settings.set_value(
            "phone_verification_country", body.phone_verification_country.strip())
    if body.phone_verification_page_country is not None:
        await settings.set_value(
            "phone_verification_page_country",
            body.phone_verification_page_country.strip().upper())
    if body.phone_verification_api_key is not None:
        await settings.set_value(
            "phone_verification_api_key",
            crypto.ensure_encrypted(body.phone_verification_api_key.strip()))
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
    "IN": "en-IN", "PH": "en-PH",
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
async def geo_lookup(ip: str = "", _: None = Depends(require_admin)):
    """Resolve an exit IP (or this server's own exit IP when omitted) to geo info.

    Chain: with an explicit ip -> ipwho.is/{ip}. Without one -> learn the exit
    IP via ipify first, then resolve it; when ipify is unreachable, fall back to
    a bare https://ipwho.is/ call, which resolves the caller's own exit IP.
    Returns {ok, ip, country, region, city, timezone, locale, error}.
    """
    import httpx

    ip = (ip or "").strip()
    if ip:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return {"ok": False, "ip": ip, "error": "无效的 IP 地址"}
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

@router.get("/settings/phone-dom-check")
async def phone_dom_check(_: None = Depends(require_admin)):
    """Probe add-phone selectors on the first active managed browser page."""
    page = (browser_mod.get_first_managed_page() or browser_mod.get_first_task_page())
    if page is None:
        return {"ok": False, "url": "",
                "error": "没有活跃的指纹浏览器会话，请先打开浏览器",
                "checks": []}
    checks = []
    for sel in ['div[data-trigger="Select"]', '[role="listbox"]',
                'div[role="option"]', 'input#tel',
                'input[type="radio"][value="sms"]']:
        try:
            loc = page.locator(sel)
            count = await loc.count()
            sample = ""
            if count and "option" in sel:
                sample = (await loc.first.text_content() or "")[:80]
            checks.append({"selector": sel, "count": count, "sample": sample})
        except Exception as e:
            checks.append({"selector": sel, "count": -1, "error": str(e)[:200]})
    # Dump the HTML structure around input#tel to find the area code selector
    try:
        dom_explore = await page.evaluate("""() => {
            const tel = document.querySelector('input#tel');
            if (!tel) return [{error: 'input#tel not found'}];
            let container = tel.parentElement;
            for (let i = 0; i < 4 && container; i++) {
                if (container.querySelectorAll('div,span,button,select').length > 3) break;
                container = container.parentElement;
            }
            return [{html: container ? container.outerHTML.slice(0, 3000) : 'no container'}];
        }""")
    except Exception as e:
        dom_explore = [{"error": str(e)[:200]}]
    return {"ok": True, "url": page.url, "checks": checks, "dom_explore": dom_explore}


class PageExecBody(BaseModel):
    js: str = Field(min_length=1)


@router.post("/settings/phone-page-exec")
async def phone_page_exec(body: PageExecBody,
                          _: None = Depends(require_admin)):
    """Execute arbitrary JS on the active managed browser page (diagnostic)."""
    page = (browser_mod.get_first_managed_page() or browser_mod.get_first_task_page())
    if page is None:
        raise HTTPException(404, "没有活跃的指纹浏览器会话")
    try:
        result = await page.evaluate(body.js)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


@router.post("/logs/prune")
async def prune_logs_now(_: None = Depends(require_admin)):
    """Manually sweep expired logs (normally done hourly by the pruner)."""
    from ..core import maintenance
    return await maintenance.prune_once()
