"""Groups router: CRUD + start batch login."""
import logging
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import config, database, settings
from ..core import crypto
from ..automation import scheduler
from ..automation import fingerprint as fp_mod
from ..automation import fpcheck
from ..automation import token_refresh
from ..automation.flows import validate_login_type, get_adapter
from ..automation.platforms import is_known_group_type
from ..automation.flows.adapters._util import totp_code, translate_remote_status
from .deps import require_admin

router = APIRouter(prefix="/api/groups", tags=["groups"], dependencies=[Depends(require_admin)])
_log = logging.getLogger("groups.token_refresh")


class GroupBody(BaseModel):
    group_type: str = Field(min_length=1, description="platform key from /api/meta, e.g. OpenAI-openai")
    name: str = Field(min_length=1)
    login_type: str = Field(min_length=1, description="flow adapter key: sub2api | cpr")
    login_url: str = Field(min_length=1, description="upstream base URL, used by the adapter")
    upstream_key: str = Field(default="", description="upstream auth key, adapter-internal")
    # legacy columns kept in DB for backward compatibility; no longer accepted
    # from the UI — callbacks now happen inside the adapters.
    callback_url: str = ""
    header_json: str = "[]"
    concurrency: int = Field(default=1, ge=1, le=config.MAX_CONCURRENCY_PER_GROUP)
    interval_min_ms: int = Field(default=5000, ge=config.INTERVAL_MIN_MS, le=config.INTERVAL_MAX_MS)
    interval_max_ms: int = Field(default=10000, ge=config.INTERVAL_MIN_MS, le=config.INTERVAL_MAX_MS)
    browser_mode: str = Field(default="inherit", pattern="^(headless|headed|inherit)$")
    # group-level proxy; the account-level proxy wins when both are set
    proxy_id: Optional[int] = None
    # group-level phone platform; empty => use system settings
    phone_platform: str = ""
    # group-level fingerprint template: accounts inherit these values, seed is
    # always randomized per account (company-batch machine scenario)
    fingerprint_template: dict | str = {}
    # fingerprint-check site URL override; empty => use the system setting
    fp_check_url: str = ""


class StartBody(BaseModel):
    account_ids: Optional[list[int]] = None   # empty/None => all accounts in group


def _has_valid_totp(encrypted_secret: str) -> bool:
    """Run-time TOTP precheck; an empty secret remains optional and never enters here."""
    try:
        return totp_code(crypto.decrypt(encrypted_secret)) is not None
    except Exception:
        return False


class RefreshTokensBody(BaseModel):
    """Batch refresh selected upstream accounts (empty/None => whole group)."""
    account_ids: Optional[list[int]] = None


