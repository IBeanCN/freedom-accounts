"""Task scheduler & executor: per-group dispatch queue, group concurrency cap,
random inter-account interval.

Design:
  - one dispatcher task per group (spawned on demand), pulls account ids from
    an asyncio.Queue and waits [interval_min, interval_max] (random) between
    consecutive dispatches;
  - a group-level asyncio.Semaphore(group.concurrency) bounds simultaneous
    browser runs; queued tasks wait on the semaphore;
  - each run: create task row -> launch browser -> run login flow -> persist
    result. Upstream integration is adapter-internal and log-only now.
"""
import asyncio
import json
import random
import time
from datetime import datetime

from ..core import config, database, settings
from . import browser as browser_mod
from . import flows

_groups: dict[int, dict] = {}   # group_id -> {"queue": Queue, "dispatcher": Task, "sem": Semaphore}
_lock = asyncio.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def enqueue(group_id: int, account_ids: list[int]) -> int:
    """Queue accounts of one group; spawns the group dispatcher if needed."""
    async with _lock:
        g = _groups.get(group_id)
        if g is None:
            g = {"queue": asyncio.Queue(), "sem": None}
            _groups[group_id] = g
            g["dispatcher"] = asyncio.create_task(_dispatcher(group_id, g))
        for aid in account_ids:
            await g["queue"].put(aid)
        return len(account_ids)


async def _dispatcher(group_id: int, g: dict) -> None:
    db = await database.get_db()
    while True:
        account_id = await g["queue"].get()
        # read current interval config every dispatch (live-updatable)
        row = await db.execute(
            "SELECT concurrency, interval_min_ms, interval_max_ms FROM groups WHERE id=?",
            (group_id,))
        gr = await row.fetchone()
        if gr is None:          # group deleted
            break
        conc = max(1, min(int(gr["concurrency"] or 1), config.MAX_CONCURRENCY_PER_GROUP))
        if g["sem"] is None or g["sem"]._value != conc:  # config changed
            g["sem"] = asyncio.Semaphore(conc)
        sem = g["sem"]

        lo = max(int(gr["interval_min_ms"] or 0), config.INTERVAL_MIN_MS) / 1000.0
        hi = max(int(gr["interval_max_ms"] or 0), lo) / 1000.0
        # interval applies between dispatches; wait before every dispatch except
        # when nothing else was dispatched recently (queue idle -> start fast)
        if not g["queue"].empty() or getattr(g, "_last_dispatch", None):
            pass
        if g.get("last_dispatch") is not None:
            await asyncio.sleep(random.uniform(lo, hi))
        g["last_dispatch"] = time.monotonic()

        asyncio.create_task(_run_one(group_id, account_id, sem))


async def _run_one(group_id: int, account_id: int, sem: asyncio.Semaphore) -> None:
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    a = await (await db.execute("SELECT * FROM accounts WHERE id=?", (account_id,))).fetchone()
    if not g or not a:
        return

    async with sem:
        await _execute(db, g, a)


async def _execute(db, g, a) -> None:
    group_id, account_id = g["id"], a["id"]
    cur = await db.execute(
        "INSERT INTO tasks(group_id,account_id,status,created_at) VALUES(?,?, 'running', ?)",
        (group_id, account_id, _now()))
    task_id = cur.lastrowid
    started_at = _now()
    steps: list = [{"t": _now(), "step": "task_created", "detail": f"task#{task_id}", "ok": True}]
    await db.execute(
        "UPDATE accounts SET last_status='running', last_task_id=?, last_run_at=? WHERE id=?",
        (task_id, started_at, account_id))
    await db.commit()

    status, error, result_json, fp_json, mode = "failed", "", {}, "{}", ""
    engine_used = browser_mod.engine_name()
    closer = None
    try:
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
            steps.append({"t": _now(), "step": "proxy", "detail": proxy_server, "ok": True})
        closer, ctx, engine_used, fp_json = await browser_mod.launch_for_account(
            fp, mode, profile_key=f"g{group_id}_a{account_id}",
            proxy_server=proxy_server)
        steps.append({"t": _now(), "step": "browser_launched", "detail": engine_used, "ok": True})

        try:
            result = await flows.run_flow(g["login_type"], ctx, a["username"], a["password"],
                                          a["totp_secret"], g["login_url"], steps)
        finally:
            try:
                await closer()
            finally:
                steps.append({"t": _now(), "step": "browser_closed", "detail": "-", "ok": True})
        result_json = result
        status = "success"
    except Exception as e:
        error = str(e)
        status = "failed"
        if closer is not None:
            try:
                await closer()
            except Exception:
                pass
    steps.append({"t": _now(), "step": "finished", "detail": status, "ok": status == "success"})

    # NOTE: upstream callbacks used to be posted here via groups.callback_url.
    # That field is retired — upstream integration (auth links, token redeem,
    # refresh...) now lives inside the flow adapters and is log-only
    # (see flows/adapters/base.py & adapter_logs).
    callback_status, callback_response = "skipped", ""

    await db.execute(
        """UPDATE tasks SET status=?, error=?, steps=?, result_json=?, fingerprint_json=?,
           browser_mode=?, callback_status=?, callback_response=?, started_at=?, finished_at=?
           WHERE id=?""",
        (status, error, json.dumps(steps, ensure_ascii=False),
         json.dumps(result_json, ensure_ascii=False), fp_json, mode,
         callback_status, callback_response, started_at, _now(), task_id))
    msg = error or (result_json.get("note", "") if isinstance(result_json, dict) else "")
    await db.execute("UPDATE accounts SET last_status=?, last_message=? WHERE id=?",
                     (status, str(msg)[:300], account_id))
    await db.commit()
