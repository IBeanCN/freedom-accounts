"""Fingerprint risk check: drive the fuck-claude.com style check site with the
account's own fingerprint browser, then read the risk badge + score.

Flow (per run, on a launched browser context):
  1. resolve the check URL (group override > system setting); if neither is
     configured, abort with a prompt instead of guessing a default
  2. goto the check URL
  2. wait for load, then click `button#retest` to (re)trigger detection
  3. poll `span#risk-badge` until its text is no longer a "checking" state
  4. read `span#risk-badge` (risk label) and `span#score-value` (score)
  5. persist `"{risk}/{score}"` to accounts.fp_check_result

The check runs in the background (asyncio task); the API only enqueues it and
reports current status. Concurrency is bounded by a module-level semaphore.
"""
import asyncio
import contextlib

from ..core import config, database, settings
from ..core import tasks
from . import browser as browser_mod

# "检测中" is the site's in-progress marker; anything else means finished.
CHECKING_MARKS = {"检测中", "检测中…", "检测中...", "checking"}
POLL_INTERVAL = 1.0      # seconds between badge polls
LOAD_TIMEOUT = 30_000    # ms — page goto timeout
DETECT_TIMEOUT = 120     # s — max wait for the badge to leave 检测中

# both the group override and the system setting are empty => refuse to run
NO_URL_MSG = "未配置指纹检测地址，请先在「系统设置 → 指纹检测站点」填写，或在分组编辑中单独配置"

# CloakBrowser Pro plan caps concurrent live sessions; an over-cap launch may
# complete the CDP handshake and THEN be killed by the license guard (exit 76),
# which surfaces downstream as a bare "Target page has been closed" — easy to
# misread as a proxy failure. Detect and report the real cause (dynamic plan
# cap comes from the license server when reachable).
def _session_limit_msg() -> str:
    try:
        return browser_mod.session_limit_message()
    except Exception:
        return ("浏览器会话数达到套餐上限（CloakBrowser 计划并发），"
                "请先关闭已打开的指纹浏览器窗口再检测")


_TARGET_CLOSED_MARKS = (
    "Target page has been closed", "Target closed", "target crashed",
    "Browser has been closed", "Session closed",
)


def _is_session_killed(msg: str) -> bool:
    """Heuristic: the launch succeeded but the browser died before navigation."""
    m = (msg or "").lower()
    if "session limit" in m or "exitcode=76" in m:
        return True
    return any(mark.lower() in m for mark in _TARGET_CLOSED_MARKS)

_sem = asyncio.Semaphore(1)   # CloakBrowser plan caps live sessions; keep 1 seat spare for manual browser


async def resolve_check_url(group_row: dict | None) -> str | None:
    """Check URL priority: group override > system setting.

    Returns None when neither is configured — callers must prompt the user
    instead of silently falling back to a builtin default.
    """
    if group_row is not None:
        override = (group_row["fp_check_url"] or "").strip() \
            if "fp_check_url" in group_row.keys() else ""
        if override:
            return override
    stored = (await settings.get("fp_check_url") or "").strip()
    return stored or None


async def account_check_url(account_id: int) -> str | None:
    """Resolve the check URL for one account (via its group override > setting)."""
    db = await database.get_db()
    g = await (await db.execute(
        "SELECT * FROM groups WHERE id=(SELECT group_id FROM accounts WHERE id=?)",
        (account_id,))).fetchone()
    return await resolve_check_url(g)


async def set_checking(account_id: int) -> None:
    db = await database.get_db()
    await db.execute(
        "UPDATE accounts SET fp_check_result='检测中', fp_check_at="
        "datetime('now','localtime') WHERE id=?", (account_id,))
    await db.commit()


async def save_result(account_id: int, result: str) -> None:
    db = await database.get_db()
    await db.execute(
        "UPDATE accounts SET fp_check_result=?, fp_check_at="
        "datetime('now','localtime') WHERE id=?", (result[:100], account_id))
    await db.commit()


