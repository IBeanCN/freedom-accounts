"""sub2api flow adapter — OpenAI 授权任务.

任务 flow = 纯编排，浏览器操作零上游耦合：
  1. auth_link（上游段）: POST /openai/generate-auth-url {account_id}
     → {flow_id=session_id, url=auth_url, account_id}
  2. 通用浏览器授权段（_openai_browser.run_browser_auth，全适配器共享）
  3. redeem_token（上游段）: POST /openai/exchange-code {code, state, session_id}
     成功后 best-effort 恢复账号 recover-state / schedulable

上游 wire contract（对照 s2accheck 插件验证）:
  - base URL   = groups.login_url（站点根），API 前缀固定 /api/v1/admin
                 （login_url 已带前缀则原样使用）
  - auth       = 每个请求携带 Header `x-api-key: <groups.upstream_key>`
  - 响应形状宽容: data.data.X / data.X / data 为数组均可；业务错误判定
    error / data.error / success===false
  - 上游账号按 email 与本地账号 username 匹配（remote_id 缺失时兜底）

凭证操作（log-only）: list_accounts / get_account / auth_link / redeem_token
已实现；refresh_token 未实现（上游未见对应端点）。

同步版 run_sync 不支持: OAuth 流程依赖原生 async 引擎（scheduler 全为 async）。
"""
import asyncio
import random

import httpx

from ....core import config
from ._util import now, translate_remote_status
from ._log import log_action
from ._openai_browser import run_browser_auth, parse_callback
from .base import FlowAdapter

API_PREFIX = "/api/v1/admin"
HTTP_TIMEOUT = max(30.0, float(config.CALLBACK_TIMEOUT_SECONDS))
EXCHANGE_RETRIES = 5             # exchange-code 失败重试次数

# 上游账号状态 -> 中文（与 cpr 适配器同一套语义）
# ---------------- wire helpers ----------------
def _api_base(login_url: str) -> str:
    base = (login_url or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("sub2api: 分组 login_url（上游站点地址）为空")
    return base if base.endswith(API_PREFIX) else base + API_PREFIX


def _api_key(group: dict | None) -> str:
    key = ((group or {}).get("upstream_key") or "").strip()
    if not key:
        raise RuntimeError("sub2api: 分组 upstream_key（上游 API Key）为空，请先在分组设置填写")
    return key


def _unwrap(data):
    """宽容解析响应：剔除 envelope，业务错误抛 RuntimeError。"""
    if not isinstance(data, dict):
        return data
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    err = data.get("error") or inner.get("error")
    if not err and data.get("success") is False:
        err = data.get("message") or "success=false"
    if err:
        raise RuntimeError(f"sub2api 上游业务错误: {str(err)[:200]}")
    return data.get("data") if isinstance(data.get("data"), (dict, list)) else data


async def _request(api: str, key: str, method: str, path: str,
                   *, json_body: dict | None = None,
                   params: dict | None = None):
    """一次带 x-api-key 的上游请求，返回解包后的 data。"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.request(method, f"{api}{path}", json=json_body,
                                    params=params, headers={"x-api-key": key})
    if resp.status_code >= 400:
        raise RuntimeError(f"sub2api {method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return _unwrap(resp.json())
    except ValueError:
        return {}


def _extract_items(data) -> list:
    """上游账号列表响应形状宽容提取（对照插件 fetchErrorAccounts）。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("items"), list):
            return inner["items"]
        if isinstance(inner, list):
            return inner
        if isinstance(data.get("items"), list):
            return data["items"]
    return []


def _item_id(it: dict):
    return it.get("id") if it.get("id") is not None else it.get("account_id")


async def _list_items(api: str, key: str, page_size: int = 100) -> list:
    """Fetch every account page; partial reads would make sync delete rows."""
    items: list = []
    seen: set[str] = set()
    max_pages = 100
    for page in range(1, max_pages + 1):
        data = await _request(api, key, "GET", "/accounts",
                              params={"page": page, "page_size": page_size,
                                      "sort_by": "name", "sort_order": "asc"})
        page_items = _extract_items(data)
        for item in page_items:
            item_id = str(_item_id(item))
            if item_id not in seen:
                seen.add(item_id)
                items.append(item)
        if len(page_items) < page_size:
            return items
    raise RuntimeError(f"sub2api: 上游账号分页超过 {max_pages} 页，已停止同步以避免误删")


