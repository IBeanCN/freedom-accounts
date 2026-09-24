"""Task scheduler & executor: per-group dispatch queue, group concurrency cap,
random inter-account interval.

Design:
  - one dispatcher task per group (spawned on demand), pulls account ids from
    an asyncio.Queue and waits [interval_min, interval_max] (random) between
    consecutive dispatches;
  - a group-level asyncio.Semaphore(group.concurrency) bounds simultaneous
    browser runs; queued tasks wait on the semaphore;
  - each run: create task row -> launch browser -> run login flow -> persist
    result. Upstream integration is internal to the selected flow adapter.
"""
import asyncio
import json
import random
import time
from datetime import datetime

from ..core import config, database, settings
from ..core import crypto
from . import browser as browser_mod
from . import flows
from .flows.adapters._openai_browser import redact_callback_url
from .flows.adapters._phone_verification import (
    PhoneVerificationTerminalError,
    provider_phone_verification,
)
from .phone import get_phone_adapter

_groups: dict[int, dict] = {}   # group_id -> {"queue": Queue, "dispatcher": Task, "sem": Semaphore}
_lock = asyncio.Lock()
_account_slots: set[int] = set()
_running_accounts: set[int] = set()
_account_state_lock = asyncio.Lock()
_RUN_TASKS: set[asyncio.Task] = set()
_RUN_TASK_BY_ACCOUNT: dict[int, asyncio.Task] = {}
_EXECUTE_TASK_BY_ACCOUNT: dict[int, asyncio.Task] = {}
_EXECUTE_LAUNCHING: set[int] = set()
# Queue entries carry a generation so a stopped stale item can never execute
# after the same account is immediately queued again.
_account_generations: dict[int, int] = {}
# Stop marks let an ID already inside an asyncio.Queue drain lazily and give
# the executor one deterministic cancellation boundary.
_stop_requests: set[int] = set()
# After a run's browser closes and result is persisted, keep its group slot
# reserved briefly so the next queued account never reuses it immediately.
RUN_COOLDOWN_MIN_SECONDS = 15.0
RUN_COOLDOWN_MAX_SECONDS = 30.0


class RunStopped(Exception):
    """Internal signal: a cancelled login run has been persisted and cleaned up."""


class TaskStepLog(list):
    """A step list whose appends are mirrored into ``tasks.steps`` immediately.

    Flow helpers receive a plain mutable list and call ``append`` synchronously.
    A single writer task serializes those appends onto the task's SQLite row,
    so any process can read the current step without a whole-run snapshot.
    """

    def __init__(self, db=None, task_id: int | None = None) -> None:
        super().__init__()
        self._db = db
        self._task_id = task_id
        self._dirty = asyncio.Event()
        self._writer: asyncio.Task | None = None
        self._closed = False

    def bind(self, db, task_id: int) -> None:
        self._db = db
        self._task_id = task_id
        self._mark_dirty()

    def append(self, value) -> None:
        super().append(value)
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        if self._closed or self._db is None or self._task_id is None:
            return
        if self._writer is None or self._writer.done():
            self._writer = asyncio.create_task(self._write_loop())
        self._dirty.set()

    async def _write(self) -> None:
        await self._db.execute(
            "UPDATE tasks SET steps=? WHERE id=?",
            (json.dumps(self, ensure_ascii=False), self._task_id))
        await self._db.commit()

    async def _write_loop(self) -> None:
        try:
            while True:
                await self._dirty.wait()
                self._dirty.clear()
                await self._write()
                if not self._dirty.is_set():
                    return
        finally:
            if self._writer is asyncio.current_task():
                self._writer = None

    async def flush(self) -> None:
        """Wait until every append made so far is visible in ``tasks.steps``."""
        if self._closed or self._db is None or self._task_id is None:
            return
        self._dirty.set()
        if self._writer is not None:
            await self._writer
        else:
            await self._write()

    async def close(self) -> None:
        await self.flush()
        self._closed = True


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def enqueue(group_id: int, account_ids: list[int]) -> int:
    """Queue each account once; queued/running accounts cannot be duplicated."""
    db = await database.get_db()
    async with _lock:
        g = _groups.get(group_id)
        if g is None:
            g = {"queue": asyncio.Queue(), "sem": None}
            _groups[group_id] = g
            g["dispatcher"] = asyncio.create_task(_dispatcher(group_id, g))
        queued: list[int] = []
        for aid in account_ids:
            if aid in _account_slots or aid in _running_accounts:
                continue
            _stop_requests.discard(aid)
            _account_slots.add(aid)
            generation = _account_generations.get(aid, 0) + 1
            _account_generations[aid] = generation
            queued.append(aid)
            await g["queue"].put((aid, generation))
    if queued:
        # 入队即对外可见，防止前端在任务真正启动前重复提交。
        marks = ",".join("?" * len(queued))
        await db.execute(
            f"""UPDATE accounts SET last_status='queued', last_message='任务队列中'
                WHERE id IN ({marks})""", tuple(queued))
        await db.commit()
        return len(queued)
    return 0