async def _goto_check_page(page, url: str, proxy_server: str) -> None:
    """goto the check URL; failures through a proxy get an actionable message.

    检测必须经由账号/分组代理执行（直连的结果对指纹无意义），所以代理不可达时
    明确报出代理地址，而不是抛 Playwright 原始堆栈。
    例外：页面/浏览器已被关闭（CloakBrowser 套餐会话数超限静默杀进程）时，
    报会话上限而不是误报代理——此时代理是无辜的。
    """
    try:
        await page.goto(url, timeout=LOAD_TIMEOUT, wait_until="domcontentloaded")
    except Exception as e:
        msg = str(e)
        if _is_session_killed(msg):
            # 抛 SessionLimitError：调用方（run_check/run_group_check）会自动
            # 清掉占座的手动浏览器窗口并整体重试一次。
            raise browser_mod.SessionLimitError(_session_limit_msg()) from e
        if proxy_server:
            hostport = proxy_server.rsplit("@", 1)[-1]   # mask credentials
            raise RuntimeError(
                f"检测站打开失败（经由代理 {hostport}，代理可能不可用或无法访问检测站）") from e
        raise RuntimeError(f"检测站打开失败: {e}") from e


async def _click_retest(page) -> None:
    """Click button#retest; tolerate pages where it appears a bit late."""
    btn = page.locator("button#retest")
    try:
        await btn.wait_for(state="visible", timeout=10_000)
        await btn.click()
    except Exception as e:
        raise RuntimeError(f"未找到 retest 按钮（页面结构可能已变化）: {e}") from e


async def _read_badge(page) -> tuple[str, str]:
    """Poll #risk-badge until done; return '{risk}/{score}'."""
    badge = page.locator("span#risk-badge")
    await badge.wait_for(state="visible", timeout=LOAD_TIMEOUT)

    waited = 0.0
    while waited < DETECT_TIMEOUT:
        text = ((await badge.text_content()) or "").strip()
        if text and text not in CHECKING_MARKS:
            score_raw = ""
            with contextlib.suppress(Exception):
                score_raw = ((await page.locator("span#score-value")
                              .text_content()) or "").strip()
            score = score_raw or "-"
            return f"{text}/{score}"
        await asyncio.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
    raise RuntimeError("等待检测结果超时（risk-badge 一直处于检测中）")


async def _run_check_once(a, g, url: str, mode: str) -> tuple[bool, dict]:
    """One attempt: launch -> goto -> detect -> read. Returns (ok, payload)."""
    import json
    account_id = a["id"]
    async with _sem:
        closer = None
        try:
            proxy_server = await browser_mod.resolve_proxy(
                a["proxy_id"] if "proxy_id" in a.keys() else None,
                g["proxy_id"] if "proxy_id" in g.keys() else None)
            closer, ctx, engine, _ = await browser_mod.launch_with_autocleanup(
                json.loads(a["fingerprint"] or "{}"), mode,
                profile_key=f"g{a['group_id']}_a{account_id}_fpcheck",
                proxy_server=proxy_server)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await _goto_check_page(page, url, proxy_server)
            await _click_retest(page)
            result = await _read_badge(page)
            await save_result(account_id, result)
            return True, {"ok": True, "result": result, "engine": engine}
        except Exception as e:
            await save_result(account_id, f"失败: {str(e)[:80]}")
            return False, {"ok": False, "error": str(e)}
        finally:
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer()


async def run_check(account_id: int) -> dict:
    """Full check for one account; runs as a background task.

    On SessionLimitError (browser killed by the plan's concurrent-session cap —
    typically a manual "打开浏览器" window holding a seat), reclaim those seats
    automatically and retry once instead of asking the user to close windows.
    """
    db = await database.get_db()
    a = await (await db.execute("SELECT * FROM accounts WHERE id=?", (account_id,))).fetchone()
    if not a:
        return {"ok": False, "error": "account not found"}
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (a["group_id"],))).fetchone()
    if not g:
        return {"ok": False, "error": "group not found"}
    url = await resolve_check_url(g)
    if not url:
        await save_result(account_id, f"失败: {NO_URL_MSG}")
        return {"ok": False, "error": NO_URL_MSG}

    await set_checking(account_id)
    mode = await browser_mod.resolve_browser_mode(a["browser_mode"], g["browser_mode"])

    ok, payload = await _run_check_once(a, g, url, mode)
    if not ok and _is_session_killed(payload.get("error", "")):
        await browser_mod.reclaim_manual_sessions()
        ok, payload = await _run_check_once(a, g, url, mode)
    return payload


