"""OpenAI 浏览器授权段（全适配器共享）.

auth.openai.com 的页面操作与上游无关：
  清 openai/chatgpt cookie → 打开授权页 → 自动填邮箱/密码/TOTP →
  持续点 Continue → 轮询等 localhost 回调 → 提取 code/state

上游差异（拿授权 URL / 回调换凭证）由各适配器的 auth_link / redeem_token
实现；本模块不做任何上游 HTTP。

选择器与 s2accheck 插件（/Users/ibean/Documents/s2accheck）逐字一致。
"""
import asyncio
import random
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from ._util import now, totp_code

CALLBACK_WAIT_SECONDS = 300      # 等 localhost 回调总时长（与插件一致）
CALLBACK_HOSTS = ("localhost", "127.0.0.1")

# 页面选择器（与插件 PAGE_STEP_FUNCS 保持一致）
SEL_EMAIL = 'input[type="email"], input[name="email"], input#email'
SEL_PASSWORD = 'input[type="password"], input[name="password"], input#password'
SEL_TOTP = 'input[type="text"][name="code"]'
SEL_CONTINUE = 'button[data-dd-action-name="Continue"]'


def is_localhost(url: str) -> bool:
    try:
        return urlparse(url).hostname in CALLBACK_HOSTS
    except Exception:
        return False


def parse_callback(callback_url: str) -> tuple[str, str]:
    """从 localhost 回调 URL 提取 (code, state)；缺 code 抛 RuntimeError。"""
    qs = parse_qs(urlparse(callback_url).query)
    code = (qs.get("code") or [""])[0]
    state = (qs.get("state") or [""])[0]
    if not code:
        raise RuntimeError(f"回调 URL 缺少 code 参数: {redact_callback_url(callback_url)}")
    return code, state


def redact_callback_url(callback_url: str) -> str:
    """Keep callback host/path for diagnosis while hiding OAuth code/state."""
    try:
        parsed = urlparse(callback_url)
        query = urlencode(
            [(key, "***" if key.lower() in {"code", "state"} else value)
             for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
        )
        return urlunparse(parsed._replace(query=query))
    except Exception:
        return "***"


def _step(steps: list, step: str, detail: str, ok: bool = True) -> None:
    steps.append({"t": now(), "step": step, "detail": str(detail)[:300], "ok": ok})


async def _sleep(min_s: float, max_s: float | None = None) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s if max_s is not None else min_s))


async def _fill_first(page, selector: str, value: str, attempts: int = 5) -> bool:
    for _ in range(attempts):
        loc = page.locator(selector)
        try:
            if await loc.count() > 0:
                await loc.first.fill(value)
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def _click_continue(page, attempts: int = 5) -> bool:
    for _ in range(attempts):
        try:
            btn = page.locator(SEL_CONTINUE)
            if await btn.count() > 0:
                await btn.first.click()
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def run_browser_auth(ctx, auth_url: str, email: str, password: str,
                           totp_secret: str, steps: list) -> dict:
    """执行通用 OpenAI 浏览器授权段。

    返回 {"callback_url", "code", "state"}；失败抛 RuntimeError（steps 已留痕）。
    """
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    page.set_default_timeout(30000)

    # 1) 清 openai/chatgpt cookie（防旧会话把授权页重定向走）
    try:
        try:
            await ctx.clear_cookies(domains=["openai.com", "chatgpt.com"])
        except TypeError:
            await ctx.clear_cookies()
        _step(steps, "clear_cookies", "openai/chatgpt cookies cleared")
    except Exception as e:
        _step(steps, "clear_cookies", f"清理失败（继续）: {e}", ok=False)

    # 2) 打开授权页
    await page.goto(auth_url, wait_until="domcontentloaded", timeout=60000)
    _step(steps, "goto", page.url)

    # 3) 填邮箱 -> Continue
    await _sleep(5)
    if await _fill_first(page, SEL_EMAIL, email):
        await _click_continue(page)
        _step(steps, "fill_email", email)
    else:
        _step(steps, "fill_email", "未找到邮箱输入框（可能已登录/已是授权页），继续", ok=False)

    # 4) 填密码 -> Continue
    if not (password or "").strip():
        raise RuntimeError("账号未配置密码，无法自动完成授权")
    await _sleep(5)
    if await _fill_first(page, SEL_PASSWORD, password):
        await _click_continue(page)
        _step(steps, "fill_password", "***")
    else:
        _step(steps, "fill_password", "未找到密码输入框（可能已登录/无需密码），继续", ok=False)

    # 5) 2FA（可选）
    await _sleep(5, 10)
    totp_input = page.locator(SEL_TOTP)
    has_totp_input = False
    for _ in range(5):
        try:
            if await totp_input.count() > 0:
                has_totp_input = True
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    if has_totp_input:
        otp = totp_code(totp_secret)
        if not otp:
            raise RuntimeError("页面要求 2FA 但账号未配置 TOTP 密钥")
        await totp_input.first.fill(otp)
        await _sleep(5, 10)
        await _click_continue(page)
        _step(steps, "fill_2fa", "已填写 TOTP 验证码")
    else:
        _step(steps, "fill_2fa", "无 2FA 输入框，跳过")

    # 6) 持续点 Continue + 等 localhost 回调
    #
    # 回调捕获用事件驱动：page.on("request") 在浏览器**发起** localhost 请求的
    # 瞬间就拿到完整 URL。不能只轮询 page.url —— 回调地址（如 localhost:1455）
    # 本机通常没有服务监听，导航会失败并被 Chrome 替换成网络错误页
    # chrome-error://chromewebdata/，page.url 从此不再是 localhost，
    # 轮询会白等 300s 超时（真实事故：task#8，fill_2fa 后卡满 5 分钟）。
    captured: dict = {}

    def _on_request(req):
        if not captured and is_localhost(req.url):
            captured["url"] = req.url

    page.on("request", _on_request)
    try:
        for _round in range(5):
            await _sleep(5, 10)
            if captured.get("url") or is_localhost(page.url):
                break
            await _click_continue(page, attempts=3)
            if captured.get("url") or is_localhost(page.url):
                break
        deadline = time.monotonic() + CALLBACK_WAIT_SECONDS
        while time.monotonic() < deadline:
            if captured.get("url") or is_localhost(page.url):
                break
            await asyncio.sleep(1)
        else:
            _step(steps, "callback_timeout", page.url[:200])
            raise RuntimeError(
                f"等待 localhost 回调超时（{CALLBACK_WAIT_SECONDS}s），最后页面: {page.url[:200]}")

        callback_url = captured.get("url") or page.url
    finally:
        page.remove_listener("request", _on_request)
    code, state = parse_callback(callback_url)
    _step(steps, "callback", redact_callback_url(callback_url))
    return {"callback_url": callback_url, "code": code, "state": state}