def _match_account(items: list, email: str) -> dict:
    u = (email or "").strip().lower()
    for it in items:
        up = str(it.get("email") or it.get("name") or "").strip().lower()
        if up and up == u:
            return it
    raise RuntimeError(
        f"sub2api: 上游未找到邮箱为 {email} 的账号，请先在分组页执行「同步账号」")


# ---------------- 上游段：拿授权链接 ----------------
async def _auth_link(group: dict, email: str,
                     remote_account_id: str | None = None) -> dict:
    api, key = _api_base(group.get("login_url") or ""), _api_key(group)
    account_id = remote_account_id
    if not account_id:
        items = await _list_items(api, key)
        account_id = _item_id(_match_account(items, email))
    if account_id is None:
        raise RuntimeError("上游账号缺少 id，无法发起授权")
    data = await _request(api, key, "POST", "/openai/generate-auth-url",
                          json_body={"account_id": account_id}) or {}
    result = {"flow_id": data.get("session_id"),
              "url": data.get("auth_url"),
              "expires_at": None,
              "account_id": account_id}
    if not result["flow_id"] or not result["url"]:
        raise RuntimeError("generate-auth-url 未返回 auth_url/session_id")
    return result


# ---------------- 上游段：兑换凭证（含重试） ----------------
async def _exchange(api: str, key: str, code: str, state: str,
                    session_id: str, steps: list | None) -> dict:
    last: Exception | None = None
    for attempt in range(1, EXCHANGE_RETRIES + 1):
        try:
            data = await _request(api, key, "POST", "/openai/exchange-code",
                                  json_body={"code": code, "state": state,
                                             "session_id": session_id})
            if steps is not None:
                steps.append({"t": now(), "step": "exchange_code",
                              "detail": f"attempt {attempt}/{EXCHANGE_RETRIES} ok", "ok": True})
            return data
        except Exception as e:
            last = e
            if steps is not None:
                steps.append({"t": now(), "step": "exchange_code",
                              "detail": f"attempt {attempt}/{EXCHANGE_RETRIES} 失败: {str(e)[:150]}",
                              "ok": False})
            if attempt < EXCHANGE_RETRIES:
                await asyncio.sleep(random.uniform(5, 10))
    raise last if last else RuntimeError("exchange-code 未知失败")


async def _recover_account(api: str, key: str, account_id, steps: list) -> None:
    """恢复账号状态与调度（best-effort，失败不阻断——授权已成功）。"""
    for path, body in (
            (f"/accounts/{account_id}/recover-state", None),
            (f"/accounts/{account_id}/schedulable", {"schedulable": True})):
        label = f"recover_{path.rsplit('/', 1)[-1]}"
        try:
            await _request(api, key, "POST", path, json_body=body)
            steps.append({"t": now(), "step": label,
                          "detail": f"account {account_id} ok", "ok": True})
        except Exception as e:
            steps.append({"t": now(), "step": label,
                          "detail": f"失败（授权已成功，忽略）: {str(e)[:150]}", "ok": False})


# ---------------- flow: sync（不支持）/ async（编排） ----------------
def run_sub2api_sync(ctx, username: str, password: str, totp_secret: str,
                     login_url: str, steps: list, group: dict | None = None,
                     account: dict | None = None) -> dict:
    steps.append({"t": now(), "step": "sub2api_unsupported",
                  "detail": "OAuth 授权流程仅支持异步引擎", "ok": False})
    raise RuntimeError("sub2api（OpenAI 授权任务）仅支持异步引擎（scheduler 当前均为 async）")


async def run_sub2api_async(ctx, username: str, password: str, totp_secret: str,
                            login_url: str, steps: list,
                            group: dict | None = None,
                            account: dict | None = None,
                            cdp_engine: bool = False,
                            phone_handler=None) -> dict:
    """编排: auth_link → 浏览器授权（共享段） → redeem_token."""
    group = dict(group or {})
    remote_id = str((account or {}).get("remote_id") or "").strip() or None

    # 1) 上游段: 拿授权链接
    link = await _auth_link(group, username, remote_id)
    steps.append({"t": now(), "step": "auth_url",
                  "detail": str(link["url"])[:300], "ok": True})

    # 2) 通用浏览器授权段（全适配器共享，与上游无关）
    auth = await run_browser_auth(ctx, link["url"], username, password,
                                  totp_secret, steps, cdp_engine=cdp_engine,
                                  phone_handler=phone_handler)

    # 3) 上游段: 兑换凭证（exchange 成功即授权完成）
    api, key = _api_base(login_url), _api_key(group)
    await _exchange(api, key, auth["code"], auth["state"], link["flow_id"], steps)
    if link.get("account_id") is not None:
        await _recover_account(api, key, link["account_id"], steps)

    return {"authorized": True, "upstream_email": username,
            "flow_id": link["flow_id"], "account_id": link.get("account_id"),
            "callback_url": auth["callback_url"], "url": auth["callback_url"]}


