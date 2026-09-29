"""Periodic maintenance: prune expired logs (adapter_logs & tasks).

Retention comes from settings.log_retention_days (default 3). The pruner
runs as one asyncio task for the app lifetime, sweeping once per hour;
`prune_once` is also invoked on startup so a fresh boot cleans immediately.
"""
import asyncio
from datetime import datetime, timedelta

from ..core import database, settings
import logging

log = logging.getLogger("maintenance")

SWEEP_INTERVAL_SECONDS = 3600


async def count_task_screenshots(task_ids) -> int:
    """Count DB screenshots that will disappear with their task rows."""
    ids = list(task_ids)
    if not ids:
        return 0
    db = await database.get_db()
    marks = ",".join("?" * len(ids))
    row = await db.execute(
        f"SELECT COUNT(*) AS count FROM task_screenshots WHERE task_id IN ({marks})",
        tuple(int(task_id) for task_id in ids),
    )
    return (await row.fetchone())["count"]


async def _retention_days() -> int:
    raw = ""
    try:
        raw = (await settings.get("log_retention_days") or "").strip()
    except Exception:
        pass
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


async def prune_once() -> dict:
    """Delete adapter_logs and tasks older than the retention window."""
    days = await _retention_days()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    db = await database.get_db()
    cur = await db.execute("DELETE FROM adapter_logs WHERE created_at < ?", (cutoff,))
    adapter_deleted = cur.rowcount or 0
    expired_rows = await db.execute(
        "SELECT id FROM tasks WHERE created_at < ? AND status NOT IN ('running','pending')",
        (cutoff,))
    expired_ids = [row["id"] for row in await expired_rows.fetchall()]
    screenshots_deleted = await count_task_screenshots(expired_ids)
    cur = await db.execute(
        "DELETE FROM tasks WHERE created_at < ? AND status NOT IN ('running','pending')",
        (cutoff,))
    tasks_deleted = cur.rowcount or 0
    await db.commit()
    return {"cutoff": cutoff, "retention_days": days,
            "adapter_logs_deleted": adapter_deleted, "tasks_deleted": tasks_deleted,
            "screenshots_deleted": screenshots_deleted}


async def _loop() -> None:
    while True:
        try:
            r = await prune_once()
            if r["adapter_logs_deleted"] or r["tasks_deleted"]:
                log.info("log prune: %s", r)
        except Exception as e:
            log.warning("log prune failed: %s", e)
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start_pruner() -> asyncio.Task:
    return asyncio.create_task(_loop())
