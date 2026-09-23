"""Accounts router: CRUD + per-account start + task history."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import database
from ..core import crypto
from ..automation import scheduler
from ..automation import fingerprint as fp_mod
from ..automation import fpcheck
from ..automation import token_refresh
from ..automation.flows import get_adapter
from ..automation.flows.adapters._util import totp_code, translate_remote_status
from .deps import require_admin

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(require_admin)])

_BUSY_MESSAGES = {
    "queued": "账号在任务队列中，请稍后再试",
    "running": "账号任务正在执行，请稍后再试",
    "token_queued": "账号在刷新 Token 队列中，请稍后再试",
    "token_running": "账号正在刷新 Token，请稍后再试",
}


def _reject_busy(status: str) -> None:
    if token_refresh.is_account_busy(status):
        raise HTTPException(409, _BUSY_MESSAGES.get(status, "账号正在运行，请稍后再试"))


def _has_valid_totp(encrypted_secret: str) -> bool:
    """Run-time TOTP precheck; an empty secret remains optional and never enters here."""
    try:
        return totp_code(crypto.decrypt(encrypted_secret)) is not None
    except Exception:
        return False


class AccountBody(BaseModel):
    group_id: int
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    totp_secret: str = ""
    browser_mode: str = Field(default="inherit", pattern="^(headless|headed|inherit)$")
    phone_platform: str = Field(default="inherit")
    fingerprint: dict | str = {}
    enabled: bool = True
    remark: str = ""
    proxy_id: int | None = Field(default=None, description="proxies.id; None/0 = direct")


class StartBody(BaseModel):
    account_ids: Optional[list[int]] = None


class BatchDeleteBody(BaseModel):
    account_ids: list[int] = Field(min_length=1)


class EnabledBody(BaseModel):
    enabled: bool


@router.get("")
async def list_accounts(group_id: Optional[int] = None):
    db = await database.get_db()
    if group_id:
        rows = await db.execute(
            """SELECT a.*, g.proxy_id AS group_proxy_id,
                      p.name AS proxy_name,
                      p.timezone AS proxy_timezone, p.country AS proxy_country,
                      p.city AS proxy_city, p.locale AS proxy_locale
               FROM accounts a
               LEFT JOIN groups g ON g.id=a.group_id
               LEFT JOIN proxies p ON p.id=COALESCE(a.proxy_id, g.proxy_id)
               WHERE a.group_id=? ORDER BY a.id DESC""", (group_id,))
    else:
        rows = await db.execute(
            """SELECT a.*, g.proxy_id AS group_proxy_id,
                      p.name AS proxy_name,
                      p.timezone AS proxy_timezone, p.country AS proxy_country,
                      p.city AS proxy_city, p.locale AS proxy_locale
               FROM accounts a
               LEFT JOIN groups g ON g.id=a.group_id
               LEFT JOIN proxies p ON p.id=COALESCE(a.proxy_id, g.proxy_id)
               ORDER BY a.id DESC""")
    out = []
    for r in await rows.fetchall():
        d = dict(r)
        d["fingerprint"] = fp_mod.sanitize(d.get("fingerprint"))
        # 凭据只暴露是否存在，用于任务执行前的前端提示；值永不回传前端。
        d["has_password"] = bool(d.pop("password", None))
        d["has_totp"] = bool(d.pop("totp_secret", ""))
        # upstream status is display-only: translate at the API layer so the
        # frontend renders the value as-is; local `enabled` is independent
        d["remote_status"] = translate_remote_status(d.get("remote_status"))
        out.append(d)
    return {"accounts": out}


@router.post("")
async def create_account(body: AccountBody):
    db = await database.get_db()
    username = body.username.strip()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (body.group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")
    # 批量粘贴常见大小写不一致；同组内按邮箱语义查重，已存在直接跳过。
    existing = await db.execute(
        "SELECT id FROM accounts WHERE group_id=? AND lower(username)=lower(?)",
        (body.group_id, username))
    old = await existing.fetchone()
    if old:
        return {"id": old["id"], "fingerprint": {}, "created": False, "exists": True}
    fp = fp_mod.sanitize(body.fingerprint)
    if not fp:
        # no explicit fingerprint: inherit the group template (seed randomized);
        # fall back to a fully random fingerprint when the group has no template
        template = g["fingerprint_template"] if "fingerprint_template" in g.keys() else "{}"
        fp = fp_mod.generate_from_template(template) if fp_mod.sanitize(template) \
            else fp_mod.generate_fingerprint()
    # proxy: 0/None => direct (NULL); a given id must exist
    proxy_id = body.proxy_id or None
    if proxy_id:
        row = await db.execute("SELECT id FROM proxies WHERE id=?", (proxy_id,))
        if not await row.fetchone():
            raise HTTPException(404, "proxy not found")
    encrypted_password = crypto.encrypt(body.password)
    encrypted_totp = crypto.encrypt(body.totp_secret.strip()) if body.totp_secret.strip() else ""
    cur = await db.execute(
        """INSERT INTO accounts(group_id,username,password,totp_secret,browser_mode,
           phone_platform,fingerprint,enabled,remark,proxy_id)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (body.group_id, username, encrypted_password, encrypted_totp,
         body.browser_mode, body.phone_platform.strip() or "inherit",
         json.dumps(fp, ensure_ascii=False),
         int(body.enabled), body.remark, proxy_id))
    await db.commit()
    return {"id": cur.lastrowid, "fingerprint": fp, "created": True, "exists": False}


