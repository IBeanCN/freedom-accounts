"""Groups router: CRUD + start batch login."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import config, database, settings
from ..core import crypto
from ..automation import scheduler
from ..automation import fingerprint as fp_mod
from ..automation import fpcheck
from ..automation.flows import validate_login_type, get_adapter
from ..automation.platforms import is_known_group_type
from ..automation.flows.adapters._util import translate_remote_status
from .deps import require_admin

router = APIRouter(prefix="/api/groups", tags=["groups"], dependencies=[Depends(require_admin)])


class GroupBody(BaseModel):
    group_type: str = Field(min_length=1, description="platform key from /api/meta, e.g. OpenAI-openai")
    name: str = Field(min_length=1)
    login_type: str = Field(min_length=1, description="flow adapter key: password | sub2api | cpr")
    login_url: str = Field(min_length=1, description="upstream base URL, used by the adapter")
    upstream_key: str = Field(default="", description="upstream auth key, adapter-internal")
    # legacy columns kept in DB for backward compatibility; no longer accepted
    # from the UI — callbacks now happen inside the adapters, log-only.
    callback_url: str = ""
    header_json: str = "[]"
    concurrency: int = Field(default=1, ge=1, le=config.MAX_CONCURRENCY_PER_GROUP)
    interval_min_ms: int = Field(default=5000, ge=config.INTERVAL_MIN_MS, le=config.INTERVAL_MAX_MS)
    interval_max_ms: int = Field(default=10000, ge=config.INTERVAL_MIN_MS, le=config.INTERVAL_MAX_MS)
    browser_mode: str = Field(default="inherit", pattern="^(headless|headed|inherit)$")
    # group-level proxy; the account-level proxy wins when both are set
    proxy_id: Optional[int] = None
    # group-level fingerprint template: accounts inherit these values, seed is
    # always randomized per account (company-batch machine scenario)
    fingerprint_template: dict | str = {}
    # fingerprint-check site URL override; empty => use the system setting
    fp_check_url: str = ""


class StartBody(BaseModel):
    account_ids: Optional[list[int]] = None   # empty/None => all accounts in group


async def _apply_remote_sync(db, group_row, remote_data: dict) -> dict:
    """Apply upstream account data to the local DB (shared by sync + start).

    Returns counts: {created, updated, deleted, disabled, ignored, remote_total}.
    The caller is responsible for fetching the remote data via the adapter.
    """
    group_id = group_row["id"]
    remote_items: dict[str, dict] = {}
    for it in remote_data.get("accounts", []):
        rid = str(it.get("id") or "").strip()
        if rid:
            remote_items.setdefault(rid, it)
    remote_names: set[str] = {
        str(it.get("email") or it.get("name") or "").strip().lower()
        for it in remote_items.values()}
    remote_names.discard("")
    remote_identity_ids: dict[str, set[str]] = {}
    for rid, item in remote_items.items():
        identity = str(item.get("email") or item.get("name") or "").strip().lower()
        if identity:
            remote_identity_ids.setdefault(identity, set()).add(rid)

    rows = await db.execute("SELECT * FROM accounts WHERE group_id=?", (group_id,))
    local_rows = await rows.fetchall()
    local_by_rid: dict[str, dict] = {}
    for r in local_rows:
        d = dict(r)
        rid = (d.get("remote_id") or "").strip()
        if rid:
            local_by_rid[rid] = d

    created = deleted = updated = disabled = 0
    template = group_row.get("fingerprint_template") or "{}"
    has_tpl = bool(fp_mod.sanitize(template))

    # step 1) synced rows whose remote id vanished upstream -> delete
    for rid, row in local_by_rid.items():
        if rid not in remote_items:
            await db.execute("DELETE FROM accounts WHERE id=?", (row["id"],))
            deleted += 1

    # step 2) upsert by remote_id
    for rid, it in remote_items.items():
        display = str(it.get("email") or it.get("name") or rid).strip()
        status = str(it.get("status_label")
                     or translate_remote_status(it.get("status"))
                     or "").strip()
        up_remark = str(it.get("remark") or "").strip()
        row = local_by_rid.get(rid)
        if row is not None:
            await db.execute(
                """UPDATE accounts SET username=?, remote_status=?,
                   remote_remark=? WHERE id=?""",
                (display or row["username"], status or row["remote_status"],
                 up_remark, row["id"]))
            updated += 1
        else:
            fp = fp_mod.generate_from_template(template) if has_tpl \
                else fp_mod.generate_fingerprint()
            await db.execute(
                """INSERT INTO accounts(group_id,username,password,fingerprint,
                   remote_id,remote_status,remote_remark)
                   VALUES(?,?,?,?,?,?,?)""",
                (group_id, display or rid, "", json.dumps(fp, ensure_ascii=False),
                 rid, status, up_remark))
            created += 1

    # step 3) disable duplicates after final display usernames are known.
    rows = await db.execute(
        "SELECT id, username, remote_id, enabled FROM accounts WHERE group_id=?",
        (group_id,))
    final_rows = await rows.fetchall()
    dup_ids: list[int] = []
    for row in final_rows:
        identity = (row["username"] or "").strip().lower()
        remote_ids = remote_identity_ids.get(identity, set())
        rid = (row["remote_id"] or "").strip()
        manual_duplicate = not rid and identity in remote_names
        synced_duplicate = bool(rid) and len(remote_ids) > 1 and rid in remote_ids
        if (manual_duplicate or synced_duplicate) and row["enabled"]:
            dup_ids.append(row["id"])
    for aid in dup_ids:
        await db.execute(
            "UPDATE accounts SET enabled=0 WHERE id=? AND enabled=1", (aid,))
        disabled += 1

    await db.commit()
    ignored = max(0, len(remote_items) - created)
    return {"created": created, "updated": updated, "deleted": deleted,
            "disabled": disabled, "ignored": ignored,
            "remote_total": len(remote_items)}


class RegenFpBody(BaseModel):
    """Batch-replace fingerprints of every account in the group.

    mode:
      - "seed_only": keep each account's fingerprint, randomize seed only
        (same-model company machines: one seed = one identity)
      - "from_template": rebuild from the group's fingerprint_template,
        randomizing seed per account
      - "random": fully random per account (legacy behavior)
    """
    mode: str = Field(default="seed_only", pattern="^(seed_only|from_template|random)$")


def _manual_session_key(group_id: int) -> str:
    return f"g{group_id}_manual"


def _row_dict(r) -> dict:
    d = dict(r)
    # callback fields are legacy: hidden from the UI, kept for DB compatibility
    d.pop("callback_url", None)
    d.pop("header_json", None)
    if d.get("upstream_key"):
        d["upstream_key"] = crypto.decrypt(d["upstream_key"])
    d["fingerprint_template"] = fp_mod.sanitize(d.get("fingerprint_template"))
    return d


@router.get("")
async def list_groups():
    db = await database.get_db()
    rows = await db.execute(
        """SELECT g.*,
                  (SELECT COUNT(*) FROM accounts a WHERE a.group_id=g.id) AS account_count,
                  (SELECT COUNT(*) FROM accounts a WHERE a.group_id=g.id AND a.last_status='running') AS running_count,
                  (SELECT p.timezone FROM proxies p WHERE p.id=g.proxy_id) AS proxy_timezone,
                  (SELECT p.country  FROM proxies p WHERE p.id=g.proxy_id) AS proxy_country,
                  (SELECT p.city     FROM proxies p WHERE p.id=g.proxy_id) AS proxy_city,
                  (SELECT p.locale   FROM proxies p WHERE p.id=g.proxy_id) AS proxy_locale
           FROM groups g ORDER BY g.id DESC""")
    return {"groups": [_row_dict(r) for r in await rows.fetchall()]}


@router.get("/{group_id}")
async def get_group(group_id: int):
    db = await database.get_db()
    row = await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))
    g = await row.fetchone()
    if not g:
        raise HTTPException(404, "group not found")
    return _row_dict(g)


def _validated_login_type(value: str) -> str:
    try:
        return validate_login_type(value)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("")
async def create_group(body: GroupBody):
    if body.interval_max_ms < body.interval_min_ms:
        raise HTTPException(400, "interval_max_ms must be >= interval_min_ms")
    login_type = _validated_login_type(body.login_type)
    if not is_known_group_type(body.group_type):
        raise HTTPException(400, f"unknown group_type: {body.group_type}")
    tpl = fp_mod.as_template(body.fingerprint_template)
    encrypted_key = crypto.encrypt(body.upstream_key) if body.upstream_key else ""
    db = await database.get_db()
    cur = await db.execute(
        """INSERT INTO groups(group_type,name,login_type,login_url,upstream_key,callback_url,
           header_json,concurrency,interval_min_ms,interval_max_ms,browser_mode,
           proxy_id,fingerprint_template,fp_check_url)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (body.group_type, body.name, login_type, body.login_url, encrypted_key,
         "", "[]",
         body.concurrency, body.interval_min_ms, body.interval_max_ms, body.browser_mode,
         body.proxy_id, json.dumps(tpl, ensure_ascii=False), body.fp_check_url.strip()))
    await db.commit()
    return {"id": cur.lastrowid}