async def _mark_cancelled(db, account_ids: list[int]) -> None:
    if not account_ids:
        return
    marks = ",".join("?" * len(account_ids))
    await db.execute(
        f"""UPDATE accounts SET last_status='cancelled', last_message='已手动停止',
            last_task_id=NULL WHERE id IN ({marks})""",
        tuple(account_ids))
    await db.commit()


async def _dispatcher(group_id: int, g: dict) -> None:
    db = await database.get_db()
    while True:
        account_id, generation = await g["queue"].get()
        if generation != _account_generations.get(account_id):
            continue
        if account_id in _stop_requests:
            async with _account_state_lock:
                _account_slots.discard(account_id)
            await _mark_cancelled(db, [account_id])
            continue

        # read current interval config every dispatch (live-updatable)
        row = await db.execute(
            "SELECT concurrency, interval_min_ms, interval_max_ms FROM groups WHERE id=?",
            (group_id,))
        gr = await row.fetchone()
        if gr is None:          # group deleted
            async with _account_state_lock:
                _account_slots.discard(account_id)
            # drain remaining queued accounts and release their slots
            while not g["queue"].empty():
                try:
                    remaining, remaining_generation = g["queue"].get_nowait()
                    if remaining_generation != _account_generations.get(remaining):
                        continue
                    async with _account_state_lock:
                        _account_slots.discard(remaining)
                except asyncio.QueueEmpty:
                    break
            break
        conc = max(1, min(int(gr["concurrency"] or 1), config.MAX_CONCURRENCY_PER_GROUP))
        if g["sem"] is None or g.get("sem_concurrency") != conc:
            g["sem"] = asyncio.Semaphore(conc)
            g["sem_concurrency"] = conc
        sem = g["sem"]

        lo = max(int(gr["interval_min_ms"] or 0), config.INTERVAL_MIN_MS) / 1000.0
        hi = max(int(gr["interval_max_ms"] or 0), lo) / 1000.0
        if g.get("last_dispatch") is not None:
            await asyncio.sleep(random.uniform(lo, hi))
            if account_id in _stop_requests:
                async with _account_state_lock:
                    _account_slots.discard(account_id)
                await _mark_cancelled(db, [account_id])
                continue
        g["last_dispatch"] = time.monotonic()

        task = asyncio.create_task(_run_one(group_id, account_id, sem))
        _RUN_TASKS.add(task)
        task.add_done_callback(_RUN_TASKS.discard)


async def _run_one(group_id: int, account_id: int, sem: asyncio.Semaphore) -> None:
    task = asyncio.current_task()
    async with _account_state_lock:
        if account_id in _running_accounts:
            return
        _running_accounts.add(account_id)
        if task is not None:
            _RUN_TASK_BY_ACCOUNT[account_id] = task
    try:
        db = await database.get_db()
        g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
        a = await (await db.execute("SELECT * FROM accounts WHERE id=?", (account_id,))).fetchone()
        if not g or not a:
            if account_id in _stop_requests:
                await _mark_cancelled(db, [account_id])
            return

        # decrypt sensitive credentials for the flow (they are encrypted at rest)
        password = crypto.decrypt(a["password"]) if a["password"] else ""
        totp_secret = crypto.decrypt(a["totp_secret"]) if a["totp_secret"] else ""

        # decrypt the group's upstream key for adapters
        group_row = dict(g)
        if group_row.get("upstream_key"):
            group_row["upstream_key"] = crypto.decrypt(group_row["upstream_key"])

        async with sem:
            execute_task = asyncio.create_task(
                _execute(db, g, a, password=password, totp_secret=totp_secret,
                         group_decrypted=group_row))
            async with _account_state_lock:
                _EXECUTE_TASK_BY_ACCOUNT[account_id] = execute_task
            try:
                await asyncio.shield(execute_task)
            except RunStopped:
                return
            except asyncio.CancelledError:
                execute_task.cancel()
                try:
                    await execute_task
                except asyncio.CancelledError:
                    pass
                return
            # Hold the semaphore while cooling down, so the next queued task
            # cannot acquire this group's concurrency slot as soon as it ends.
            try:
                await asyncio.sleep(random.uniform(
                    RUN_COOLDOWN_MIN_SECONDS, RUN_COOLDOWN_MAX_SECONDS))
            except asyncio.CancelledError:
                return
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        # Cancellation before the executor starts must still clear queue state;
        # app shutdown does not set a stop mark and keeps the existing restart reset.
        if account_id in _stop_requests:
            db = await database.get_db()
            await _mark_cancelled(db, [account_id])
        return
    finally:
        async with _account_state_lock:
            _account_slots.discard(account_id)
            _running_accounts.discard(account_id)
            if _RUN_TASK_BY_ACCOUNT.get(account_id) is task:
                _RUN_TASK_BY_ACCOUNT.pop(account_id, None)
            _EXECUTE_TASK_BY_ACCOUNT.pop(account_id, None)


