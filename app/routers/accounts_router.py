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
from ..automation.flows.adapters._util import translate_remote_status
from .deps import require_admin

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(require_admin)])


class AccountBody(BaseModel):
    group_id: int
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    totp_secret: str = ""
    browser_mode: str = Field(default="inherit", pattern="^(headless|headed|inherit)$")
    fingerprint: dict | str = {}
    enabled: bool = True
    remark: str = ""
    proxy_id: int | None = Field(default=None, description="proxies.id; None/0 = direct")


class StartBody(BaseModel):
    account_ids: Optional[list[int]] = None


class EnabledBody(BaseModel):
    enabled: bool


@router.get("")
async def list_accounts(group_id: Optional[int] = None):
    db = await database.get_db()
    if group_id:
        rows = await db.execute(
            """SELECT a.*, p.name AS proxy_name,
                      p.timezone AS proxy_timezone, p.country AS proxy_country,
                      p.city AS proxy_city, p.locale AS proxy_locale
               FROM accounts a LEFT JOIN proxies p ON p.id=a.proxy_id
               WHERE a.group_id=? ORDER BY a.id DESC""", (group_id,))
    else:
        rows = await db.execute(
            """SELECT a.*, p.name AS proxy_name,
                      p.timezone AS proxy_timezone, p.country AS proxy_country,
                      p.city AS proxy_city, p.locale AS proxy_locale
               FROM accounts a LEFT JOIN proxies p ON p.id=a.proxy_id
               ORDER BY a.id DESC""")
    out = []
    for r in await rows.fetchall():
        d = dict(r)
        d["fingerprint"] = fp_mod.sanitize(d.get("fingerprint"))
        d.pop("password", None)      # never return passwords to the frontend
        d["has_totp"] = bool(d.pop("totp_secret", ""))
        # upstream status is display-only: translate at the API layer so the
        # frontend renders the value as-is; local `enabled` is independent
        d["remote_status"] = translate_remote_status(d.get("remote_status"))
        out.append(d)
    return {"accounts": out}


@router.post("")
async def create_account(body: AccountBody):
    db = await database.get_db()
    g = await (await db.execute("SELECT * FROM groups WHERE id=?", (body.group_id,))).fetchone()
    if not g:
        raise HTTPException(404, "group not found")
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
           fingerprint,enabled,remark,proxy_id)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (body.group_id, body.username, encrypted_password, encrypted_totp,
         body.browser_mode, json.dumps(fp, ensure_ascii=False),
         int(body.enabled), body.remark, proxy_id))
    await db.commit()
    return {"id": cur.lastrowid, "fingerprint": fp}


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
           fingerprint=?,enabled=?,remark=?,proxy_id=? WHERE id=?""",
        (body.group_id, body.username, password, totp, body.browser_mode,
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
    if not body.enabled and old["last_status"] == "running":
        raise HTTPException(409, "账号正在运行，不能停用")
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
    if account["last_status"] == "running":
        raise HTTPException(409, "账号正在运行，不能删除")
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
            f"SELECT id, group_id, enabled FROM accounts WHERE id IN ({marks})",
            tuple(body.account_ids))
    else:
        raise HTTPException(400, "account_ids required")
    pairs, blocked = [], 0
    for r in await rows.fetchall():
        if r["enabled"]:
            pairs.append((r["group_id"], r["id"]))
        else:
            blocked += 1
    if not pairs:
        raise HTTPException(409, "所选账号均已停用，仅允许编辑/删除")
    by_group: dict[int, list[int]] = {}
    for gid, aid in pairs:
        by_group.setdefault(gid, []).append(aid)
    total = 0
    for gid, aids in by_group.items():
        total += await scheduler.enqueue(gid, aids)
    return {"ok": True, "queued": total, "blocked": blocked}


@router.post("/{account_id}/regenerate-fingerprint")
async def regenerate_fingerprint(account_id: int):
    db = await database.get_db()
    row = await db.execute("SELECT id FROM accounts WHERE id=?", (account_id,))
    if not await row.fetchone():
        raise HTTPException(404, "account not found")
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
    # gate: refuse to start when no check URL is configured (group > setting)
    url = await fpcheck.account_check_url(account_id)
    if not url:
        raise HTTPException(400, fpcheck.NO_URL_MSG)
    fpcheck.start_check(account_id)
    return {"ok": True, "status": "检测中"}


@router.get("/{account_id}/tasks")
async def account_tasks(account_id: int, limit: int = 20):
    db = await database.get_db()
    rows = await db.execute(
        "SELECT * FROM tasks WHERE account_id=? ORDER BY id DESC LIMIT ?", (account_id, limit))
    return {"tasks": [dict(r) for r in await rows.fetchall()]}
