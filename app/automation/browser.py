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
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..core import config, crypto, database, settings
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
_ACTIVE_LOCAL_PROFILES: set[str] = set()


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
    """Probe Chrome version without launching a licensed CDP seat.

    ``/json/version`` starts a seed-backed browser. Check root status first and
    reuse only an already-active seed; return empty when none is running.
    """
    if not cdp_url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            root = (await client.get(cdp_url.rstrip("/"))).json()
            processes = root.get("processes") if isinstance(root.get("processes"), list) else []
            if processes:
                seed = str(processes[0].get("seed") or "").strip()
                if seed:
                    r = await client.get(
                        f"{cdp_url.rstrip('/')}/json/version",
                        params={"fingerprint": seed})
                    data = r.json()
                    browser = str(data.get("Browser") or "")
                    return browser.split("/", 1)[1] if "/" in browser else browser
            # No active browser: do not launch a licensed seat just to show a
            # version. The root probe above already proves cloakserve reachability.
            return ""
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

    Returns the decrypted full proxy server URL from the proxies table.
    """
    pid = account_proxy_id or group_proxy_id
    if not pid:
        return ""
    db = await database.get_db()
    row = await db.execute("SELECT server FROM proxies WHERE id=?", (pid,))
    p = await row.fetchone()
    if not p or not (p["server"] or "").strip():
        return ""
    return crypto.decrypt(p["server"]).strip()


def mask_proxy_server(server: str) -> str:
    """Hide proxy credentials while keeping enough detail to identify it."""
    return re.sub(r"([^/@\s]+:[^/@\s]+)@", "***@", server or "")


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
        url += f"&timezone={quote(str(fp['timezone']), safe='')}"
    if fp.get("locale"):
        url += f"&locale={quote(str(fp['locale']), safe='')}"
    if proxy_server:
        url += f"&proxy={quote(proxy_server, safe='')}"

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(url)
    except Exception as e:
        with contextlib.suppress(Exception):
            await pw.stop()
        _engine_last_error = f"cloakserve connect failed: {e}"
        raise

    # CDP 远程连接不走 SDK 的 launch(humanize=True)，手动打补丁。
    if HAS_CLOAK:
        from cloakbrowser.human import patch_browser_async
        from cloakbrowser.human.config import HumanConfig
        patch_browser_async(browser, HumanConfig())

    context = browser.contexts[0] if browser.contexts else await browser.new_context(**ctx_kwargs)

    async def close_remote():
        # The HTTP close owns the remote fingerprint process. Notify it first so
        # a slow CDP disconnect cannot delay actual browser teardown.
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(f"{base}/fingerprint/{seed}/close")
        with contextlib.suppress(Exception):
            await asyncio.wait_for(browser.close(), 3)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(pw.stop(), 1)

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
    kwargs = dict(headless=headless, args=cmd_args, license_key=license_key,
                  humanize=True)
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
class SessionLimitError(RuntimeError):
    """CloakBrowser plan concurrent-session cap hit (post-handshake kill).

    Raised both when the launch itself is license-killed and (via fpcheck's
    _goto_check_page) when an apparently-healthy context dies before the first
    navigation completes. Callers may auto-reclaim manual session seats on it.
    """


# --------------------------------------------------------------------------
# Plan seat management (CloakBrowser Pro concurrent-session cap)
# --------------------------------------------------------------------------
# The license server counts seats per key; a *gracefully closed* browser frees
# its seat immediately, but a *license-killed* (zombie) seat only expires on
# the server side (~1-2 min TTL, observed). The SDK exposes a seat-count
# endpoint but no revoke, so the strongest force-release we can do locally is:
# gracefully close every CloakBrowser session we own, then poll the server
# until seats free up (bounded wait covering the zombie TTL).
CLOSE_GRACE_SECONDS = 5.0


def _kill_profile_processes(profile_key: str) -> int:
    """Force-kill only the Chromium processes using one managed profile."""
    import os as _os
    import signal
    import subprocess

    profile_path = str(config.BROWSER_PROFILES_DIR / profile_key)
    try:
        out = subprocess.run(
            ["pgrep", "-f", "browser_profiles"], capture_output=True, text=True,
            timeout=2)
        pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except Exception:
        return 0
    killed = 0
    for pid in pids:
        try:
            probe = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                text=True, timeout=2)
            if profile_path not in (probe.stdout or ""):
                continue
            _os.kill(pid, signal.SIGKILL)
            killed += 1
        except Exception:
            continue
    if killed:
        _ACTIVE_LOCAL_PROFILES.discard(profile_key)
    return killed


async def terminate_profile(profile_key: str | None) -> None:
    """Best-effort hard stop for a local profile after graceful close fails."""
    if profile_key:
        await asyncio.to_thread(_kill_profile_processes, profile_key)


async def close_protected(closer, timeout: float = CLOSE_GRACE_SECONDS,
                          profile_key: str | None = None) -> None:
    """Close a browser even when the calling task is being cancelled.

    A graceful close normally finishes quickly. The grace deadline only covers
    a stuck SDK/Playwright close; after it expires, the exact managed profile is
    killed instead of keeping a stop request open indefinitely.
    """
    close_task = asyncio.create_task(closer())
    current = asyncio.current_task()
    caller_cancelled = False
    try:
        await asyncio.wait_for(asyncio.shield(close_task), timeout)
    except TimeoutError:
        await terminate_profile(profile_key)
        close_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await close_task
    except asyncio.CancelledError:
        caller_cancelled = True
        if current is not None:
            current.uncancel()
        try:
            await asyncio.wait_for(asyncio.shield(close_task), timeout)
        except TimeoutError:
            await terminate_profile(profile_key)
            close_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await close_task
        except asyncio.CancelledError:
            pass
    if caller_cancelled:
        raise asyncio.CancelledError


_SEAT_POLL_INTERVAL = 5.0     # s between server seat checks
_SEAT_WAIT_TIMEOUT = 180.0    # s max wait for zombie seats to expire


async def cdp_configured() -> bool:
    """Whether launches must use the explicitly configured remote CDP engine."""
    return bool((await settings.get("cloak_cdp_url") or "").strip())


def _license_key() -> str | None:
    return config.CLOAKBROWSER_LICENSE_KEY or None


def server_seats() -> tuple[int | None, int | None]:
    """(active, limit) from the license server; (None, None) when unknown."""
    if not HAS_CLOAK:
        return None, None
    try:
        from cloakbrowser.license import get_session_seats
        s = get_session_seats(_license_key())
        if s.state == "ok":
            return s.active, s.limit
    except Exception:
        pass
    return None, None


def session_limit_message() -> str:
    active, limit = server_seats()
    cap = f"并发 {limit}" if limit else "并发会话"
    return f"浏览器会话数达到套餐上限（CloakBrowser {cap}），请先关闭已打开的指纹浏览器窗口再试"


async def force_free_seats(timeout: float = _SEAT_WAIT_TIMEOUT) -> bool:
    """Best-effort force-release of plan seats before an important launch.

    1. close every managed session we hold (graceful close frees its seat at
       once);
    2. kill any leftover CloakBrowser Chromium processes from earlier crashes
       (they hold seats until the server TTL expires — killing them starts the
       TTL clock now rather than later, and an OS-level dead process is
       reaped by the server promptly);
    3. poll the license server until active < limit or timeout.

    Returns True when a seat is (very likely) free.
    """
    if await cdp_configured():
        # This check uses the app's local SDK key, while the CDP server owns
        # the actual license/seat state. Never make CDP wait on that proxy.
        return True

    await close_all_managed_sessions()
    protected_profiles = {
        str(config.BROWSER_PROFILES_DIR / key) for key in _ACTIVE_LOCAL_PROFILES
    }
    await asyncio.to_thread(_kill_leftover_cloak_processes, protected_profiles)

    active, limit = await asyncio.to_thread(server_seats)
    if active is None or limit is None:
        return True          # server unreachable: don't block, let launch try
    waited = 0.0
    while active >= limit and waited < timeout:
        await asyncio.sleep(_SEAT_POLL_INTERVAL)
        waited += _SEAT_POLL_INTERVAL
        active, limit = await asyncio.to_thread(server_seats)
        if active is None:
            return True
    return active is not None and active < limit


# One-at-a-time seat acquisition: with limit=1 plans two concurrent "get a
# seat" flows would otherwise fight over the same seat.
_seat_gate = asyncio.Lock()


async def acquire_seat(timeout: float = _SEAT_WAIT_TIMEOUT) -> None:
    """Pre-flight seat guard for local CloakBrowser launches.

    Local SDK seats are counted per key and freed by TTL — there is no revoke
    API (probed: release/revoke/close all 404). So the strategy is:
    if the server reports a full house, clean everything we own and WAIT for
    the TTL to release zombie seats, instead of launching into a guaranteed
    license kill. Serializes concurrent acquirers via a module lock.
    """
    if await cdp_configured():
        # cloakserve owns licensing for CDP and fails a truly full launch fast;
        # a stale/remote SDK seat count must not block fingerprint checks.
        return

    async with _seat_gate:
        active, limit = await asyncio.to_thread(server_seats)
        if active is None or limit is None or active < limit:
            return                      # seat available (or unknown): go
        # Full house: release what we can, then wait for the server TTL.
        freed = await force_free_seats(timeout)
        if not freed:
            raise SessionLimitError(session_limit_message())


def _kill_leftover_cloak_processes(protected_profiles: set[str] | None = None) -> int:
    """SIGKILL CloakBrowser Chromium processes from crashed sessions.

    Matches the project's browser_profiles dir in the command line so we never
    touch the user's own Chrome. Returns how many processes were signalled.
    """
    import os as _os
    import signal
    import subprocess
    import time as _time

    profiles_root = str(config.BROWSER_PROFILES_DIR)
    protected_profiles = protected_profiles or set()
    killed = 0
    try:
        out = subprocess.run(
            ["pgrep", "-f", "browser_profiles"], capture_output=True, text=True,
            timeout=5)
        pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except Exception:
        return 0
    for pid in pids:
        try:
            probe = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                text=True, timeout=5)
            cmd = probe.stdout or ""
        except Exception:
            continue
        if profiles_root in cmd and not any(path in cmd for path in protected_profiles):
            with contextlib.suppress(Exception):
                _os.kill(pid, signal.SIGKILL)
                killed += 1
    if killed:
        # give the OS a moment to reap so the license server sees them gone
        _time.sleep(1.0)
    return killed


async def launch_for_account(account_fp: dict, browser_mode: str,
                             profile_key: str | None = None,
                             proxy_server: str = ""):
    """Launch a browser for one account.

    Returns (closer, context, engine_used, fingerprint_json).
    All contexts are native async Playwright objects; flows expose async run_* methods.
    ``proxy_server`` (scheme://[user:pass@]host:port) routes ALL browser traffic
    through that proxy when non-empty; empty string = direct connection.
    """
    fp = fp_mod.sanitize(account_fp)
    cmd_args = fp_mod.cloak_args(fp)
    ctx_kwargs = fp_mod.context_kwargs(fp)
    headless = browser_mode != "headed"

    key = profile_key or uuid.uuid4().hex
    cdp_url = (await settings.get("cloak_cdp_url") or "").strip()
    errors: list[str] = []

    # CloakBrowser Pro caps concurrent sessions per plan. An over-cap launch can
    # complete the CDP handshake and THEN be killed by the license guard — the
    # context looks alive but its pages are gone, and the next navigation fails
    # with an opaque "Target page has been closed". Detect it here and fail fast
    # with a clear message instead of letting callers misdiagnose it (e.g. as a
    # proxy outage).
    def _ctx_is_alive(context) -> bool:
        pages = getattr(context, "pages", None)
        return bool(pages)

    def _wrap_closer(raw_closer, profile_key: str):
        async def closer():
            _ACTIVE_LOCAL_PROFILES.discard(profile_key)
            await raw_closer()
        return closer

    # 1) cloakserve remote CDP
    if cdp_url:
        try:
            closer, ctx, engine = await _launch_cloakserve(cdp_url, fp, ctx_kwargs, proxy_server)
            if not _ctx_is_alive(ctx):
                # A remote license kill can leave the CDP handshake successful
                # but return an empty context; avoid treating it as usable.
                with contextlib.suppress(Exception):
                    await closer()
                raise SessionLimitError(session_limit_message())
            closer = _wrap_closer(closer, key)
            _ACTIVE_LOCAL_PROFILES.add(key)
            return closer, ctx, engine, json.dumps(fp, ensure_ascii=False)
        except SessionLimitError:
            raise
        except Exception as e:
            # CDP is an explicit deployment choice. Falling back to local SDK
            # would consume another plan seat and ignore remote headed mode.
            detail = _engine_last_error or str(e)
            raise RuntimeError(f"CloakBrowser CDP 启动失败: {detail}") from e

    key = profile_key or uuid.uuid4().hex
    user_data_dir = config.BROWSER_PROFILES_DIR / key
    user_data_dir.mkdir(parents=True, exist_ok=True)

    # Local engines are only available when no CDP endpoint is configured.
    try:
        if HAS_CLOAK and HAS_CLOAK_ASYNC:
            closer, ctx = await _launch_cloak_sdk(cmd_args, ctx_kwargs, headless,
                                                  user_data_dir, proxy_server)
            if not _ctx_is_alive(ctx):
                # post-handshake license kill: give the guard a beat, then re-check
                await asyncio.sleep(1.0)
                if not _ctx_is_alive(ctx):
                    with contextlib.suppress(Exception):
                        await closer()
                    raise SessionLimitError(
                        "CloakBrowser 会话被关闭（疑似套餐并发会话数已达上限），"
                        "请关闭其他指纹浏览器窗口后重试")
            closer = _wrap_closer(closer, key)
            _ACTIVE_LOCAL_PROFILES.add(key)
            return closer, ctx, "cloakbrowser", json.dumps(fp, ensure_ascii=False)
    except SessionLimitError:
        raise
    except Exception as e:
        errors.append(str(e))

    # Playwright fallback is still limited to explicit local mode.
    try:
        closer, ctx = await _launch_playwright(cmd_args, ctx_kwargs, headless,
                                               user_data_dir, proxy_server)
        closer = _wrap_closer(closer, key)
        _ACTIVE_LOCAL_PROFILES.add(key)
        return closer, ctx, "playwright", json.dumps(fp, ensure_ascii=False)
    except Exception as e:
        errors.append(str(e))
        raise RuntimeError("all engines failed: " + " | ".join(errors)) from e


async def reclaim_manual_sessions() -> int:
    """Close every live managed ("打开浏览器") session; returns how many died.

    Also drops finished registrations. Used by launch_with_autocleanup and
    fpcheck to free plan seats automatically before a retry.
    """
    closed = 0
    for k in list(_MANUAL_SESSIONS):
        if not _MANUAL_SESSIONS[k]["closer"].done():
            with contextlib.suppress(Exception):
                if await close_managed_session(k):
                    closed += 1
        else:
            _MANUAL_SESSIONS.pop(k, None)
    return closed


async def launch_with_autocleanup(account_fp: dict, browser_mode: str,
                                  profile_key: str | None = None,
                                  proxy_server: str = ""):
    """launch_for_account + automatic local-seat recovery.

    CDP delegates licensing to cloakserve, so it neither waits on the app's
    SDK seat count nor runs the local force-free/retry path.
    """
    remote_cdp = await cdp_configured()
    if not remote_cdp:
        await acquire_seat()
    try:
        return await launch_for_account(account_fp, browser_mode,
                                        profile_key=profile_key,
                                        proxy_server=proxy_server)
    except SessionLimitError:
        if remote_cdp:
            raise
        if not await force_free_seats():
            raise SessionLimitError(session_limit_message())
        return await launch_for_account(account_fp, browser_mode,
                                        profile_key=profile_key,
                                        proxy_server=proxy_server)


# --------------------------------------------------------------------------
# Managed interactive sessions ("打开浏览器" button)
# --------------------------------------------------------------------------
# Keyed by session key (e.g. "g<group_id>_manual"); one live browser per key.
_MANUAL_SESSIONS: dict[str, dict] = {}
_MANUAL_SEM = asyncio.Semaphore(2)   # bounded concurrent launches
_TASK_CONTEXTS: dict[str, dict] = {}


def managed_session_keys() -> list[str]:
    return list(_MANUAL_SESSIONS.keys())


def get_first_managed_page():
    """Return the first Page from any active managed session, or None."""
    for sess in _MANUAL_SESSIONS.values():
        if sess.get("closer") and not sess["closer"].done():
            ctx = sess.get("ctx")
            if ctx and getattr(ctx, "pages", None):
                return ctx.pages[0]
    return None


def register_task_context(key: str, closer, ctx):
    """Expose a task-owned context for diagnostics without making it manual."""
    async def _wrapped_close():
        sess = _TASK_CONTEXTS.get(key)
        if sess and sess.get("closed"):
            return
        if sess:
            sess["closed"] = True
        _TASK_CONTEXTS.pop(key, None)
        await closer()

    _TASK_CONTEXTS[key] = {"closer": _wrapped_close, "ctx": ctx, "closed": False}
    return _wrapped_close


def get_first_task_page():
    """Return the first Page from a live account-task context, or None."""
    for sess in list(_TASK_CONTEXTS.values()):
        if not sess.get("closed"):
            ctx = sess.get("ctx")
            if ctx and getattr(ctx, "pages", None):
                return ctx.pages[0]
    return None


def is_managed_session_open(key: str) -> bool:
    sess = _MANUAL_SESSIONS.get(key)
    # A closed browser can leave the holder task alive briefly; expose only
    # sessions whose Playwright context still has pages.
    return bool(sess and not sess["closer"].done() and _session_ctx_healthy(sess))


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


def _session_ctx_healthy(sess: dict) -> bool:
    """A registered manual session is only 'open' if its browser really is.

    The license guard can kill the browser post-handshake while the _keep()
    task is still awaiting — that registration is a zombie seat.
    """
    ctx = sess.get("ctx")
    return bool(ctx is not None and getattr(ctx, "pages", None))


async def open_managed_browser(fp: dict, browser_mode: str, key: str,
                               proxy_server: str = "") -> dict:
    """Launch (or reuse) a persistent headed browser session for manual use.

    Reuses an existing live session when present (same key), so repeated
    clicks don't spawn duplicate browsers. When another manual session holds
    the plan's last seat — or a same-key zombie exists — it is closed
    automatically so the new window opens without manual cleanup.
    """
    if is_managed_session_open(key):
        return {"ok": True, "reused": True}

    # Pre-flight: if the plan's seats are full (our own manual window counts),
    # acquire_seat() auto-cleans and waits instead of launching into a kill.
    await acquire_seat()

    # Not reusable: clear every registration — same-key zombies, license-killed
    # seats, and healthy older windows (evicted: the plan caps sessions, and a
    # silently killed second browser is worse than closing the replaced one).
    for k in list(_MANUAL_SESSIONS):
        if not _MANUAL_SESSIONS[k]["closer"].done():
            with contextlib.suppress(Exception):
                await close_managed_session(k)
        else:
            _MANUAL_SESSIONS.pop(k, None)

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

    _MANUAL_SESSIONS[key] = {"closer": asyncio.create_task(_keep()),
                             "engine": engine, "ctx": ctx}
    return {"ok": True, "reused": False, "engine": engine}


async def close_all_managed_sessions() -> None:
    for key in list(_MANUAL_SESSIONS.keys()):
        with contextlib.suppress(Exception):
            await close_managed_session(key)
