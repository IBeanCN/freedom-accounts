"""Upstream token refresh: sequential HTTP calls with anti-rate-limit delays.

Token refresh is API-only (no browser launch). The batch entry refreshes only
normal accounts whose token expires within 30 minutes; the account-level entry
passes ``ignore_window=True`` to bypass that 30-minute check.
"""
import asyncio
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone

from ..core import crypto, database, tasks
from ..core import settings
from .flows import get_adapter

REFRESH_INTERVAL_MIN_SECONDS = 5.0
REFRESH_INTERVAL_MAX_SECONDS = 20.0
BATCH_EXPIRY_WINDOW = timedelta(minutes=30)
DEFAULT_REFRESH_INTERVAL_SECONDS = 3600
NORMAL_STATUS = "正常"
BUSY_ACCOUNT_STATUSES = {"queued", "running", "token_queued", "token_running"}
_REFRESHING: set[int] = set()
_log = logging.getLogger("automation.token_refresh")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _expiry_datetime(value) -> datetime | None:
    """Parse upstream RFC3339 or epoch (seconds/milliseconds) expiry values."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            seconds = float(text)
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
    if seconds > 1_000_000_000_000:  # milliseconds
        seconds /= 1000
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def can_refresh(row, *, ignore_window: bool = False) -> bool:
    """Whether one already-filtered enabled row satisfies upstream gate rules."""
    if (row["remote_status"] or "").strip() != NORMAL_STATUS:
        return False
    expires_at = _expiry_datetime(row["token_expires_at"])
    if expires_at is None:
        return False
    return ignore_window or expires_at <= datetime.now(timezone.utc) + BATCH_EXPIRY_WINDOW


def has_valid_expiry(row) -> bool:
    """Whether the stored expiry can be used for gate checks/display."""
    return _expiry_datetime(row["token_expires_at"]) is not None


def any_refreshing(account_ids: list[int]) -> bool:
    return any(account_id in _REFRESHING for account_id in account_ids)


def is_active() -> bool:
    """Whether one global refresh queue owns the anti-rate-limit sequence."""
    return bool(_REFRESHING)


def is_account_busy(status: str) -> bool:
    return (status or "") in BUSY_ACCOUNT_STATUSES


def adapter_supports_refresh(adapter) -> bool:
    """Distinguish a real adapter implementation from the base placeholder."""
    method = type(adapter).__dict__.get("refresh_token")
    return method is not None


async def _append_step(db, task_id: int | None, step: str,
                       detail: str, ok: bool) -> None:
    if not task_id:
        return
    row = await (await db.execute("SELECT steps FROM tasks WHERE id=?", (task_id,))).fetchone()
    try:
        steps = json.loads(row["steps"] or "[]") if row else []
    except (TypeError, ValueError):
        steps = []
    steps.append({"t": _now(), "step": step, "detail": str(detail), "ok": ok})
    await db.execute("UPDATE tasks SET steps=? WHERE id=?",
                     (json.dumps(steps, ensure_ascii=False), task_id))


async def _mark_queued(account_ids: list[int]) -> None:
    """Create one queued task-log row per account and publish queue state."""
    db = await database.get_db()
    marks = ",".join("?" * len(account_ids))
    rows = await db.execute(
        f"""SELECT id, group_id FROM accounts
            WHERE id IN ({marks}) ORDER BY id""", tuple(account_ids))
    for row in await rows.fetchall():
        created = _now()
        steps = [{"t": created, "step": "task_created",
                  "detail": "token_refresh", "ok": True}]
        cur = await db.execute(
            """INSERT INTO tasks(group_id,account_id,operation,status,steps,
               result_json,created_at) VALUES(?,?,?,?,?,?,?)""",
            (row["group_id"], row["id"], "token_refresh", "queued",
             json.dumps(steps, ensure_ascii=False),
             json.dumps({"operation": "token_refresh"}, ensure_ascii=False), created))
        await db.execute(
            """UPDATE accounts SET last_status='token_queued',
               token_refresh_result='队列中', token_refresh_at=?, last_task_id=?
               WHERE id=?""", (created, cur.lastrowid, row["id"]))
    await db.commit()


async def queue_refresh(account_ids: list[int]) -> bool:
    """Atomically reserve one global queue; false means another queue is active."""
    ids = list(dict.fromkeys(account_ids))
    if not ids:
        return True
    if is_active():
        return False
    _REFRESHING.update(ids)
    try:
        await _mark_queued(ids)
    except Exception:
        _REFRESHING.difference_update(ids)
        raise
    tasks.spawn(_run_refresh(ids))
    return True


async def _begin_refresh(account_id: int) -> int | None:
    db = await database.get_db()
    row = await (await db.execute(
        "SELECT group_id, last_task_id FROM accounts WHERE id=?", (account_id,))).fetchone()
    if not row:
        return None
    started = _now()
    task_id = row["last_task_id"]
    if task_id:
        await db.execute(
            """UPDATE tasks SET status='running', started_at=?
               WHERE id=? AND operation='token_refresh'""", (started, task_id))
        await _append_step(db, task_id, "token_refresh_started", "开始调用上游", True)
    await db.execute(
        """UPDATE accounts SET last_status='token_running',
           token_refresh_result='刷新中', token_refresh_at=? WHERE id=?""",
        (started, account_id))
    await db.commit()
    return task_id


async def _finish_refresh(account_id: int, task_id: int | None, *, ok: bool,
                          result: str, expires_at=None, remote_status: str = "",
                          error: str = "") -> None:
    db = await database.get_db()
    finished = _now()
    sets = ["last_status=?", "token_refresh_result=?", "token_refresh_at=?"]
    params: list = ["success" if ok else "failed", result[:200], finished]
    if expires_at is not None:
        sets.append("token_expires_at=?")
        params.append(str(expires_at))
    if remote_status:
        sets.append("remote_status=?")
        params.append(remote_status)
    sets.append("last_message=?")
    params.append(str(error or result)[:300])
    params.append(account_id)
    await db.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id=?", tuple(params))
    if task_id:
        await _append_step(db, task_id, "token_refresh_result", result, ok)
        await _append_step(db, task_id, "finished", "success" if ok else "failed", ok)
        await db.execute(
            """UPDATE tasks SET status=?, error=?, finished_at=?, result_json=?
               WHERE id=?""",
            ("success" if ok else "failed", error, finished,
             json.dumps({"operation": "token_refresh", "message": result,
                         "expires_at": expires_at, "remote_status": remote_status},
                        ensure_ascii=False), task_id))
    await db.commit()


async def _refresh_one(account_id: int) -> None:
    db = await database.get_db()
    row = await (await db.execute(
        """SELECT a.*, g.login_type, g.login_url, g.upstream_key
           FROM accounts a JOIN groups g ON g.id=a.group_id
           WHERE a.id=?""", (account_id,))).fetchone()
    if not row:
        return
    task_id = await _begin_refresh(account_id)
    group = dict(row)
    if group.get("upstream_key"):
        group["upstream_key"] = crypto.decrypt(group["upstream_key"])
    adapter = get_adapter(group["login_type"])()
    try:
        await _append_step(db, task_id, "upstream_refresh", row["remote_id"], True)
        result = await adapter.refresh_token(group, row["remote_id"])
        error = str((result or {}).get("error") or "").strip()
        if error:
            await _finish_refresh(account_id, task_id, ok=False,
                                  result=f"失败: {error}", error=error)
            return
        message = ("成功" if (result or {}).get("access_token_expires_at")
                   else "成功（未返回新过期时间）")
        await _finish_refresh(
            account_id, task_id, ok=True, result=message,
            expires_at=(result or {}).get("access_token_expires_at"),
            remote_status=str((result or {}).get("status_label") or "").strip())
    except NotImplementedError as e:
        await _finish_refresh(account_id, task_id, ok=False, result=f"失败: {e}",
                              error=str(e))
    except Exception as e:
        error = str(e)[:180]
        await _finish_refresh(account_id, task_id, ok=False, result=f"失败: {error}",
                              error=error)


async def _run_refresh(account_ids: list[int]) -> None:
    """Refresh one by one; delay only between accounts, never after the last."""
    try:
        for index, account_id in enumerate(account_ids):
            if index:
                await asyncio.sleep(random.uniform(
                    REFRESH_INTERVAL_MIN_SECONDS, REFRESH_INTERVAL_MAX_SECONDS))
            await _refresh_one(account_id)
    finally:
        _REFRESHING.difference_update(account_ids)


async def refresh_interval_seconds() -> int:
    """Read the configured sweep interval; invalid values fall back to 1 hour."""
    raw = await settings.get("token_refresh_interval_seconds")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_INTERVAL_SECONDS


def start_scheduler(run_once) -> asyncio.Task:
    """Run the sweep at startup, then use the current setting after each pass."""
    async def _loop() -> None:
        while True:
            try:
                result = await run_once()
                if result and result.get("queued"):
                    _log.info("token refresh sweep: %s", result)
            except Exception as e:
                _log.warning("token refresh sweep failed: %s", e)
            await asyncio.sleep(await refresh_interval_seconds())

    return tasks.spawn(_loop())
