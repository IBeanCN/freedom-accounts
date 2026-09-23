"""SQLite (aiosqlite) access layer and schema."""
import aiosqlite
import asyncio
from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_type TEXT NOT NULL,              -- e.g. OpenAI-openai
    name TEXT NOT NULL,
    login_type TEXT NOT NULL,              -- login type
    login_url TEXT NOT NULL,               -- target URL
    upstream_key TEXT NOT NULL DEFAULT '', -- upstream key
    callback_url TEXT NOT NULL DEFAULT '', -- upstream callback URL (POST result after run)
    header_json TEXT NOT NULL DEFAULT '[]', -- custom headers for callback, JSON array [{key,value}]
    concurrency INTEGER NOT NULL DEFAULT 1,
    interval_min_ms INTEGER NOT NULL DEFAULT 5000,
    interval_max_ms INTEGER NOT NULL DEFAULT 10000,
    browser_mode TEXT NOT NULL DEFAULT 'inherit', -- headless|headed|inherit
    proxy_id INTEGER,                      -- proxies.id for the whole group; account.proxy_id overrides it
    fingerprint_template TEXT NOT NULL DEFAULT '{}', -- group-level fp template; accounts inherit it, seed randomized per account
    fp_check_url TEXT NOT NULL DEFAULT '', -- per-group override for the fingerprint-check site URL
    fp_check_result TEXT NOT NULL DEFAULT '', -- group-template check: '' | 检测中 | 高风险/80 | 失败: ...
    fp_check_at TEXT,                      -- last template-check timestamp
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    totp_secret TEXT NOT NULL DEFAULT '',  -- optional 2FA secret (base32)
    browser_mode TEXT NOT NULL DEFAULT 'inherit', -- headless|headed|inherit
    fingerprint TEXT NOT NULL DEFAULT '{}',-- JSON: fingerprint config
    enabled INTEGER NOT NULL DEFAULT 1,    -- 1=enabled; 0=disabled (only edit/delete allowed)
    proxy_id INTEGER,                      -- proxies.id; NULL = direct connection
    remote_id TEXT NOT NULL DEFAULT '',    -- upstream account id (from sync), stable across syncs
    remote_status TEXT NOT NULL DEFAULT '', -- upstream status translated to Chinese by the adapter (display-only)
    remote_remark TEXT NOT NULL DEFAULT '', -- upstream remark pulled at sync (display-only)
    token_expires_at TEXT NOT NULL DEFAULT '', -- upstream access token expiry (RFC3339/epoch)
    token_refresh_result TEXT NOT NULL DEFAULT '', -- '' | 队列中 | 刷新中 | 成功... | 失败: ...
    token_refresh_at TEXT,                 -- last refresh attempt timestamp
    fp_check_result TEXT NOT NULL DEFAULT '', -- fingerprint risk check: '' | 检测中 | 高风险/80 | 失败: ...
    fp_check_at TEXT,                      -- last check timestamp
    remark TEXT NOT NULL DEFAULT '',
    last_task_id INTEGER,
    last_status TEXT NOT NULL DEFAULT 'never', -- never|queued|running|token_queued|token_running|success|failed|cancelled
    last_message TEXT NOT NULL DEFAULT '',
    last_run_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                    -- display name, e.g. 1111
    server TEXT NOT NULL DEFAULT '',       -- full proxy url: scheme://[user:pass@]host:port
    custom_geo INTEGER NOT NULL DEFAULT 0, -- 1 = pins country/region/city/timezone for geo matching
    country TEXT NOT NULL DEFAULT '',      -- two-letter country code, e.g. US
    region TEXT NOT NULL DEFAULT '',       -- region/state, e.g. California
    city TEXT NOT NULL DEFAULT '',         -- city name
    timezone TEXT NOT NULL DEFAULT '',     -- IANA timezone, e.g. America/New_York
    locale TEXT NOT NULL DEFAULT '',       -- BCP47 locale, e.g. en-US
    exit_ip TEXT NOT NULL DEFAULT '',      -- last probe exit IP (ipify)
    latency_ms INTEGER,                    -- last probe round-trip ms
    check_at TEXT,                         -- last successful probe timestamp
    check_error TEXT NOT NULL DEFAULT '',  -- last probe error ('' = last probe ok)
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    operation TEXT NOT NULL DEFAULT 'login', -- login|token_refresh
    status TEXT NOT NULL DEFAULT 'pending', -- pending|queued|running|success|failed|callback_failed|cancelled
    browser_mode TEXT NOT NULL DEFAULT '',  -- resolved mode actually used
    fingerprint_json TEXT NOT NULL DEFAULT '{}',
    steps TEXT NOT NULL DEFAULT '[]',       -- JSON log of steps
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    callback_status TEXT NOT NULL DEFAULT 'none', -- none|ok|failed|skipped
    callback_response TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adapter_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER,                      -- groups.id at call time (not FK: groups may be deleted)
    login_type TEXT NOT NULL DEFAULT '',   -- adapter key, e.g. cpr
    action TEXT NOT NULL,                  -- list_accounts|get_account|auth_link|redeem_token|refresh_token
    ok INTEGER NOT NULL DEFAULT 1,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_adapter_logs_created ON adapter_logs(created_at);