async def _collect_group_refresh_candidates(g, selected_ids: list[int] | None = None):
    """Sync upstream rows, then select enabled normal accounts inside 30 minutes.

    Shared by the one-click endpoint and the scheduled sweep so both use the
    same expiry/status gates.
    """
    db = await database.get_db()
    adapter = get_adapter(g["login_type"])()
    if not token_refresh.adapter_supports_refresh(adapter):
        raise HTTPException(400, f"登录类型 {g['login_type']} 不支持刷新 Token")

    # Sync first so the 30-minute decision uses upstream status/expiry, not a stale row.
    adapter_group = dict(g)
    if adapter_group.get("upstream_key"):
        adapter_group["upstream_key"] = crypto.decrypt(adapter_group["upstream_key"])
    try:
        remote = await adapter.list_accounts(adapter_group)
        await _apply_remote_sync(db, dict(g), remote)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"同步上游账号失败: {e}")

    selected_ids = list(dict.fromkeys(selected_ids or []))
    params: list = [g["id"]]
    where = ("WHERE group_id=? AND enabled=1 AND remote_status='正常' "
             "AND token_expires_at != '' "
             "AND last_status NOT IN ('queued','running','token_queued','token_running')")
    if selected_ids:
        where += f" AND id IN ({','.join('?' * len(selected_ids))})"
        params.extend(selected_ids)
    rows = await db.execute(
        f"""SELECT id, username, remote_status, token_expires_at,
                   token_refresh_result FROM accounts {where} ORDER BY id""",
        tuple(params))
    rows = await rows.fetchall()

    candidates: list = []
    skipped_window = skipped_invalid = 0
    for row in rows:
        if token_refresh.can_refresh(row):
            candidates.append(row)
        elif not token_refresh.has_valid_expiry(row):
            skipped_invalid += 1
        else:
            skipped_window += 1
    return candidates, skipped_window, skipped_invalid, len(selected_ids)


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
    remote_identity_ids: dict[str, set[str]] = {}
    for rid, item in remote_items.items():
        identity = str(item.get("email") or item.get("name") or "").strip().lower()
        if identity:
            remote_identity_ids.setdefault(identity, set()).add(rid)

    def _item_identity(item: dict) -> str:
        return str(item.get("email") or item.get("name") or "").strip().lower()

    remote_names = set(remote_identity_ids)

    rows = await db.execute("SELECT * FROM accounts WHERE group_id=?", (group_id,))
    local_rows = await rows.fetchall()
    local_by_rid: dict[str, dict] = {}
    local_manual_by_identity: dict[str, list[dict]] = {}
    for r in local_rows:
        d = dict(r)
        rid = (d.get("remote_id") or "").strip()
        if rid:
            local_by_rid[rid] = d
        else:
            identity = (d.get("username") or "").strip().lower()
            if identity:
                local_manual_by_identity.setdefault(identity, []).append(d)

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
        token_expires_at = str(it.get("access_token_expires_at")
                               or it.get("token_expires_at") or "").strip()
        row = local_by_rid.get(rid)
        identity = _item_identity(it)
        if row is None and identity:
            # Manual accounts get their remote_id only after the first upstream
            # authorization. Adopt exactly one matching row so the user's local
            # password/fingerprint survive; ambiguous matches keep duplicate
            # protection below.
            manual_rows = local_manual_by_identity.get(identity, [])
            if len(manual_rows) == 1 and remote_identity_ids.get(identity) == {rid}:
                row = manual_rows[0]
        if row is not None:
            await db.execute(
                """UPDATE accounts SET username=?, remote_id=?, remote_status=?,
                   remote_remark=?, token_expires_at=? WHERE id=?""",
                (display or row["username"], rid,
                 status or row["remote_status"],
                 up_remark, token_expires_at or row["token_expires_at"], row["id"]))
            updated += 1
        else:
            fp = fp_mod.generate_from_template(template) if has_tpl \
                else fp_mod.generate_fingerprint()
            await db.execute(
                """INSERT INTO accounts(group_id,username,password,fingerprint,
                   remote_id,remote_status,remote_remark,token_expires_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (group_id, display or rid, "", json.dumps(fp, ensure_ascii=False),
                 rid, status, up_remark, token_expires_at))
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
    account_ids: Optional[list[int]] = None   # None/empty => all accounts in group


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
    from ..automation import browser as browser_mod

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
    groups = []
    for row in await rows.fetchall():
        item = _row_dict(row)
        item["browser_open"] = browser_mod.is_managed_session_open(
            _manual_session_key(row["id"]))
        groups.append(item)
    return {"groups": groups}


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
           proxy_id,phone_platform,fingerprint_template,fp_check_url)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (body.group_type, body.name, login_type, body.login_url, encrypted_key,
         "", "[]",
         body.concurrency, body.interval_min_ms, body.interval_max_ms, body.browser_mode,
         body.proxy_id, body.phone_platform.strip(),
         json.dumps(tpl, ensure_ascii=False), body.fp_check_url.strip()))
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
           browser_mode=?,proxy_id=?,phone_platform=?,fingerprint_template=?,fp_check_url=?
           WHERE id=?""",
        (body.group_type, body.name, login_type, body.login_url, encrypted_key,
         "", "[]",
         body.concurrency, body.interval_min_ms, body.interval_max_ms, body.browser_mode,
         body.proxy_id, body.phone_platform.strip(),
         json.dumps(tpl, ensure_ascii=False), body.fp_check_url.strip(), group_id))
    await db.commit()
    return {"ok": True}


@router.post("/{group_id}/regenerate-fingerprints")
async def regenerate_fingerprints(group_id: int, body: RegenFpBody):
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")
    selected_ids = list(dict.fromkeys(body.account_ids or []))
    params: list = [group_id]
    where = ("WHERE group_id=? AND last_status NOT IN "
             "('queued','running','token_queued','token_running')")
    if selected_ids:
        where += f" AND id IN ({','.join('?' * len(selected_ids))})"
        params.extend(selected_ids)
    rows = await db.execute(
        f"SELECT id, fingerprint FROM accounts {where}", tuple(params))
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
        errors.append("任务地址未配置")
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

    # Unique manual rows adopted during sync now carry the upstream ID; any
    # remaining local-only rows are still valid OAuth candidates.
    selected_ids = list(dict.fromkeys(body.account_ids or []))
    params: list = [group_id]
    where = ("WHERE group_id=? AND enabled=1 "
             "AND (remote_status IN ('error', '错误') "
             "OR COALESCE(remote_id, '')='')")
    if selected_ids:
        where += f" AND id IN ({','.join('?' * len(selected_ids))})"
        params.extend(selected_ids)
    rows = await db.execute(
        f"""SELECT id, username, remote_status, password, totp_secret FROM accounts
           {where} ORDER BY id""",
        tuple(params))
    error_accounts = await rows.fetchall()

    if error_accounts:
        missing = [
            f"#{r['id']} {r['username']}"
            + ("（缺密码）" if not r["password"] else "")
            + ("（2FA密钥无效）" if r["totp_secret"] and not _has_valid_totp(r["totp_secret"]) else "")
            for r in error_accounts
            if not r["password"]
            or (r["totp_secret"] and not _has_valid_totp(r["totp_secret"]))
        ]
        if missing:
            raise HTTPException(
                400, "以下账号未配置密码，或2FA密钥无效（2FA可选）: " + "、".join(missing))

    if not error_accounts:
        return {"ok": True, "queued": 0, "error_count": 0, "sync": sync_result,
                "message": "同步完成，没有上游状态为「错误」或本地手动新增的启用账号，无需执行任务"}

    # step 3) enqueue only the error accounts
    error_ids = [r["id"] for r in error_accounts]
    n = await scheduler.enqueue(group_id, error_ids)
    return {"ok": True, "queued": n, "error_count": len(error_ids),
            "selected_count": len(selected_ids),
            "error_accounts": [{"id": r["id"], "username": r["username"]}
                               for r in error_accounts],
            "sync": sync_result}


