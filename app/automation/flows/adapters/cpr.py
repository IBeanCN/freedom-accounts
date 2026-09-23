"""CPR (codex-proxy-rs) flow adapter.

任务 flow = 纯编排（auth_link → 共享浏览器授权段 → redeem_token），
浏览器操作零上游耦合；上游差异集中在凭证操作（管理面 HTTP API）。

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

五个凭证操作只写 adapter_logs；refresh_token 可由账号页面 API 触发，其余仍为内部调用。
"""
import httpx

from ....core import config
from ....core import database  # noqa: F401  (kept for parity with other adapters)
from ._util import now, translate_remote_status
from ._log import log_action
from ._openai_browser import run_browser_auth, is_localhost
from .base import FlowAdapter

PROVIDER = "openai"          # CPR 管理面的 provider 维度，当前仅 openai
SESSION_COOKIE = "cpr_session"
HTTP_TIMEOUT = max(30.0, float(config.CALLBACK_TIMEOUT_SECONDS))
LIST_PAGE_SIZE = 50

# 上游账号状态 -> 中文（适配器层负责转换，接口/页面直接使用返回值）
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


def _items(data: dict) -> list:
    items = data.get("items")
    return items if isinstance(items, list) else []


def _item_id(item: dict):
    return item.get("id") if item.get("id") is not None else item.get("account_id")


async def _list_items(group: dict) -> list:
    """Fetch all account pages; a partial read would make sync delete rows."""
    items: list = []
    seen: set[str] = set()
    max_pages = 100
    for page in range(1, max_pages + 1):
        data = await _api_call(
            group, "GET", "/api/admin/accounts",
            params={"page": page, "pageSize": LIST_PAGE_SIZE})
        page_items = _items(data)
        for item in page_items:
            item_id = str(_item_id(item))
            if item_id not in seen:
                seen.add(item_id)
                items.append(item)
        if len(page_items) < LIST_PAGE_SIZE:
            return items
    raise RuntimeError(f"CPR: 上游账号分页超过 {max_pages} 页，已停止同步以避免误删")


# ---------------- sync flavor (unsupported) ----------------
def run_cpr_sync(ctx, username: str, password: str, totp_secret: str,
                 login_url: str, steps: list, group: dict | None = None,
                 account: dict | None = None) -> dict:
    steps.append({"t": now(), "step": "cpr_unsupported",
                  "detail": "OAuth 授权流程仅支持异步引擎", "ok": False})
    raise RuntimeError("CPR（OpenAI 授权任务）仅支持异步引擎（scheduler 当前均为 async）")


# ---------------- async flavor: 编排（共享浏览器段） ----------------
async def run_cpr_async(ctx, username: str, password: str, totp_secret: str,
                        login_url: str, steps: list,
                        group: dict | None = None,
                        account: dict | None = None,
                        cdp_engine: bool = False,
                        phone_handler=None) -> dict:
    """编排: auth_link（oauth/start） → 浏览器授权（共享段） → redeem_token（oauth/complete）."""
    group = dict(group or {})
    remote_id = str((account or {}).get("remote_id") or "").strip() or None

    # 1) 上游段: 拿授权链接（CPR 管理 API oauth/start）
    link = await CprAdapter().auth_link(group, name=username, remote_account_id=remote_id)
    steps.append({"t": now(), "step": "auth_url",
                  "detail": str(link.get("url") or "")[:300], "ok": True})

    # 2) 通用浏览器授权段（全适配器共享，与上游无关）
    auth = await run_browser_auth(ctx, link["url"], username, password,
                                  totp_secret, steps, cdp_engine=cdp_engine,
                                  phone_handler=phone_handler)

    # 3) 上游段: 兑换凭证（oauth/complete，exchange 成功即授权完成）
    await CprAdapter().redeem_token(group, link["flow_id"], auth["callback_url"])

    return {"authorized": True, "upstream_email": username,
            "flow_id": link["flow_id"],
            "callback_url": auth["callback_url"], "url": auth["callback_url"]}


# ---------------- adapter ----------------
class CprAdapter(FlowAdapter):
    key = "cpr"
    label = "CPR（codex-proxy-rs）"
    description = "指纹浏览器完成 OpenAI OAuth 授权；凭证操作对接 codex-proxy-rs 管理 API（仅记日志）"
    run_sync = staticmethod(run_cpr_sync)
    run_async = staticmethod(run_cpr_async)

    # ---- credential operations (log-only, never exposed on the web) ----

    async def list_accounts(self, group: dict) -> dict:
        try:
            items = await _list_items(group)
            summary = {
                "total": len(items),
                "accounts": [
                    {"id": it.get("id"),
                     "name": it.get("name"),
                     "email": it.get("email"),
                     "status": it.get("status"),
                     # 中文状态直接由适配器转换，接口/页面展示即用
                     "status_label": translate_remote_status(it.get("status")),
                     "enabled": it.get("enabled"),
                     "plan_type": it.get("planType"),
                     "access_token_expires_at": it.get("accessTokenExpiresAt"),
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

    async def redeem_token(self, group: dict, flow_id: str, callback_url: str,
                           remote_account_id: str | None = None) -> dict:
        """flow_id = oauth/start 的 flowId；callback_url = 浏览器段的 localhost 回调地址。"""
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
            account = data.get("account") or {}
            result = {"account_id": account.get("accountId")
                      or remote_account_id,
                      "access_token_expires_at": account.get("accessTokenExpiresAt"),
                      "status_label": translate_remote_status(account.get("status")),
                      "result": data.get("result"),
                      "error": data.get("error")}
            ok = not result["error"]
            await log_action(group["id"], self.key, "refresh_token", ok,
                             f"accountId={remote_account_id} result={result['result']} "
                             f"expiresAt={result['access_token_expires_at']} err={result['error']}")
            return result
        except Exception as e:
            await log_action(group["id"], self.key, "refresh_token", False,
                             f"accountId={remote_account_id}: {e}")
            raise