@router.put("/{group_id}")
async def update_group(group_id: int, body: GroupBody):
    if body.interval_max_ms < body.interval_min_ms:
        raise HTTPException(400, "interval_max_ms must be >= interval_min_ms")
    login_type = _validated_login_type(body.login_type)
    if not is_known_group_type(body.group_type):
        raise HTTPException(400, f"unknown group_type: {body.group_type}")
    db = await database.get_db()
    row = await db.execute("SELECT id FROM groups WHERE id=?", (group_id,))
    if not await row.fetchone():
        raise HTTPException(404, "group not found")
    # a template never pins a seed: sanitized fields only
    tpl = fp_mod.as_template(body.fingerprint_template)
    encrypted_key = crypto.encrypt(body.upstream_key) if body.upstream_key else ""
    await db.execute(
        """UPDATE groups SET group_type=?,name=?,login_type=?,login_url=?,upstream_key=?,
           callback_url=?,header_json=?,concurrency=?,interval_min_ms=?,interval_max_ms=?,
           browser_mode=?,proxy_id=?,fingerprint_template=?,fp_check_url=?
           WHERE id=?""",
        (body.group_type, body.name, login_type, body.login_url, encrypted_key,
         "", "[]",
         body.concurrency, body.interval_min_ms, body.interval_max_ms, body.browser_mode,
         body.proxy_id, json.dumps(tpl, ensure_ascii=False), body.fp_check_url.strip(),
         group_id))
    await db.commit()
    return {"ok": True}