@router.put("/{account_id}")
async def update_account(account_id: int, body: AccountBody):
    db = await database.get_db()
    row = await db.execute("SELECT * FROM accounts WHERE id=?", (account_id,))
    old = await row.fetchone()
    if not old:
        raise HTTPException(404, "account not found")
    group = await db.execute("SELECT id FROM groups WHERE id=?", (body.group_id,))
    if not await group.fetchone():
        raise HTTPException(404, "group not found")
    fp = fp_mod.sanitize(body.fingerprint) if body.fingerprint else fp_mod.sanitize(old["fingerprint"])
    # totp: __CLEAR__ wipes; new non-empty value encrypts; empty keeps existing (already encrypted)
    if body.totp_secret == "__CLEAR__":
        totp = ""
    elif body.totp_secret.strip():
        totp = crypto.encrypt(body.totp_secret.strip())
    else:
        totp = old["totp_secret"]  # already encrypted in DB
    # keep-old sentinel: reuse the stored (encrypted) value; new value is encrypted before write
    if body.password == "__KEEP_OLD__":
        password = old["password"]  # already encrypted in DB
    else:
        password = crypto.encrypt(body.password)
    proxy_id = body.proxy_id or None
    if proxy_id and proxy_id != old["proxy_id"]:
        row = await db.execute("SELECT id FROM proxies WHERE id=?", (proxy_id,))
        if not await row.fetchone():
            raise HTTPException(404, "proxy not found")
    await db.execute(
        """UPDATE accounts SET group_id=?,username=?,password=?,totp_secret=?,browser_mode=?,
           phone_platform=?,fingerprint=?,enabled=?,remark=?,proxy_id=? WHERE id=?""",
        (body.group_id, body.username, password, totp, body.browser_mode,
         body.phone_platform.strip() or "inherit",
         json.dumps(fp, ensure_ascii=False), int(body.enabled), body.remark,
         proxy_id, account_id))
    await db.commit()
    return {"ok": True}


@router.put("/{account_id}/enabled")
async def set_account_enabled(account_id: int, body: EnabledBody):
    db = await database.get_db()
    row = await db.execute(
        """SELECT id, last_status FROM accounts WHERE id=?""", (account_id,))
    old = await row.fetchone()
    if not old:
        raise HTTPException(404, "account not found")
    if not body.enabled:
        _reject_busy(old["last_status"])
    await db.execute("UPDATE accounts SET enabled=? WHERE id=?",
                     (int(body.enabled), account_id))
    await db.commit()
    return {"ok": True, "enabled": body.enabled}


@router.delete("/{account_id}")
async def delete_account(account_id: int):
    db = await database.get_db()
    row = await db.execute("SELECT last_status FROM accounts WHERE id=?", (account_id,))
    account = await row.fetchone()
    if not account:
        raise HTTPException(404, "account not found")
    _reject_busy(account["last_status"])
    await db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    await db.commit()
    return {"ok": True}


