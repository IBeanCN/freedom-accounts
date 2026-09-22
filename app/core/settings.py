"""Runtime settings stored in the settings table (admin password, global browser mode...)."""
from ..core import config, database, auth

SETTING_DEFAULTS = {
    "admin_password_hash": "",          # empty => bootstrap from INITIAL_ADMIN_PASSWORD
    "global_browser_mode": "headless",  # headless | headed
    "cloak_cdp_url": "",                # cloakserve CDP endpoint, e.g. http://127.0.0.1:9222
    "log_retention_days": "3",          # adapter_logs & task logs older than this are pruned
    "fp_check_url": "https://fuck-claude.com/zh/",  # fingerprint risk-check site; group may override
    # global geo defaults: prefilled into the proxy form when "自定义时区位置"
    # is switched on; manually editable or auto-filled from exit-IP lookup
    "default_geo_country": "",
    "default_geo_region": "",
    "default_geo_city": "",
    "default_geo_timezone": "",
    "default_geo_locale": "",
}

_CACHE: dict[str, str] = {}


async def init_settings() -> None:
    db = await database.get_db()
    for key, default in SETTING_DEFAULTS.items():
        row = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        found = await row.fetchone()
        if found is None:
            value = default
            if key == "admin_password_hash" and not default:
                value = auth.hash_password(config.INITIAL_ADMIN_PASSWORD)
            await db.execute("INSERT INTO settings(key,value) VALUES(?,?)", (key, value))
    # Docker: auto-fill cloak_cdp_url when env FA_CDP_URL is set and DB is empty
    if config.FA_CDP_URL:
        row = await db.execute("SELECT value FROM settings WHERE key='cloak_cdp_url'")
        existing = await row.fetchone()
        if existing is not None and not (existing["value"] or "").strip():
            await db.execute(
                "UPDATE settings SET value=? WHERE key='cloak_cdp_url'",
                (config.FA_CDP_URL,))
    await db.commit()
    await refresh_cache()


async def refresh_cache() -> None:
    db = await database.get_db()
    async with db.execute("SELECT key,value FROM settings") as cur:
        rows = await cur.fetchall()
    _CACHE.clear()
    _CACHE.update({r["key"]: r["value"] for r in rows})


async def get(key: str) -> str:
    if key not in _CACHE:
        await refresh_cache()
    return _CACHE.get(key, "")


async def set_value(key: str, value: str) -> None:
    db = await database.get_db()
    await db.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    await db.commit()
    _CACHE[key] = value