@router.post("/{group_id}/regenerate-fingerprints")
async def regenerate_fingerprints(group_id: int, body: RegenFpBody):
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")
    rows = await db.execute("SELECT id, fingerprint FROM accounts WHERE group_id=?", (group_id,))
    accounts = await rows.fetchall()
    if not accounts:
        raise HTTPException(400, "no accounts in group")
    template = g["fingerprint_template"] if "fingerprint_template" in g.keys() else "{}"
    updated = 0
    for r in accounts:
        if body.mode == "seed_only":
            try:
                fp = json.loads(r["fingerprint"] or "{}")
            except Exception:
                fp = {}
            fp = fp_mod.sanitize(fp) or fp_mod.generate_fingerprint()
            fp["seed"] = fp_mod.generate_fingerprint()["seed"]
        elif body.mode == "from_template":
            fp = fp_mod.generate_from_template(template) if fp_mod.sanitize(template) \
                else fp_mod.generate_fingerprint()
        else:
            fp = fp_mod.generate_fingerprint()
        await db.execute("UPDATE accounts SET fingerprint=? WHERE id=?",
                         (json.dumps(fp, ensure_ascii=False), r["id"]))
        updated += 1
    await db.commit()
    return {"ok": True, "updated": updated, "mode": body.mode}


@router.delete("/{group_id}")
async def delete_group(group_id: int):
    db = await database.get_db()
    await db.execute("DELETE FROM groups WHERE id=?", (group_id,))
    await db.commit()
    return {"ok": True}


@router.post("/{group_id}/start")
async def start_group(group_id: int, body: StartBody):
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")

    # pre-validation: config must be complete before any sync or start
    errors = []
    if not (g["login_url"] or "").strip():
        errors.append("上号地址未配置")
    if g["login_type"] in ("sub2api", "cpr") and not (g["upstream_key"] or "").strip():
        errors.append("上游 API Key 未配置")
    if errors:
        raise HTTPException(400, "前置校验失败: " + "; ".join(errors))

    # step 1) sync accounts from upstream to refresh remote_status
    adapter_group = dict(g)
    if adapter_group.get("upstream_key"):
        adapter_group["upstream_key"] = crypto.decrypt(adapter_group["upstream_key"])
    adapter = get_adapter(g["login_type"])()
    sync_result = None
    try:
        remote = await adapter.list_accounts(adapter_group)
        if remote is not None:
            sync_result = await _apply_remote_sync(db, dict(g), remote)
    except NotImplementedError:
        pass  # adapter doesn't support sync, proceed with local data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"同步上游账号失败: {e}")

    # step 2) filter: only enabled accounts with remote_status='error'
    rows = await db.execute(
        """SELECT id, username, remote_status FROM accounts
           WHERE group_id=? AND enabled=1 AND remote_status='error'
           ORDER BY id""",
        (group_id,))
    error_accounts = await rows.fetchall()

    if not error_accounts:
        return {"ok": True, "queued": 0, "error_count": 0, "sync": sync_result,
                "message": "同步完成，没有上游状态为「错误」的启用账号，无需上号"}

    # step 3) enqueue only the error accounts
    error_ids = [r["id"] for r in error_accounts]
    n = await scheduler.enqueue(group_id, error_ids)
    return {"ok": True, "queued": n, "error_count": len(error_ids),
            "error_accounts": [{"id": r["id"], "username": r["username"]}
                               for r in error_accounts],
            "sync": sync_result}


