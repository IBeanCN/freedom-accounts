"""Browser engine launcher.

Engine priority:
  1. cloakserve remote CDP (if cloak_cdp_url configured) — connect_over_cdp with
     a per-account fingerprint seed; closed via /fingerprint/{seed}/close.
  2. cloakbrowser SDK native async API (launch_async / launch_persistent_context
     via anyio worker; SDK >= 0.5.x exposes async Playwright-compatible objects).
  3. Playwright bundled Chromium fallback (context-level spoofing).
"""
import asyncio
import contextlib
import json
import sys
import uuid
from pathlib import Path

import httpx

from ..core import config, database, settings
from . import fingerprint as fp_mod

# Try to import cloakbrowser SDK once at module load.
try:
    import cloakbrowser  # type: ignore
    HAS_CLOAK = True
    # native async entrypoints present?
    HAS_CLOAK_ASYNC = hasattr(cloakbrowser, "launch_async")
except Exception:
    cloakbrowser = None
    HAS_CLOAK = False
    HAS_CLOAK_ASYNC = False

_engine_last_error = ""


def engine_name() -> str:
    return "cloakbrowser" if HAS_CLOAK else "playwright"


def engine_info() -> dict:
    return {
        "engine": engine_name(),
        "cloak_available": HAS_CLOAK,
        "async_api": HAS_CLOAK_ASYNC,
        "license_key_source": license_key_source(),
        "last_error": _engine_last_error,
        "python": sys.version.split()[0],
    }


def license_key_source() -> str:
    """Where the CloakBrowser license key comes from: env(.env) / file(~/.cloakbrowser) / none."""
    if config.CLOAKBROWSER_LICENSE_KEY:
        return "env"
    key_file = Path.home() / ".cloakbrowser" / "license.key"
    try:
        if key_file.exists() and key_file.read_text().strip():
            return "file"
    except OSError:
        pass
    return "none"


def cloak_version() -> str:
    """Read-only cloakbrowser binary version; best-effort, never raises."""
    if not HAS_CLOAK or not hasattr(cloakbrowser, "binary_info"):
        return ""
    try:
        info = cloakbrowser.binary_info()
        return str(info.get("version") or "") if info.get("installed") else ""
    except Exception:
        return ""


async def cdp_version(cdp_url: str) -> str:
    """Probe a running cloakserve's Chrome version via /json/version; '' on failure."""
    if not cdp_url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{cdp_url.rstrip('/')}/json/version")
            data = r.json()
        browser = str(data.get("Browser") or "")
        return browser.split("/", 1)[1] if "/" in browser else browser
    except Exception:
        return ""


async def resolve_browser_mode(account_mode: str, group_mode: str) -> str:
    """Priority: account > group > global setting."""
    if account_mode in ("headless", "headed"):
        return account_mode
    if group_mode in ("headless", "headed"):
        return group_mode
    return await settings.get("global_browser_mode") or "headless"


async def resolve_proxy(account_proxy_id, group_proxy_id) -> str:
    """Proxy priority: account > group; NULL/0/missing on both -> '' (direct).

    Returns the full proxy server URL from the proxies table.
    """
    pid = account_proxy_id or group_proxy_id
    if not pid:
        return ""
    db = await database.get_db()
    row = await db.execute("SELECT server FROM proxies WHERE id=?", (pid,))
    p = await row.fetchone()
    if not p or not (p["server"] or "").strip():
        return ""
    return p["server"].strip()


# --------------------------------------------------------------------------
# Engine 1: cloakserve remote CDP (native async playwright)
# --------------------------------------------------------------------------
async def _launch_cloakserve(cdp_url: str, fp: dict, ctx_kwargs: dict,
                             proxy_server: str = ""):
    global _engine_last_error
    from playwright.async_api import async_playwright

    seed = str(fp.get("seed") or uuid.uuid4().hex[:12])
    base = cdp_url.rstrip("/")
    url = f"{base}/?fingerprint={seed}"
    if fp.get("timezone"):
        url += f"&timezone={fp['timezone']}"
    if fp.get("locale"):
        url += f"&locale={fp['locale']}"
    if proxy_server:
        url += f"&proxy={proxy_server}"

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(url)
    except Exception as e:
        with contextlib.suppress(Exception):
            await pw.stop()
        _engine_last_error = f"cloakserve connect failed: {e}"
        raise

    context = browser.contexts[0] if browser.contexts else await browser.new_context(**ctx_kwargs)

    async def close_remote():
        with contextlib.suppress(Exception):
            await browser.close()
        with contextlib.suppress(Exception):
            await pw.stop()
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{base}/fingerprint/{seed}/close")

    return close_remote, context, f"cloakserve(seed={seed})"


# --------------------------------------------------------------------------
# Engine 2: cloakbrowser SDK (native async)
# --------------------------------------------------------------------------
async def _launch_cloak_sdk(cmd_args: list[str], ctx_kwargs: dict,
                            headless: bool, user_data_dir: Path,
                            proxy_server: str = ""):
    global _engine_last_error
    # License key comes from .env only (config.CLOAKBROWSER_LICENSE_KEY);
    # editing it requires a service restart, by design.
    license_key = config.CLOAKBROWSER_LICENSE_KEY or None
    kwargs = dict(headless=headless, args=cmd_args, license_key=license_key)
    if proxy_server:
        # Playwright-compatible proxy option (also understood by the SDK)
        kwargs["proxy"] = {"server": proxy_server}
    try:
        # native async persistent context (keeps cookies/localStorage per profile)
        ctx = await cloakbrowser.launch_persistent_context_async(
            str(user_data_dir), **kwargs) if hasattr(
                cloakbrowser, "launch_persistent_context_async") else None
        if ctx is None:
            browser = await cloakbrowser.launch_async(**kwargs)
            ctx = await browser.new_context(**ctx_kwargs)
    except Exception as e:
        _engine_last_error = f"cloakbrowser async launch failed: {e}"
        raise

    async def closer():
        with contextlib.suppress(Exception):
            await ctx.close()

    return closer, ctx