async def _close_protected(closer) -> None:
    """Close a browser even when the calling task is being cancelled.

    A plain await in a cancellation finally can itself raise immediately and
    leave the fingerprint-browser session open.
    """
    close_task = asyncio.create_task(closer())
    current = asyncio.current_task()
    try:
        await asyncio.shield(close_task)
    except asyncio.CancelledError:
        if current is not None:
            current.uncancel()
        try:
            await close_task
        except asyncio.CancelledError:
            pass
        # Do not re-raise CancelledError: its pending delivery can interrupt the
        # result persistence below. RunStopped is the executor's safe boundary.
        raise RunStopped from None


async def _resolve_phone_handler(steps: list, g, a):
    """Build the optional phone provider; any missing config falls back to manual.

    Platform priority: account.phone_platform > group.phone_platform > system setting.
    API key and country stay in system settings (shared across platforms).
    """
    mode = (await settings.get("phone_verification_mode") or "manual").strip()
    if mode != "auto":
        return None
    ac_val = a["phone_platform"] if "phone_platform" in a.keys() else ""
    g_val = g["phone_platform"] if "phone_platform" in g.keys() else ""
    platform = (ac_val if ac_val and ac_val != "inherit" else "") \
        or (g_val if g_val and g_val != "inherit" else "") \
        or (await settings.get("phone_verification_platform") or "").strip()
    country = (await settings.get("phone_verification_country") or "").strip()
    page_country = (await settings.get("phone_verification_page_country") or "").strip()
    encrypted_key = await settings.get("phone_verification_api_key") or ""
    api_key = crypto.decrypt(encrypted_key).strip() if encrypted_key else ""
    try:
        adapter = get_phone_adapter(platform)()
    except ValueError:
        adapter = None
    if adapter is None or not country or not api_key or not page_country:
        steps.append({
            "t": _now(), "step": "phone_verification_fallback",
            "detail": "自动接码配置不完整或平台不支持，回退手动手机号验证", "ok": False,
        })
        return None

    async def handler(page, email: str, handler_steps: list) -> None:
        await provider_phone_verification(
            page, email, handler_steps, adapter=adapter,
            api_key=api_key, country=country, page_country=page_country)

    steps.append({
        "t": _now(), "step": "phone_verification_auto",
        "detail": f"自动接码已启用：{adapter.label}", "ok": True,
    })
    return handler