class SyncBody(BaseModel):
    """Sync (pull) upstream accounts into the group.

    Identity is strictly the upstream account id (remote_id):
      - remote_id already present locally -> update UPSTREAM-owned fields only
        (display name, remark, remote_id). Local-only fields (password, TOTP,
        fingerprint, proxy, enabled...) are never touched.
      - local row with remote_id missing upstream -> deleted (it came from sync).
      - local manual rows (no remote_id) are always kept untouched.
      - same account (email/username) present under DIFFERENT remote ids ->
        every matching local row is disabled (duplicate account protection).
    """
    dry_run: bool = False


@router.post("/{group_id}/sync-accounts")
async def sync_accounts(group_id: int, body: SyncBody):
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")

    adapter_group = dict(g)
    if adapter_group.get("upstream_key"):
        adapter_group["upstream_key"] = crypto.decrypt(adapter_group["upstream_key"])
    adapter = get_adapter(g["login_type"])()
    try:
        remote = await adapter.list_accounts(adapter_group)
    except NotImplementedError:
        raise HTTPException(400, f"登录类型 {g['login_type']} 不支持同步账号")
    except Exception as e:
        raise HTTPException(502, f"拉取上游账号失败: {e}")

    counts = await _apply_remote_sync(db, dict(g), remote)
    return {"ok": True, "dry_run": body.dry_run, **counts}


@router.post("/{group_id}/fp-check")
async def fp_check_group(group_id: int):
    """Fingerprint-template check: validate the group's configured template with
    one representative fingerprint against the check site (background run)."""
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")
    tpl = fp_mod.sanitize(g["fingerprint_template"])
    if not tpl:
        raise HTTPException(400, "分组未配置指纹模板，请先在分组编辑中配置")
    # gate: refuse to start when no check URL is configured (group > setting)
    if not (await fpcheck.resolve_check_url(g)):
        raise HTTPException(400, fpcheck.NO_URL_MSG)
    if (g["fp_check_result"] or "") == "检测中":
        return {"ok": True, "already_running": True}
    return fpcheck.start_group_check(group_id)


@router.post("/{group_id}/open-browser")
async def open_browser(group_id: int):
    """Open a persistent interactive browser for the group (manual use).

    Local SDK mode only: refused when cloakserve CDP is configured (a remote
    Docker browser cannot show a window on this machine). Uses the group's
    fingerprint template (random seed when unset) + group proxy, headed mode;
    the session stays open until explicitly closed via /close.
    """
    from ..automation import browser as browser_mod

    cdp_url = (await settings.get("cloak_cdp_url") or "").strip()
    if cdp_url:
        raise HTTPException(
            409, "当前使用远程 CDP 引擎（cloakserve），浏览器运行在服务端，无法在本地打开；请在系统设置中清空 CDP 地址后使用本地 SDK 引擎")

    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")

    template = g["fingerprint_template"] if "fingerprint_template" in g.keys() else "{}"
    tpl = fp_mod.sanitize(template)
    fp = fp_mod.generate_from_template(tpl)     # random seed always
    proxy_server = await browser_mod.resolve_proxy(
        None, g["proxy_id"] if "proxy_id" in g.keys() else None)

    try:
        result = await browser_mod.open_managed_browser(
            fp, "headed", _manual_session_key(group_id), proxy_server=proxy_server)
    except Exception as e:
        raise HTTPException(500, f"打开浏览器失败: {str(e)[:120]}")
    return {**result, "proxy": browser_mod.mask_proxy_server(proxy_server)}


@router.post("/{group_id}/close-browser")
async def close_browser(group_id: int):
    """Close the group's managed interactive browser (no-op when not open)."""
    from ..automation import browser as browser_mod

    closed = await browser_mod.close_managed_session(_manual_session_key(group_id))
    return {"ok": True, "closed": closed}