# --------------------------------------------------------------------------
# Engine 3: Playwright fallback (native async)
# --------------------------------------------------------------------------
async def _launch_playwright(cmd_args: list[str], ctx_kwargs: dict,
                             headless: bool, user_data_dir: Path,
                             proxy_server: str = ""):
    global _engine_last_error
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        _engine_last_error = f"playwright not installed: {e}"
        raise RuntimeError("playwright is not installed") from e
    launch_kw: dict = {}
    if proxy_server:
        launch_kw["proxy"] = {"server": proxy_server}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch_persistent_context(
        str(user_data_dir),
        headless=headless,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"] + cmd_args,
        **launch_kw,
        **ctx_kwargs,
    )

    async def closer():
        with contextlib.suppress(Exception):
            await browser.close()
        with contextlib.suppress(Exception):
            await pw.stop()

    return closer, browser


# --------------------------------------------------------------------------
# Public entry — all engines return native async contexts.
# --------------------------------------------------------------------------
async def launch_for_account(account_fp: dict, browser_mode: str,
                             profile_key: str | None = None,
                             proxy_server: str = ""):
    """Launch a browser for one account.

    Returns (closer, context, engine_used, fingerprint_json).
    All contexts are native async Playwright objects; flows use run_login_async.
    ``proxy_server`` (scheme://[user:pass@]host:port) routes ALL browser traffic
    through that proxy when non-empty; empty string = direct connection.
    """
    fp = fp_mod.sanitize(account_fp)
    cmd_args = fp_mod.cloak_args(fp)
    ctx_kwargs = fp_mod.context_kwargs(fp)
    headless = browser_mode != "headed"

    key = profile_key or uuid.uuid4().hex
    user_data_dir = config.BROWSER_PROFILES_DIR / key
    user_data_dir.mkdir(parents=True, exist_ok=True)

    cdp_url = (await settings.get("cloak_cdp_url") or "").strip()
    errors: list[str] = []

    # 1) cloakserve remote CDP
    if cdp_url:
        try:
            closer, ctx, engine = await _launch_cloakserve(cdp_url, fp, ctx_kwargs, proxy_server)
            return closer, ctx, engine, json.dumps(fp, ensure_ascii=False)
        except Exception as e:
            errors.append(str(e))

    # 2) cloakbrowser SDK async
    if HAS_CLOAK and HAS_CLOAK_ASYNC:
        try:
            closer, ctx = await _launch_cloak_sdk(cmd_args, ctx_kwargs, headless,
                                                  user_data_dir, proxy_server)
            return closer, ctx, "cloakbrowser", json.dumps(fp, ensure_ascii=False)
        except Exception as e:
            errors.append(str(e))

    # 3) Playwright fallback
    try:
        closer, ctx = await _launch_playwright(cmd_args, ctx_kwargs, headless,
                                               user_data_dir, proxy_server)
        return closer, ctx, "playwright", json.dumps(fp, ensure_ascii=False)
    except Exception as e:
        errors.append(str(e))
        raise RuntimeError("all engines failed: " + " | ".join(errors)) from e


# --------------------------------------------------------------------------
# Managed interactive sessions ("打开浏览器" button)
# --------------------------------------------------------------------------
# Keyed by session key (e.g. "g<group_id>_manual"); one live browser per key.
_MANUAL_SESSIONS: dict[str, dict] = {}
_MANUAL_SEM = asyncio.Semaphore(2)   # bounded concurrent launches


def managed_session_keys() -> list[str]:
    return list(_MANUAL_SESSIONS.keys())


def is_managed_session_open(key: str) -> bool:
    sess = _MANUAL_SESSIONS.get(key)
    return bool(sess and not sess["closer"].done())


async def close_managed_session(key: str) -> bool:
    """Close a managed session; returns True when a live session was closed."""
    sess = _MANUAL_SESSIONS.pop(key, None)
    if not sess:
        return False
    task = sess["closer"]
    if not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        return True
    return False


async def open_managed_browser(fp: dict, browser_mode: str, key: str,
                               proxy_server: str = "") -> dict:
    """Launch (or reuse) a persistent headed browser session for manual use.

    Reuses an existing live session when present (same key), so repeated
    clicks don't spawn duplicate browsers. Never auto-closes: the session
    stays until /close is called or the service shuts down.
    """
    if is_managed_session_open(key):
        return {"ok": True, "reused": True}

    await close_managed_session(key)      # clean up a dead session if any

    async with _MANUAL_SEM:
        closer, ctx, engine, _ = await launch_for_account(
            fp, browser_mode, profile_key=key, proxy_server=proxy_server)

    async def _keep():
        # hold the context open until cancelled; ctx.close() runs on cancel
        try:
            await asyncio.Event().wait()
        finally:
            with contextlib.suppress(Exception):
                await closer()

    _MANUAL_SESSIONS[key] = {"closer": asyncio.create_task(_keep()), "engine": engine}
    return {"ok": True, "reused": False, "engine": engine}


async def close_all_managed_sessions() -> None:
    for key in list(_MANUAL_SESSIONS.keys()):
        with contextlib.suppress(Exception):
            await close_managed_session(key)
