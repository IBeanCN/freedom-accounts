"""Periodic refresh of enabled accounts through upstream detail APIs."""
import asyncio
import logging

from ..core import crypto, database, settings, tasks
from .flows import get_adapter

DEFAULT_INTERVAL_SECONDS = 3600
ACCOUNT_DELAY_SECONDS = 1
_log = logging.getLogger("automation.account_refresh")
_refresh_lock = asyncio.Lock()


async def interval_seconds() -> int:
    raw = await settings.get("account_data_refresh_interval_seconds")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS


async def _enabled_count(db) -> int:
    row = await (await db.execute(
        "SELECT COUNT(*) AS total FROM accounts WHERE enabled=1"
    )).fetchone()
    return int(row["total"] or 0)


def _supports_detail(adapter) -> bool:
    return type(adapter).__dict__.get("get_account") is not None


async def _refresh_once() -> dict:
    db = await database.get_db()
    enabled_count = await _enabled_count(db)
    configured = await interval_seconds()
    if configured < enabled_count:
        _log.warning(
            "account data refresh skipped: interval=%ss, enabled_accounts=%s",
            configured, enabled_count,
        )
        return {"refreshed": 0, "skipped": True, "enabled_accounts": enabled_count}

    rows = await (await db.execute(
        """SELECT a.id, a.group_id, a.remote_id, g.login_type, g.upstream_key,
                  g.login_url
           FROM accounts a JOIN groups g ON g.id=a.group_id
           WHERE a.enabled=1 AND TRIM(a.remote_id) != '' ORDER BY a.id"""
    )).fetchall()
    refreshed = 0
    for index, row in enumerate(rows):
        # Account count and setting may change while a round is in progress.
        current_count = await _enabled_count(db)
        current_interval = await interval_seconds()
        if current_interval < current_count:
            _log.warning(
                "account data refresh stopped: interval=%ss, enabled_accounts=%s",
                current_interval, current_count,
            )
            break
        adapter = get_adapter(row["login_type"])()
        if not _supports_detail(adapter):
            continue
        group = {"id": row["group_id"], "login_type": row["login_type"],
                 "login_url": row["login_url"],
                 "upstream_key": crypto.decrypt(row["upstream_key"] or "")}
        try:
            detail = await adapter.get_account(group, row["remote_id"])
            status = str(detail.get("status_label") or "").strip()
            remark = str(detail.get("remark") or "").strip()
            expiry = detail.get("access_token_expires_at")
            if expiry is None:
                await db.execute(
                    "UPDATE accounts SET remote_status=?, remote_remark=? WHERE id=?",
                    (status, remark, row["id"]),
                )
            else:
                await db.execute(
                    """UPDATE accounts SET remote_status=?, remote_remark=?,
                       token_expires_at=? WHERE id=?""",
                    (status, remark, str(expiry or ""), row["id"]),
                )
            await db.commit()
            refreshed += 1
        except Exception as exc:
            _log.warning("account %s detail refresh failed: %s", row["id"], exc)
        if index < len(rows) - 1:
            await asyncio.sleep(ACCOUNT_DELAY_SECONDS)
    return {"refreshed": refreshed, "skipped": False,
            "enabled_accounts": enabled_count}


async def run_once() -> dict:
    async with _refresh_lock:
        return await _refresh_once()


def start_scheduler() -> asyncio.Task:
    async def _loop() -> None:
        while True:
            interval = await interval_seconds()
            if interval == 0:
                await asyncio.sleep(60)
                continue
            try:
                result = await run_once()
                if result.get("refreshed"):
                    _log.info("account data refresh: %s", result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.warning("account data refresh failed: %s", exc)
            await asyncio.sleep(interval)

    return tasks.spawn(_loop())