@router.post("/start")
async def start_accounts(body: StartBody):
    """Start one or several accounts (each in its own group's dispatcher).

    Disabled accounts (enabled=0) are rejected: they only allow edit/delete.
    """
    db = await database.get_db()
    if body.account_ids:
        marks = ",".join("?" * len(body.account_ids))
        rows = await db.execute(
            f"""SELECT a.id, a.group_id, a.enabled, a.last_status, a.username,
                       a.password, a.totp_secret, g.login_type
                FROM accounts a JOIN groups g ON g.id=a.group_id
                WHERE a.id IN ({marks})""",
            tuple(body.account_ids))
    else:
        raise HTTPException(400, "account_ids required")
    pairs, enabled_rows, blocked = [], [], 0
    for r in await rows.fetchall():
        if token_refresh.is_account_busy(r["last_status"]):
            blocked += 1
        elif r["enabled"]:
            pairs.append((r["group_id"], r["id"]))
            enabled_rows.append(dict(r))
        else:
            blocked += 1
    if not pairs:
        if blocked:
            return {"ok": True, "queued": 0, "blocked": blocked,
                    "message": "所选账号正在运行或排队，请稍后再试"}
        raise HTTPException(409, "所选账号均已停用，仅允许编辑/删除")
    if enabled_rows:
        missing = [
            f"#{r['id']} {r['username']}"
            + ("（缺密码）" if not r["password"] else "")
            + ("（2FA密钥无效）" if r["totp_secret"] and not _has_valid_totp(r["totp_secret"]) else "")
            for r in enabled_rows
            if not r["password"]
            or (r["totp_secret"] and not _has_valid_totp(r["totp_secret"]))
        ]
        if missing:
            raise HTTPException(
                400, "以下账号未配置密码，或2FA密钥无效（2FA可选）: " + "、".join(missing))

    by_group: dict[int, list[int]] = {}
    for gid, aid in pairs:
        by_group.setdefault(gid, []).append(aid)
    total = 0
    for gid, aids in by_group.items():
        total += await scheduler.enqueue(gid, aids)
    return {"ok": True, "queued": total, "blocked": blocked}


@router.post("/{account_id}/stop")
async def stop_account_run(account_id: int):
    """Stop login work only; token refresh has its own lifecycle and protections."""
    db = await database.get_db()
    row = await db.execute("SELECT id, last_status FROM accounts WHERE id=?", (account_id,))
    account = await row.fetchone()
    if not account:
        raise HTTPException(404, "account not found")
    if account["last_status"] in ("token_queued", "token_running"):
        raise HTTPException(409, "正在刷新 Token，暂不支持从这里停止")
    if account["last_status"] not in ("queued", "running"):
        raise HTTPException(409, "账号当前没有执行中的任务")
    action = await scheduler.stop_account(account_id)
    if action == "not_running":
        raise HTTPException(409, "账号当前没有执行中的任务")
    return {"ok": True, "action": action}


@router.post("/batch-delete")
async def batch_delete_accounts(body: BatchDeleteBody):
    """Delete selected accounts; refuse the whole batch if any one is running."""
    db = await database.get_db()
    account_ids = list(dict.fromkeys(body.account_ids))
    marks = ",".join("?" * len(account_ids))
    rows = await db.execute(
        f"SELECT id, username, last_status FROM accounts WHERE id IN ({marks})",
        tuple(account_ids))
    selected = await rows.fetchall()
    if not selected:
        raise HTTPException(404, "所选账号不存在")

    running = [dict(r) for r in selected if token_refresh.is_account_busy(r["last_status"])]
    if running:
        names = "、".join(f"#{r['id']} {r['username']}" for r in running)
        raise HTTPException(409, f"账号正在运行或排队，不能删除: {names}")

    deletable_ids = [r["id"] for r in selected]
    cur = await db.execute(
        f"DELETE FROM accounts WHERE id IN ({','.join('?' * len(deletable_ids))})",
        tuple(deletable_ids))
    await db.commit()
    return {
        "ok": True,
        "deleted": cur.rowcount,
        "blocked": len(running),
        "missing": len(account_ids) - len(selected),
    }