class SyncBody(BaseModel):
    """Sync (pull) upstream accounts into the group.

    Identity is strictly the upstream account id (remote_id):
      - remote_id already present locally -> update UPSTREAM-owned fields only
        (display name, remark, remote_id). Local-only fields (password, TOTP,
        fingerprint, proxy, enabled...) are never touched.
      - a unique local manual row is adopted by a unique upstream email/name
        identity; its remote_id and upstream-owned fields are backfilled while
        local-only fields stay intact.
      - local row with remote_id missing upstream -> deleted (it came from sync).
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


@router.post("/{group_id}/refresh-tokens")
async def refresh_tokens(group_id: int, body: RefreshTokensBody):
    """Refresh expiring upstream tokens; candidates are selected after a sync."""
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")

    (candidates, skipped_window, skipped_invalid,
     selected_count) = await _collect_group_refresh_candidates(
        g, body.account_ids)
    candidate_ids = [row["id"] for row in candidates]
    if not candidate_ids:
        return {"ok": True, "queued": 0, "skipped_window": skipped_window,
                "skipped_invalid": skipped_invalid, "selected_count": len(selected_ids),
                "message": "没有需要刷新 Token 的启用账号"}
    if token_refresh.any_refreshing(candidate_ids):
        raise HTTPException(409, "所选账号正在刷新 Token，请稍后再试")

    if not await token_refresh.queue_refresh(candidate_ids):
        raise HTTPException(409, "已有 Token 刷新队列正在执行，请稍后再试")
    return {"ok": True, "queued": len(candidate_ids),
            "skipped_window": skipped_window, "skipped_invalid": skipped_invalid,
            "selected_count": selected_count,
            "accounts": [{"id": row["id"], "username": row["username"]}
                         for row in candidates]}


async def run_due_token_refresh():
    """Scheduled sweep: apply the batch rule to every refresh-capable group."""
    db = await database.get_db()
    groups = await (await db.execute("SELECT * FROM groups ORDER BY id")).fetchall()
    all_candidates = []
    for g in groups:
        try:
            candidates, _, _, _ = await _collect_group_refresh_candidates(g)
        except HTTPException as e:
            if token_refresh.adapter_supports_refresh(get_adapter(g["login_type"])()):
                _log.warning("group %s token sweep failed: %s", g["id"], e.detail)
            continue
        except Exception as e:
            _log.warning("group %s token sweep failed: %s", g["id"], e)
            continue
        ids = [row["id"] for row in candidates]
        # Keep IDs globally unique so one scheduled run remains one serial queue.
        if ids and not token_refresh.any_refreshing(ids) \
                and not set(ids).intersection(row["id"] for row in all_candidates):
            all_candidates.extend(candidates)

    if not all_candidates:
        return {"queued": 0}
    ids = [row["id"] for row in all_candidates]
    if token_refresh.any_refreshing(ids):
        return {"queued": 0}
    if not await token_refresh.queue_refresh(ids):
        _log.info("scheduled token refresh skipped: another queue is active")
        return {"queued": 0}
    _log.info("scheduled token refresh queued: %s account(s)", len(ids))
    return {"queued": len(ids)}


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
    if fpcheck.is_group_check_running(group_id):
        return {"ok": True, "already_running": True}
    return fpcheck.start_group_check(group_id)


@router.post("/{group_id}/fp-check/stop")
async def stop_fp_check_group(group_id: int):
    """Stop a live template check, or clear its stale checking marker."""
    db = await database.get_db()
    row = await db.execute("SELECT id FROM groups WHERE id=?", (group_id,))
    if not await row.fetchone():
        raise HTTPException(404, "group not found")
    if not await fpcheck.stop_group_check(group_id):
        raise HTTPException(409, "指纹模板检测未在执行")
    return {"ok": True, "status": fpcheck.STOP_RESULT}


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