# ---------------- adapter ----------------
class Sub2ApiAdapter(FlowAdapter):
    key = "sub2api"
    label = "sub2api（OpenAI 授权任务）"
    description = "指纹浏览器完成 OpenAI OAuth 授权：获取授权链接 → 自动登录 → localhost 回调 → 兑换凭证"
    run_sync = staticmethod(run_sub2api_sync)
    run_async = staticmethod(run_sub2api_async)

    # ---- credential operations (log-only, never exposed on the web) ----

    async def list_accounts(self, group: dict) -> dict:
        try:
            api, key = _api_base(group.get("login_url") or ""), _api_key(group)
            items = await _list_items(api, key)
            summary = {
                "total": len(items),
                "accounts": [{
                    "id": _item_id(it),
                    "name": it.get("name"),
                    "email": it.get("email"),
                    "status": it.get("status"),
                    "status_label": translate_remote_status(it.get("status")),
                    "enabled": it.get("enabled"),
                    "access_token_expires_at": (
                        it.get("accessTokenExpiresAt") or it.get("tokenExpiresAt")),
                    # 上游 error_message 并入备注（同步后页面可见，便于判断 401 过期等）
                    "remark": str(it.get("remark") or it.get("error_message") or "").strip()[:300],
                } for it in items],
            }
            await log_action(group["id"], self.key, "list_accounts", True,
                             f"total={summary['total']}")
            return summary
        except Exception as e:
            await log_action(group.get("id"), self.key, "list_accounts", False, str(e))
            raise

    async def get_account(self, group: dict, remote_account_id: str) -> dict:
        try:
            api, key = _api_base(group.get("login_url") or ""), _api_key(group)
            items = await _list_items(api, key)
            for it in items:
                if str(_item_id(it)) == str(remote_account_id):
                    summary = {
                        "id": _item_id(it),
                        "name": it.get("name"),
                        "email": it.get("email"),
                        "status": it.get("status"),
                        "status_label": translate_remote_status(it.get("status")),
                        "enabled": it.get("enabled"),
                        "remark": str(it.get("remark") or it.get("error_message") or "").strip()[:300],
                    }
                    await log_action(group["id"], self.key, "get_account", True,
                                     f"accountId={remote_account_id} status={summary['status']}")
                    return summary
            raise RuntimeError(f"上游未找到账号 id={remote_account_id}")
        except Exception as e:
            await log_action(group.get("id"), self.key, "get_account", False,
                             f"accountId={remote_account_id}: {e}")
            raise

    async def auth_link(self, group: dict, name: str,
                        remote_account_id: str | None = None) -> dict:
        """获取授权链接。remote_account_id 缺失时按 email(=name) 在上游列表中定位。"""
        try:
            result = await _auth_link(group, name, remote_account_id)
            await log_action(group["id"], self.key, "auth_link", True,
                             f"accountId={result['account_id']} session={result['flow_id']}")
            return result
        except Exception as e:
            await log_action(group.get("id"), self.key, "auth_link", False, str(e))
            raise

    async def redeem_token(self, group: dict, flow_id: str, callback_url: str,
                           remote_account_id: str | None = None) -> dict:
        """兑换凭证：flow_id = generate-auth-url 的 session_id；
        callback_url = 浏览器段拿到的 localhost 回调地址。
        exchange 成功后 best-effort 恢复账号状态与调度（失败仅记日志，不影响授权结果）。"""
        try:
            code, state = parse_callback(callback_url)
            api, key = _api_base(group.get("login_url") or ""), _api_key(group)
            data = await _exchange(api, key, code, state, flow_id, None)

            if remote_account_id is not None:
                await _recover_account(api, key, remote_account_id, [])

            result = {"ok": True, "data": data if isinstance(data, dict) else {}}
            await log_action(group["id"], self.key, "redeem_token", True,
                             f"session={flow_id} account={remote_account_id}")
            return result
        except Exception as e:
            await log_action(group.get("id"), self.key, "redeem_token", False,
                             f"session={flow_id}: {e}")
            raise

    # refresh_token：上游未见对应端点（插件仅 recover-state/schedulable），不实现。