@router.post("/{account_id}/regenerate-fingerprint")
async def regenerate_fingerprint(account_id: int):
    db = await database.get_db()
    row = await db.execute("SELECT id, last_status FROM accounts WHERE id=?", (account_id,))
    account = await row.fetchone()
    if not account:
        raise HTTPException(404, "account not found")
    _reject_busy(account["last_status"])
    fp = fp_mod.generate_fingerprint()
    await db.execute("UPDATE accounts SET fingerprint=? WHERE id=?",
                     (json.dumps(fp, ensure_ascii=False), account_id))
    await db.commit()
    return {"fingerprint": fp}


@router.post("/{account_id}/fp-check")
async def fp_check(account_id: int):
    """Trigger a fingerprint risk check in a background browser task.

    Result lands on the account row (`fp_check_result`, e.g. 高风险/80);
    the frontend polls the accounts list to pick it up.
    """
    db = await database.get_db()
    row = await db.execute(
        "SELECT id, enabled, last_status FROM accounts WHERE id=?", (account_id,))
    a = await row.fetchone()
    if not a:
        raise HTTPException(404, "account not found")
    if not a["enabled"]:
        raise HTTPException(409, "账号已停用，仅允许编辑/删除")
    _reject_busy(a["last_status"])
    # gate: refuse to start when no check URL is configured (group > setting)
    url = await fpcheck.account_check_url(account_id)
    if not url:
        raise HTTPException(400, fpcheck.NO_URL_MSG)
    if fpcheck.is_account_check_running(account_id):
        raise HTTPException(409, "指纹检测正在执行，请先停止或等待完成")
    fpcheck.start_check(account_id)
    return {"ok": True, "status": "检测中"}


@router.post("/{account_id}/fp-check/stop")
async def stop_fp_check(account_id: int):
    """Stop a live fingerprint check, or clear its stale checking marker."""
    db = await database.get_db()
    row = await db.execute("SELECT id FROM accounts WHERE id=?", (account_id,))
    if not await row.fetchone():
        raise HTTPException(404, "account not found")
    if not await fpcheck.stop_account_check(account_id):
        raise HTTPException(409, "指纹检测未在执行")
    return {"ok": True, "status": fpcheck.STOP_RESULT}


@router.post("/{account_id}/refresh-token")
async def refresh_token(account_id: int):
    """Refresh one account now; the account button bypasses the 30-minute gate."""
    db = await database.get_db()
    row = await (await db.execute(
        """SELECT a.*, g.login_type, g.login_url, g.upstream_key
           FROM accounts a JOIN groups g ON g.id=a.group_id WHERE a.id=?""",
        (account_id,))).fetchone()
    if not row:
        raise HTTPException(404, "account not found")
    if not row["enabled"]:
        raise HTTPException(409, "账号已停用，仅允许编辑/删除")
    if not token_refresh.adapter_supports_refresh(
            get_adapter(row["login_type"])()):
        raise HTTPException(400, f"登录类型 {row['login_type']} 不支持刷新 Token")
    if (row["remote_status"] or "").strip() != "正常":
        raise HTTPException(409, "仅上游状态为「正常」的账号可以刷新 Token")
    if not token_refresh.has_valid_expiry(row):
        raise HTTPException(400, "账号缺少可识别的 Token 过期时间，请先同步账号")
    if token_refresh.is_account_busy(row["last_status"]):
        raise HTTPException(409, "账号正在执行任务或刷新 Token，请稍后再试")
    if token_refresh.is_active():
        raise HTTPException(409, "已有 Token 刷新队列正在执行，请稍后再试")
    if not await token_refresh.queue_refresh([account_id]):
        raise HTTPException(409, "已有 Token 刷新队列正在执行，请稍后再试")
    return {"ok": True, "status": "刷新Token队列中"}


@router.get("/{account_id}/tasks")
async def account_tasks(account_id: int, limit: int = 20):
    db = await database.get_db()
    rows = await db.execute(
        "SELECT * FROM tasks WHERE account_id=? ORDER BY id DESC LIMIT ?", (account_id, limit))
    return {"tasks": [dict(r) for r in await rows.fetchall()]}
