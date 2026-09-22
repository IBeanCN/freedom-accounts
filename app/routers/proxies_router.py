"""Proxies router: CRUD + connectivity probe (exit IP & latency via ipify).

The probe sends the request THROUGH the configured proxy with
``trust_env=False`` so system-level proxy env vars cannot interfere,
then asks ipify (https://www.ipify.org) for the observed exit IP.
"""
import asyncio
import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import database
from .deps import require_admin

router = APIRouter(prefix="/api/proxies", tags=["proxies"],
                   dependencies=[Depends(require_admin)])

# scheme://[user:pass@]host:port — user/pass optional
_PROXY_RE = re.compile(
    r"^(?P<scheme>(https?|socks5h?|tls?)://)?"
    r"(?P<auth>[^/@\s]+:[^/@\s]+@)?"
    r"(?P<host>[^/@\s:]+):(?P<port>\d{1,5})/?$"
)
# Exit-IP echo services, tried in order. ipify first; ipwho.is as fallback —
# some exit lines (e.g. HK relay) cannot reach ipify at all.
_IP_ECHO_ENDPOINTS = (
    "https://api.ipify.org?format=json",   # {"ip": "..."}
    "https://ipwho.is/",                   # {"ip": "..."}
)


def _normalize_server(raw: str) -> str:
    """Validate and normalize a proxy URL; add http:// when the scheme is absent."""
    s = (raw or "").strip()
    if not s:
        raise HTTPException(400, "代理地址不能为空")
    if not _PROXY_RE.match(s):
        raise HTTPException(400, "代理地址格式无效，应为 协议://用户名:密码@主机:端口")
    if "://" not in s:
        s = "http://" + s
    return s


def _mask_server(server: str) -> str:
    """Display form: keep scheme/host/port, mask the credential section."""
    def repl(m: re.Match) -> str:
        return (m.group("scheme") or "") + "******:******@" + m.group("host") + ":" + m.group("port")
    return re.sub(
        r"(?P<scheme>(?:https?|socks5h?|tls?)://)?(?P<user>[^/@\s]+):(?P<pass>[^/@\s]+)@",
        lambda m: (m.group("scheme") or "") + "******:******@",
        server or "",
    )


class ProxyBody(BaseModel):
    name: str = Field(min_length=1, description="display name")
    server: str = Field(default="", description="scheme://[user:pass@]host:port")
    custom_geo: bool = Field(default=False, description="pin country/region/city/timezone")
    country: str = Field(default="", max_length=2, description="two-letter country code")
    region: str = ""
    city: str = ""
    timezone: str = ""
    locale: str = Field(default="", description="BCP47 locale, e.g. en-US")