async def _execute(db, g, a, *, password: str = "", totp_secret: str = "",
                   group_decrypted: dict | None = None) -> None:
    group_id, account_id = g["id"], a["id"]
    task_id = None
    started_at = _now()
    steps = TaskStepLog()
    status, error, result_json, fp_json, mode = "failed", "", {}, "{}", ""
    engine_used = browser_mod.engine_name()
    closer = None
    try:
        cur = await db.execute(
            """INSERT INTO tasks(group_id,account_id,status,created_at,started_at)
               VALUES(?,?, 'running', ?, ?)""",
            (group_id, account_id, started_at, started_at))
        task_id = cur.lastrowid
        steps.bind(db, task_id)
        steps.append({"t": _now(), "step": "task_created", "detail": f"task#{task_id}", "ok": True})
        await db.execute(
            "UPDATE accounts SET last_status='running', last_task_id=?, last_run_at=? WHERE id=?",
            (task_id, started_at, account_id))
        await db.commit()

        mode = await browser_mod.resolve_browser_mode(a["browser_mode"], g["browser_mode"])
        steps.append({"t": _now(), "step": "browser_mode", "detail": mode, "ok": True})
        steps.append({"t": _now(), "step": "fingerprint", "detail": "applied", "ok": True})

        fp_raw = a["fingerprint"] or "{}"
        fp = json.loads(fp_raw) if isinstance(fp_raw, str) else fp_raw
        # proxy priority: account > group (empty on both -> direct connection)
        proxy_server = await browser_mod.resolve_proxy(
            a["proxy_id"] if "proxy_id" in a.keys() else None,
            g["proxy_id"] if "proxy_id" in g.keys() else None)
        if proxy_server:
            steps.append({
                "t": _now(), "step": "proxy",
                "detail": browser_mod.mask_proxy_server(proxy_server), "ok": True,
            })
        try:
            _EXECUTE_LAUNCHING.add(account_id)
            try:
                closer, ctx, engine_used, fp_json = await browser_mod.launch_with_autocleanup(
                    fp, mode, profile_key=f"g{group_id}_a{account_id}",
                    proxy_server=proxy_server)
                closer = browser_mod.register_task_context(
                    f"g{group_id}_a{account_id}", closer, ctx)
            finally:
                _EXECUTE_LAUNCHING.discard(account_id)
        except browser_mod.SessionLimitError as e:
            # 撞套餐会话上限（通常是手动"打开浏览器"窗口占座）：自动关掉
            # 手动窗口并重试一次；仍失败才落为任务失败。
            steps.append({"t": _now(), "step": "session_limit",
                          "detail": "自动关闭已打开的指纹浏览器窗口后重试", "ok": True})
            await browser_mod.reclaim_manual_sessions()
            _EXECUTE_LAUNCHING.add(account_id)
            try:
                closer, ctx, engine_used, fp_json = await browser_mod.launch_with_autocleanup(
                    fp, mode, profile_key=f"g{group_id}_a{account_id}",
                    proxy_server=proxy_server)
                closer = browser_mod.register_task_context(
                    f"g{group_id}_a{account_id}", closer, ctx)
            finally:
                _EXECUTE_LAUNCHING.discard(account_id)
        steps.append({"t": _now(), "step": "browser_launched", "detail": engine_used, "ok": True})
        fp_applied = json.loads(fp_json) if fp_json and fp_json != "{}" else {}
        if fp_applied:
            _fp_brief = {k: fp_applied[k] for k in
                         ("seed", "platform", "brand", "brand_version",
                          "timezone", "locale") if k in fp_applied}
            steps.append({"t": _now(), "step": "fingerprint_detail",
                          "detail": json.dumps(_fp_brief, ensure_ascii=False), "ok": True})

        keep_browser_open = False
        try:
            result = await flows.run_flow(g["login_type"], ctx, a["username"], password,
                                          totp_secret, g["login_url"], steps,
                                          group=group_decrypted or dict(g), account=dict(a),
                                          cdp_engine=await browser_mod.cdp_configured(),
                                          phone_handler=await _resolve_phone_handler(steps, g, a))
        except Exception as exc:
            keep_browser_open = isinstance(exc, PhoneVerificationTerminalError)
            raise
        finally:
            if keep_browser_open:
                browser_mod.detach_task_context(
                    f"g{group_id}_a{account_id}")
                closer = None
                steps.append({"t": _now(), "step": "browser_left_open",
                              "detail": "手机号验证终态，浏览器保持打开", "ok": False})
            else:
                try:
                    await _close_protected(closer)
                finally:
                    steps.append({"t": _now(), "step": "browser_closed",
                                  "detail": "-", "ok": True})
        result_json = result
        if isinstance(result_json, dict):
            for key in ("callback_url", "url"):
                if isinstance(result_json.get(key), str):
                    result_json[key] = redact_callback_url(result_json[key])
        status = "success"
    except RunStopped:
        status, error = "cancelled", "已手动停止"
        steps.append({"t": _now(), "step": "stopped", "detail": "已手动停止", "ok": False})
    except Exception as e:
        error = str(e)
        status = "failed"
        if closer is not None:
            try:
                await _close_protected(closer)
            except Exception:
                pass
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        if task_id is None:
            await _mark_cancelled(db, [account_id])
            return
        status, error = "cancelled", "已手动停止"
        steps.append({"t": _now(), "step": "stopped", "detail": "已手动停止", "ok": False})
    finally:
        _stop_requests.discard(account_id)
    steps.append({"t": _now(), "step": "finished", "detail": status, "ok": status == "success"})
    # Keep the final status/steps update ordered after all incremental writes.
    await steps.flush()

    # Upstream integration (auth links, token redeem, refresh...) now lives
    # inside the flow adapters; calls are audited in adapter_logs.
    callback_status, callback_response = "skipped", ""

    await db.execute(
        """UPDATE tasks SET status=?, error=?, steps=?, result_json=?, fingerprint_json=?,
           browser_mode=?, callback_status=?, callback_response=?, started_at=?, finished_at=?
           WHERE id=?""",
        (status, error, json.dumps(steps, ensure_ascii=False),
         json.dumps(result_json, ensure_ascii=False), fp_json, mode,
         callback_status, callback_response, started_at, _now(), task_id))
    msg = error or (result_json.get("note", "") if isinstance(result_json, dict) else "")
    if status == "cancelled":
        msg = "已手动停止"
    await db.execute("UPDATE accounts SET last_status=?, last_message=? WHERE id=?",
                     (status, str(msg)[:300], account_id))
    await db.commit()
    await steps.close()