def start_check(account_id: int) -> asyncio.Task:
    """Fire-and-forget background check (used by the API endpoint)."""
    return tasks.spawn(run_check(account_id))


# ---------------- group template check ----------------
# 需求：分组检测不是批量检测账号，而是验证分组配置的公共指纹模板是否可用。
# 做法：从模板生成一套代表性指纹（模板字段 + 随机 seed，即新账号实际拿到的
# 指纹形态），用它启动浏览器跑一次检测站，结果写回 groups.fp_check_result。

async def set_group_checking(group_id: int) -> None:
    db = await database.get_db()
    await db.execute(
        "UPDATE groups SET fp_check_result='检测中', fp_check_at="
        "datetime('now','localtime') WHERE id=?", (group_id,))
    await db.commit()


async def save_group_result(group_id: int, result: str) -> None:
    db = await database.get_db()
    await db.execute(
        "UPDATE groups SET fp_check_result=?, fp_check_at="
        "datetime('now','localtime') WHERE id=?", (result[:100], group_id))
    await db.commit()


async def _run_group_check_once(g, url: str, fp: dict, mode: str) -> tuple[bool, dict]:
    """One attempt for the group template check."""
    group_id = g["id"]
    async with _sem:
        closer = None
        try:
            proxy_server = await browser_mod.resolve_proxy(
                None, g["proxy_id"] if "proxy_id" in g.keys() else None)
            closer, ctx, engine, _ = await browser_mod.launch_with_autocleanup(
                fp, mode, profile_key=f"g{group_id}_tplcheck",
                proxy_server=proxy_server)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await _goto_check_page(page, url, proxy_server)
            await _click_retest(page)
            result = await _read_badge(page)
            await save_group_result(group_id, result)
            return True, {"ok": True, "result": result, "engine": engine}
        except Exception as e:
            await save_group_result(group_id, f"失败: {str(e)[:80]}")
            return False, {"ok": False, "error": str(e)}
        finally:
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer()


async def run_group_check(group_id: int) -> dict:
    """Check the group's fingerprint template with one representative fingerprint.

    Auto-reclaims manual session seats and retries once on SessionLimitError
    (same self-healing as run_check).
    """
    from . import fingerprint as fp_mod

    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        return {"ok": False, "error": "group not found"}
    url = await resolve_check_url(g)
    if not url:
        await save_group_result(group_id, f"失败: {NO_URL_MSG}")
        return {"ok": False, "error": NO_URL_MSG}

    template = g["fingerprint_template"] if "fingerprint_template" in g.keys() else "{}"
    tpl = fp_mod.sanitize(template)
    if not tpl:
        return {"ok": False, "error": "分组未配置指纹模板"}
    # representative fingerprint: exactly what a new account would receive
    fp = fp_mod.generate_from_template(tpl)

    await set_group_checking(group_id)
    mode = await browser_mod.resolve_browser_mode("inherit", g["browser_mode"])

    ok, payload = await _run_group_check_once(g, url, fp, mode)
    if not ok and _is_session_killed(payload.get("error", "")):
        await browser_mod.reclaim_manual_sessions()
        ok, payload = await _run_group_check_once(g, url, fp, mode)
    return payload


def start_group_check(group_id: int) -> dict:
    """Fire-and-forget template check (used by the API endpoint)."""
    tasks.spawn(run_group_check(group_id))
    return {"ok": True, "group_id": group_id}
