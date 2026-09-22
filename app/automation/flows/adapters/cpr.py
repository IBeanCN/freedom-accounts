"""CPR (codex-proxy-rs) flow adapter.

登录流程：站点登录 + 业务占位（沿用原骨架）。
凭证操作：对接 codex-proxy-rs 管理面 HTTP API（backend/crates/gateway-api）。

Upstream wire contract (verified against the codex-proxy-rs source):
  - base URL        = groups.login_url（例: https://cpr.example.com）
  - auth (primary)  = 每个请求携带 Header `x-api-key: <groups.upstream_key>`
  - auth (fallback) = POST {base}/api/auth/login {"mode":"key","apiKey":<key>}
                      → Set-Cookie: cpr_session=...（仅当 x-api-key 被 401 拒绝时回退）
  - envelope        = {code: 200, message: "OK", data: ...}；code!=200 视为业务失败
  - GET    {base}/api/admin/accounts?page=1&pageSize=50          → data.items[]
  - GET    {base}/api/admin/accounts/detail?accountId=<id>       → data.account
  - POST   {base}/api/admin/accounts/oauth/start                 → data.{flowId, authorizationUrl, expiresAt}
           body: {"provider":"openai","name":<name>,"accountId":<id|null>}
  - POST   {base}/api/admin/accounts/oauth/complete              → data.{accountId}
           body: {"provider":"openai","flowId":<fid>,"callbackUrl":<url>}
  - POST   {base}/api/admin/accounts/refresh                     → data.{account, result?, error?}
           body: {"accountId":<id>}

五个凭证操作不在页面暴露，仅写 adapter_logs。
"""
import httpx

from ....core import config
from ....core import database  # noqa: F401  (kept for parity with other adapters)
from ._util import now, totp_code
from ._log import log_action
from .base import FlowAdapter
from .password import run_login_async, run_login_sync

PROVIDER = "openai"          # CPR 管理面的 provider 维度，当前仅 openai
SESSION_COOKIE = "cpr_session"
HTTP_TIMEOUT = config.CALLBACK_TIMEOUT_SECONDS

# 上游账号状态 -> 中文（适配器层负责转换，接口/页面直接使用返回值）
REMOTE_STATUS_MAP = {
    "normal": "正常",
    "quota_exhausted": "配额耗尽",
    "rate_limited": "限流中",
    "disabled": "已停用",
    "error": "错误",
    "refresh_backoff": "退避中",
}