async def shutdown() -> None:
    """Stop dispatch/workers before lifespan closes the SQLite connection."""
    async with _lock:
        dispatchers = [state["dispatcher"] for state in _groups.values()]
        _groups.clear()
    for task in dispatchers:
        task.cancel()
    for task in list(_RUN_TASKS):
        task.cancel()
    if dispatchers or _RUN_TASKS:
        await asyncio.gather(*dispatchers, *_RUN_TASKS, return_exceptions=True)


async def _reconcile_stale_run(db, account_id: int) -> str:
    """Align a busy account marker with its finished task before stop returns.

    This is a stop-time recovery path for an executor whose in-memory state is
    already gone; normal completion still owns the authoritative account update.
    """
    row = await db.execute(
        """SELECT t.status AS task_status, t.error AS task_error
           FROM accounts a LEFT JOIN tasks t ON t.id=a.last_task_id
           WHERE a.id=?""", (account_id,))
    task = await row.fetchone()
    if task is None:
        return "not_running"

    task_status = task["task_status"]
    terminal_statuses = {"success", "failed", "cancelled", "callback_failed"}
    if task_status not in terminal_statuses and task_status is not None:
        return "not_running"

    status = "failed" if task_status in (None, "callback_failed") else task_status
    message = task["task_error"] or ("已手动停止" if status == "cancelled" else "任务已结束")
    await db.execute(
        """UPDATE accounts SET last_status=?, last_message=?
           WHERE id=? AND last_status IN ('queued','running')""",
        (status, str(message)[:300], account_id))
    await db.commit()
    return "stale_recovered"


async def stop_account(account_id: int) -> str:
    """Gracefully remove queued work or cancel the live login run.

    A running cancellation is awaited so the browser close is complete before
    the API response reaches the UI.
    """
    async with _account_state_lock:
        task = _RUN_TASK_BY_ACCOUNT.get(account_id)
        execute_task = _EXECUTE_TASK_BY_ACCOUNT.get(account_id)
        is_queued = account_id in _account_slots and account_id not in _running_accounts
        if not is_queued and task is None:
            db = await database.get_db()
            return await _reconcile_stale_run(db, account_id)
        _stop_requests.add(account_id)

    cancel_task = execute_task or task
    if cancel_task is not None and not cancel_task.done():
        # Don't inject cancellation into a launcher's internal await; partial
        # engine startup may not have a closer yet. Wait for the safe boundary.
        while (execute_task is not None and not execute_task.done()
               and account_id in _EXECUTE_LAUNCHING):
            await asyncio.sleep(0.05)
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass
        return "stopped"

    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # _run_one suppresses its own graceful-stop boundary after cleanup.
            pass
        return "stopped"

    db = await database.get_db()
    async with _account_state_lock:
        _account_slots.discard(account_id)
        _account_generations[account_id] = _account_generations.get(account_id, 0) + 1
    await _mark_cancelled(db, [account_id])
    return "queued_removed"