"""

# This database predates the proxies feature: the accounts table lacks proxy_id and there is no proxies table.
_LEGACY_SCHEMA = _SCHEMA[_SCHEMA.index("CREATE TABLE IF NOT EXISTS proxies"):]

async def _migrate_proxies(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(proxies)") as cur:
        if not await cur.fetchone():
            await db.executescript(_LEGACY_SCHEMA)

_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is not None:
        return _db
    async with _db_lock:
        if _db is None:
            _db = await aiosqlite.connect(config.DB_PATH)
            _db.row_factory = aiosqlite.Row
            await _db.execute("PRAGMA journal_mode=WAL")
            await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def init_db() -> None:
    db = await get_db()
    await db.executescript(_SCHEMA)
    # lightweight migrations for pre-existing databases
    async with db.execute("PRAGMA table_info(groups)") as cur:
        cols = {r[1] for r in await cur.fetchall()}
    if "fingerprint_template" not in cols:
        await db.execute(
            "ALTER TABLE groups ADD COLUMN fingerprint_template TEXT NOT NULL DEFAULT '{}'")
    # accounts.enabled may be missing on databases created before it existed
    async with db.execute("PRAGMA table_info(accounts)") as cur:
        acols = {r[1] for r in await cur.fetchall()}
    if "enabled" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
    if "proxy_id" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN proxy_id INTEGER")
    await _migrate_proxies(db)
    async with db.execute("PRAGMA table_info(proxies)") as cur:
        pcols = {r[1] for r in await cur.fetchall()}
    if pcols and "locale" not in pcols:
        await db.execute("ALTER TABLE proxies ADD COLUMN locale TEXT NOT NULL DEFAULT ''")
    if "remote_id" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN remote_id TEXT NOT NULL DEFAULT ''")
    if "remote_status" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN remote_status TEXT NOT NULL DEFAULT ''")
    if "remote_remark" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN remote_remark TEXT NOT NULL DEFAULT ''")
    if "token_expires_at" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN token_expires_at TEXT NOT NULL DEFAULT ''")
    if "token_refresh_result" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN token_refresh_result TEXT NOT NULL DEFAULT ''")
    if "token_refresh_at" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN token_refresh_at TEXT")
    async with db.execute("PRAGMA table_info(tasks)") as cur:
        tcols = {r[1] for r in await cur.fetchall()}
    if "operation" not in tcols:
        await db.execute("ALTER TABLE tasks ADD COLUMN operation TEXT NOT NULL DEFAULT 'login'")
    # A restart cancels background workers; clear stale progress markers.
    await db.execute(
        """UPDATE accounts SET last_status='failed',
               token_refresh_result='失败: 服务重启中断'
           WHERE last_status IN ('token_queued','token_running')""")
    await db.execute(
        """UPDATE accounts SET last_status='failed', last_message='服务重启中断'
           WHERE last_status IN ('queued','running')""")
    await db.execute(
        """UPDATE tasks SET status='failed', error='服务重启中断', finished_at=
               datetime('now','localtime')
           WHERE status IN ('queued','running')""")
    if "fp_check_result" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN fp_check_result TEXT NOT NULL DEFAULT ''")
    if "fp_check_at" not in acols:
        await db.execute("ALTER TABLE accounts ADD COLUMN fp_check_at TEXT")
    async with db.execute("PRAGMA table_info(groups)") as cur:
        gcols = {r[1] for r in await cur.fetchall()}
    if "fp_check_url" not in gcols:
        await db.execute("ALTER TABLE groups ADD COLUMN fp_check_url TEXT NOT NULL DEFAULT ''")
    if "fp_check_result" not in gcols:
        await db.execute("ALTER TABLE groups ADD COLUMN fp_check_result TEXT NOT NULL DEFAULT ''")
    if "fp_check_at" not in gcols:
        await db.execute("ALTER TABLE groups ADD COLUMN fp_check_at TEXT")
    # Background checks do not survive a restart; clear their marker so the
    # start action is not permanently disabled by a stale row.
    await db.execute(
        """UPDATE accounts SET fp_check_result='失败: 服务重启中断'
           WHERE fp_check_result='检测中'""")
    await db.execute(
        """UPDATE groups SET fp_check_result='失败: 服务重启中断'
           WHERE fp_check_result='检测中'""")
    if "proxy_id" not in gcols:
        await db.execute("ALTER TABLE groups ADD COLUMN proxy_id INTEGER")
    # adapter_logs may be missing on databases created before it existed
    async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='adapter_logs'") as cur:
        if not await cur.fetchone():
            await db.executescript(_SCHEMA[_SCHEMA.index("CREATE TABLE IF NOT EXISTS adapter_logs"):])
    await db.commit()
    await _migrate_encrypt_sensitive_fields(db)


async def _migrate_encrypt_sensitive_fields(db: aiosqlite.Connection) -> None:
    """One-time migration: encrypt any plaintext credentials in existing rows."""
    from . import crypto

    # accounts.password
    rows = await db.execute(
        "SELECT id, password FROM accounts WHERE password != '' AND password NOT LIKE 'enc:%'")
    for row in await rows.fetchall():
        await db.execute("UPDATE accounts SET password=? WHERE id=?",
                         (crypto.ensure_encrypted(row["password"]), row["id"]))

    # accounts.totp_secret
    rows = await db.execute(
        "SELECT id, totp_secret FROM accounts WHERE totp_secret != '' AND totp_secret NOT LIKE 'enc:%'")
    for row in await rows.fetchall():
        await db.execute("UPDATE accounts SET totp_secret=? WHERE id=?",
                         (crypto.ensure_encrypted(row["totp_secret"]), row["id"]))

    # proxies.server
    rows = await db.execute(
        "SELECT id, server FROM proxies WHERE server != '' AND server NOT LIKE 'enc:%'")
    for row in await rows.fetchall():
        await db.execute("UPDATE proxies SET server=? WHERE id=?",
                         (crypto.ensure_encrypted(row["server"]), row["id"]))

    # groups.upstream_key
    rows = await db.execute(
        "SELECT id, upstream_key FROM groups WHERE upstream_key != '' AND upstream_key NOT LIKE 'enc:%'")
    for row in await rows.fetchall():
        await db.execute("UPDATE groups SET upstream_key=? WHERE id=?",
                         (crypto.ensure_encrypted(row["upstream_key"]), row["id"]))

    await db.commit()


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