def translate_remote_status(raw) -> str:
    """上游状态枚举转中文；未知值原样返回，空值返回空串。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    return REMOTE_STATUS_MAP.get(s, s)


# ---------------- wire helpers ----------------
def _base_url(group: dict) -> str:
    return (group["login_url"] or "").strip().rstrip("/")


def _api_key(group: dict) -> str:
    return (group["upstream_key"] or "").strip()


def _unwrap(envelope: dict) -> dict:
    """CPR envelope: {code:200, message:'OK', data:...}; non-200 => failure."""
    if not isinstance(envelope, dict):
        raise RuntimeError("CPR: unexpected non-object response")
    code = envelope.get("code")
    if code != 200:
        raise RuntimeError(f"CPR: business code {code}: {envelope.get('message', '')[:200]}")
    return envelope.get("data") or {}


async def _login_session(base: str, api_key: str, client: httpx.AsyncClient) -> None:
    """Key-mode login; the session cookie lands in client.cookies."""
    resp = await client.post(f"{base}/api/auth/login",
                             json={"mode": "key", "apiKey": api_key})
    if resp.status_code >= 400:
        raise RuntimeError(f"CPR login failed: HTTP {resp.status_code}: {resp.text[:200]}")
    _unwrap(resp.json())
    if SESSION_COOKIE not in client.cookies:
        raise RuntimeError("CPR login did not issue a session cookie")


async def _api_call(group: dict, method: str, path: str,
                    *, params: dict | None = None, json_body: dict | None = None) -> dict:
    """One authenticated admin-API roundtrip; returns unwrapped data.

    Auth strategy: send `x-api-key` header first (upstream contract);
    if the server answers 401, fall back to session-cookie login once.
    """
    base = _base_url(group)
    if not base:
        raise RuntimeError("CPR: group.login_url (upstream base URL) is empty")
    api_key = _api_key(group)
    if not api_key:
        raise RuntimeError("CPR: group.upstream_key (API Key) is empty")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.request(method, f"{base}{path}", params=params,
                                    json=json_body,
                                    headers={"x-api-key": api_key})
        if resp.status_code == 401:
            # header key rejected -> fall back to session-cookie login
            await _login_session(base, api_key, client)
            resp = await client.request(method, f"{base}{path}",
                                        params=params, json=json_body)
        if resp.status_code >= 400:
            raise RuntimeError(f"CPR {method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return _unwrap(resp.json())


# ---------------- sync flavor ----------------
def run_cpr_sync(ctx, username: str, password: str, totp_secret: str,
                 login_url: str, steps: list) -> dict:
    result = run_login_sync(ctx, username, password, totp_secret, login_url, steps)

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    steps.append({"t": now(), "step": "cpr_enter", "detail": page.url, "ok": True})
    # TODO(CPR): 按真实站点实现业务流程（页面导航/表单/结果提取）
    result["cpr"] = {"entered": True, "note": "business flow placeholder"}
    return result


# ---------------- async flavor ----------------
async def run_cpr_async(ctx, username: str, password: str, totp_secret: str,
                        login_url: str, steps: list) -> dict:
    result = await run_login_async(ctx, username, password, totp_secret, login_url, steps)

    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    steps.append({"t": now(), "step": "cpr_enter", "detail": page.url, "ok": True})
    # TODO(CPR): 按真实站点实现
    result["cpr"] = {"entered": True, "note": "business flow placeholder"}
    return result


# ---------------- adapter ----------------
class CprAdapter(FlowAdapter):
    key = "cpr"
    label = "CPR（codex-proxy-rs）"
    description = "登录 CPR 站点；凭证操作对接 codex-proxy-rs 管理 API（仅记日志）"
    run_sync = staticmethod(run_cpr_sync)
    run_async = staticmethod(run_cpr_async)

    # ---- credential operations (log-only, never exposed on the web) ----

    async def list_accounts(self, group: dict) -> dict:
        try:
            data = await _api_call(group, "GET", "/api/admin/accounts",
                                   params={"page": 1, "pageSize": 50})
            items = data.get("items") or []
            summary = {
                "total": (data.get("page") or {}).get("total", len(items)),
                "accounts": [
                    {"id": it.get("id"),
                     "name": it.get("name"),
                     "email": it.get("email"),
                     "status": it.get("status"),
                     # 中文状态直接由适配器转换，接口/页面展示即用
                     "status_label": translate_remote_status(it.get("status")),
                     "enabled": it.get("enabled"),
                     "plan_type": it.get("planType"),
                     "remark": it.get("remark") or it.get("note") or ""}
                    for it in items],
            }
            await log_action(group["id"], self.key, "list_accounts", True,
                             f"total={summary['total']}")
            return summary
        except Exception as e:
            await log_action(group["id"], self.key, "list_accounts", False, str(e))
            raise

    async def get_account(self, group: dict, remote_account_id: str) -> dict:
        try:
            data = await _api_call(group, "GET", "/api/admin/accounts/detail",
                                   params={"accountId": remote_account_id})
            account = data.get("account") or {}
            summary = {
                "id": account.get("id"),
                "name": account.get("name"),
                "email": account.get("email"),
                "status": account.get("status"),
                "status_label": translate_remote_status(account.get("status")),
                "plan_type": account.get("planType"),
                "access_token_expires_at": account.get("accessTokenExpiresAt"),
                "has_refresh_token": account.get("hasRefreshToken"),
            }
            await log_action(group["id"], self.key, "get_account", True,
                             f"accountId={remote_account_id} status={summary['status']}")
            return summary
        except Exception as e:
            await log_action(group["id"], self.key, "get_account", False,
                             f"accountId={remote_account_id}: {e}")
            raise

    async def auth_link(self, group: dict, name: str,
                        remote_account_id: str | None = None) -> dict:
        try:
            body: dict = {"provider": PROVIDER, "name": name or "freedom-accounts"}
            if remote_account_id:
                body["accountId"] = remote_account_id
            data = await _api_call(group, "POST", "/api/admin/accounts/oauth/start",
                                   json_body=body)
            result = {"flow_id": data.get("flowId"),
                      "url": data.get("authorizationUrl"),
                      "expires_at": data.get("expiresAt")}
            await log_action(group["id"], self.key, "auth_link", True,
                             f"flowId={result['flow_id']}")
            return result
        except Exception as e:
            await log_action(group["id"], self.key, "auth_link", False, str(e))
            raise

    async def redeem_token(self, group: dict, flow_id: str, callback_url: str) -> dict:
        try:
            data = await _api_call(group, "POST", "/api/admin/accounts/oauth/complete",
                                   json_body={"provider": PROVIDER,
                                              "flowId": flow_id,
                                              "callbackUrl": callback_url})
            account_id = data.get("accountId")
            await log_action(group["id"], self.key, "redeem_token", True,
                             f"flowId={flow_id} -> accountId={account_id}")
            return {"account_id": account_id}
        except Exception as e:
            await log_action(group["id"], self.key, "redeem_token", False,
                             f"flowId={flow_id}: {e}")
            raise

    async def refresh_token(self, group: dict, remote_account_id: str) -> dict:
        try:
            data = await _api_call(group, "POST", "/api/admin/accounts/refresh",
                                   json_body={"accountId": remote_account_id})
            result = {"account_id": (data.get("account") or {}).get("accountId")
                      or remote_account_id,
                      "result": data.get("result"),
                      "error": data.get("error")}
            ok = not result["error"]
            await log_action(group["id"], self.key, "refresh_token", ok,
                             f"accountId={remote_account_id} result={result['result']} err={result['error']}")
            return result
        except Exception as e:
            await log_action(group["id"], self.key, "refresh_token", False,
                             f"accountId={remote_account_id}: {e}")
            raise
