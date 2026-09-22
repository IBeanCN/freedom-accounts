"""Adapter operation logging.

Every adapter credential operation (list_accounts / get_account / auth_link /
redeem_token / refresh_token) writes exactly one row here. Rows are NOT
exposed through any HTTP endpoint — they are for internal auditing only and
are pruned by the retention job (see core/maintenance.py).
"""
from ....core import database


async def log_action(group_id: int, login_type: str, action: str,
                     ok: bool, detail: str = "") -> None:
    """Append one adapter-operation audit row; never raises."""
    try:
        db = await database.get_db()
        await db.execute(
            "INSERT INTO adapter_logs(group_id, login_type, action, ok, detail, created_at) "
            "VALUES(?,?,?,?,?, datetime('now','localtime'))",
            (group_id, login_type, action, 1 if ok else 0, str(detail)[:2000]))
        await db.commit()
    except Exception:
        # logging must never break the operation itself
        pass