async def probe(server: str, timeout: float = 15.0) -> dict:
    """Fetch the exit IP through the proxy. Returns {ok, exit_ip, latency_ms, error}.

    Tries ipify first, then ipwho.is — some exit lines (e.g. HK relay) cannot
    reach ipify at all, which used to fail the whole probe on a working proxy.
    """
    try:
        client = httpx.AsyncClient(proxy=server, timeout=timeout, trust_env=False)
    except TypeError:  # httpx < 0.26 keyword
        client = httpx.AsyncClient(proxies=server, timeout=timeout, trust_env=False)
    t0 = time.perf_counter()
    last_err = ""
    try:
        async with client:
            for endpoint in _IP_ECHO_ENDPOINTS:
                try:
                    r = await client.get(endpoint)
                    r.raise_for_status()
                    ip = str((r.json() or {}).get("ip") or "").strip()
                    if ip:
                        return {"ok": True, "exit_ip": ip,
                                "latency_ms": int((time.perf_counter() - t0) * 1000)}
                    last_err = "出口 IP 接口未返回 IP"
                except Exception as e:
                    last_err = str(e) or e.__class__.__name__
        return {"ok": False, "error": last_err or "连接失败"}
    except httpx.InvalidURL as e:
        return {"ok": False, "error": f"代理地址无效: {e}"}
    except httpx.UnsupportedProtocol as e:
        return {"ok": False, "error": f"不支持的代理协议（socks 需 httpx[socks]）: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e) or e.__class__.__name__}


def _row_dict(r) -> dict:
    d = dict(r)
    d["custom_geo"] = bool(d.get("custom_geo"))
    d["server_masked"] = _mask_server(d.get("server") or "")
    d["linked_accounts"] = d.pop("linked_accounts", 0) or 0
    d["testing"] = False
    return d


@router.get("")
async def list_proxies():
    db = await database.get_db()
    rows = await db.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM accounts a WHERE a.proxy_id=p.id) AS linked_accounts
           FROM proxies p ORDER BY p.id DESC""")
    return {"proxies": [_row_dict(r) for r in await rows.fetchall()]}


@router.post("")
async def create_proxy(body: ProxyBody):
    server = _normalize_server(body.server)
    db = await database.get_db()
    cur = await db.execute(
        """INSERT INTO proxies(name,server,custom_geo,country,region,city,timezone,locale)
           VALUES(?,?,?,?,?,?,?,?)""",
        (body.name.strip(), server, int(body.custom_geo),
         body.country.strip().upper(), body.region.strip(),
         body.city.strip(), body.timezone.strip(), body.locale.strip()))
    await db.commit()
    return {"id": cur.lastrowid}


@router.put("/{proxy_id}")
async def update_proxy(proxy_id: int, body: ProxyBody):
    db = await database.get_db()
    row = await db.execute("SELECT id, server FROM proxies WHERE id=?", (proxy_id,))
    old = await row.fetchone()
    if not old:
        raise HTTPException(404, "proxy not found")
    # keep the stored address when the form submits an empty one
    server = _normalize_server(body.server) if body.server.strip() else old["server"]
    await db.execute(
        """UPDATE proxies SET name=?,server=?,custom_geo=?,country=?,region=?,city=?,timezone=?,locale=?
           WHERE id=?""",
        (body.name.strip(), server, int(body.custom_geo),
         body.country.strip().upper(), body.region.strip(),
         body.city.strip(), body.timezone.strip(), body.locale.strip(), proxy_id))
    await db.commit()
    return {"ok": True}


@router.delete("/{proxy_id}")
async def delete_proxy(proxy_id: int):
    db = await database.get_db()
    row = await db.execute("SELECT id FROM proxies WHERE id=?", (proxy_id,))
    if not await row.fetchone():
        raise HTTPException(404, "proxy not found")
    n = await (await db.execute("SELECT COUNT(*) FROM accounts WHERE proxy_id=?", (proxy_id,))).fetchone()
    if (n and n[0]) > 0:
        raise HTTPException(409, f"该代理仍被 {n[0]} 个账号关联，请先解除关联")
    await db.execute("DELETE FROM proxies WHERE id=?", (proxy_id,))
    await db.commit()
    return {"ok": True}


@router.post("/{proxy_id}/test")
async def test_proxy(proxy_id: int):
    """Probe connectivity through the stored proxy address (background run).

    Result lands on the proxy row (exit_ip / latency_ms / check_at /
    check_error); the frontend polls the list to pick it up.
    """
    db = await database.get_db()
    row = await db.execute("SELECT id, server FROM proxies WHERE id=?", (proxy_id,))
    p = await row.fetchone()
    if not p:
        raise HTTPException(404, "proxy not found")
    server = p["server"]
    probe_bg(proxy_id, server)
    return {"ok": True, "status": "检测中"}


def probe_bg(proxy_id: int, server: str) -> None:
    """Fire the probe as a fire-and-forget task writing results back."""
    async def _run():
        db = await database.get_db()
        result = await probe(server)
        await db.execute(
            """UPDATE proxies SET exit_ip=?, latency_ms=?, check_at=?, check_error=?
               WHERE id=?""",
            (result.get("exit_ip", ""),
             result.get("latency_ms"),
             time.strftime("%Y-%m-%d %H:%M:%S"),
             "" if result["ok"] else result.get("error", "连接失败"),
             proxy_id))
        await db.commit()
    asyncio.get_running_loop().create_task(_run())
