"""sub2api flow adapter.

sub2api 站点流程：登录后需要把账号「兑换/转换」为上游 API 凭证。
当前为骨架实现：复用通用账密登录完成站点认证，随后进入 sub2api
业务页面占位（TODO: 按真实站点 DOM 补充点击/提取逻辑）。

适配器要求实现的差异点集中在 `_business_flow_*`：
  - sync 版跑在 cloakbrowser 会话线程
  - async 版跑在原生异步 Playwright
"""
import asyncio

from ._util import now, totp_code
from .base import FlowAdapter
from .password import run_login_async, run_login_sync


# ---------------- sync flavor ----------------
def run_sub2api_sync(ctx, username: str, password: str, totp_secret: str,
                     login_url: str, steps: list) -> dict:
    # Step 1: standard credential login
    result = run_login_sync(ctx, username, password, totp_secret, login_url, steps)

    # Step 2: sub2api business flow (site-specific selectors live here)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    steps.append({"t": now(), "step": "sub2api_enter", "detail": page.url, "ok": True})
    # TODO(sub2api): 按真实站点实现——进入兑换页、提交账号、提取生成的 Key
    result["sub2api"] = {"entered": True, "note": "business flow placeholder"}
    return result


# ---------------- async flavor ----------------
async def run_sub2api_async(ctx, username: str, password: str, totp_secret: str,
                            login_url: str, steps: list) -> dict:
    result = await run_login_async(ctx, username, password, totp_secret, login_url, steps)

    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    steps.append({"t": now(), "step": "sub2api_enter", "detail": page.url, "ok": True})
    # TODO(sub2api): 按真实站点实现
    await asyncio.sleep(0)  # keep async contract even in placeholder
    result["sub2api"] = {"entered": True, "note": "business flow placeholder"}
    return result


class Sub2ApiAdapter(FlowAdapter):
    key = "sub2api"
    label = "sub2api（兑换上游凭证）"
    description = "登录 sub2api 站点后执行账号兑换/转换业务流程"
    run_sync = staticmethod(run_sub2api_sync)
    run_async = staticmethod(run_sub2api_async)

    # NOTE: 五个凭证操作（list_accounts / get_account / auth_link /
    # redeem_token / refresh_token）暂不实现 —— sub2api 当前不可用；
    # 上游接口确定后在类上补齐即可，基类已留好契约与日志约定。
