"""OpenAI 浏览器授权段（全适配器共享）.

auth.openai.com 的页面操作与上游无关：
  清 openai/chatgpt cookie → 打开授权页 → 自动填邮箱/密码/TOTP →
  持续点 Continue → 轮询等 localhost 回调 → 提取 code/state

上游差异（拿授权 URL / 回调换凭证）由各适配器的 auth_link / redeem_token
实现；本模块不做任何上游 HTTP。

选择器与 s2accheck 插件（/Users/ibean/Documents/s2accheck）逐字一致。
"""
import asyncio
import json
import random
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse
from collections.abc import Awaitable, Callable

from ...phone import PhoneProviderNoNumbers
from ._util import now, totp_code

CALLBACK_WAIT_SECONDS = 120      # 等 localhost 回调总时长
CALLBACK_HOSTS = ("localhost", "127.0.0.1")
ADD_PHONE_URL = "https://auth.openai.com/add-phone"
PHONE_WAIT_POLL_SECONDS = 1.0

# Future SMS/phone-pool integrations can fill phone and code themselves. The
# handler receives (page, email, steps) and returns only after the phone gate
# has been completed.
PhoneVerificationHandler = Callable[[object, str, list], Awaitable[None]]

# 页面选择器（与插件 PAGE_STEP_FUNCS 保持一致）
SEL_EMAIL = 'input[type="email"], input[name="email"], input#email'
SEL_PASSWORD = 'input[type="password"], input[name="password"], input#password'
SEL_TOTP = 'input[type="text"][name="code"]'
SEL_CONTINUE = 'button[data-dd-action-name="Continue"]'

# Read-only add-phone diagnostics. OpenAI virtualizes the country list and can
# mutate controls without navigation, so retain a small in-page event trail.
_PHONE_DOM_OBSERVER_SCRIPT = """() => {
    if (window.__faPhoneDom) return;
    const state = { events: [], latest: {}, errors: [] };
    window.__faPhoneDom = state;
    const selectors = {
        trigger: 'button[aria-haspopup="listbox"], div[data-trigger="Select"]',
        listbox: '[role="listbox"]',
        option: 'div[role="option"]',
        tel: 'input#tel',
        sms: 'input[type="radio"][value="sms"]',
        code: 'input[name="code"]',
        error: '[role="alert"], .react-aria-FieldError, [aria-live]',
    };
    const pushErrors = () => {
        const text = [...document.querySelectorAll(selectors.error)]
            .map(item => (item.innerText || item.textContent || '').trim())
            .filter(Boolean).join(' | ').slice(0, 500);
        if (!text) return;
        const key = `${location.pathname}:${text}`;
        if (state.errors.some(item => item.key === key)) return;
        state.errors.push({
            key,
            at: new Date().toISOString(),
            url: location.href,
            text,
        });
        if (state.errors.length > 20) state.errors.splice(0, state.errors.length - 20);
    };
    const push = (reason) => {
        if (!/(^|\\.)openai\\.com$/.test(location.hostname)) return;
        const path = location.pathname;
        if (path !== '/add-phone' && path !== '/phone-verification') return;
        const counts = {};
        for (const [name, selector] of Object.entries(selectors)) {
            counts[name] = document.querySelectorAll(selector).length;
        }
        const trigger = document.querySelector(selectors.trigger);
        const options = [...document.querySelectorAll(selectors.option)]
            .map(item => (item.innerText || item.textContent || '').trim())
            .filter(Boolean).slice(0, 20);
        const listbox = document.querySelector(selectors.listbox);
        const event = {
            at: new Date().toISOString(),
            url: location.href,
            reason,
            counts,
            trigger: (trigger?.innerText || trigger?.getAttribute('aria-label') || '').trim(),
            scroll_top: listbox ? listbox.scrollTop : null,
            options,
        };
        state.latest[path] = event;
        state.events.push(event);
        if (state.events.length > 20) state.events.splice(0, state.events.length - 20);
        pushErrors();
    };
    let scheduled = false;
    const schedule = (reason) => {
        if (scheduled) return;
        scheduled = true;
        setTimeout(() => {
            scheduled = false;
            push(reason);
        }, 50);
    };
    const observer = new MutationObserver(() => schedule('mutation'));
    const install = () => {
        observer.observe(document.documentElement, {
            childList: true, subtree: true, attributes: true,
        });
        for (const method of ['pushState', 'replaceState']) {
            const original = history[method];
            history[method] = function (...args) {
                const result = original.apply(this, args);
                schedule(method);
                return result;
            };
        }
        window.addEventListener('popstate', () => schedule('popstate'));
        push('init');
    };
    if (document.documentElement) install();
    else document.addEventListener('DOMContentLoaded', install, { once: true });
}"""


def is_localhost(url: str) -> bool:
    try:
        return urlparse(url).hostname in CALLBACK_HOSTS
    except Exception:
        return False


def is_add_phone_url(url: str) -> bool:
    """Match OpenAI's phone-enrollment page exactly, ignoring query/hash."""
    try:
        actual = urlparse(str(url))
        expected = urlparse(ADD_PHONE_URL)
        return (actual.scheme == expected.scheme
                and actual.hostname == expected.hostname
                and actual.path.rstrip("/") == expected.path)
    except Exception:
        return False


async def install_phone_dom_observer(page) -> None:
    """Install best-effort diagnostics without changing add-phone behavior."""
    try:
        await page.add_init_script(f"({_PHONE_DOM_OBSERVER_SCRIPT})()")
    except Exception:
        pass


async def collect_phone_dom_events(page, steps: list) -> None:
    """Drain recent add-phone DOM snapshots into task steps for diagnosis."""
    try:
        payload = await page.evaluate(
            """() => ({
                events: (window.__faPhoneDom?.events || []).splice(0, 20),
                latest: window.__faPhoneDom?.latest?.[location.pathname] || null,
            })""")
    except Exception as e:
        _step(steps, "phone_dom_events", f"读取 DOM 监听失败: {e}", ok=False)
        return
    for event in payload.get("events") or []:
        _step(steps, "phone_dom_events", json.dumps(event, ensure_ascii=False))
    snapshot = payload.get("latest")
    if snapshot and snapshot not in (payload.get("events") or []):
        _step(steps, "phone_dom_events", json.dumps(snapshot, ensure_ascii=False))


async def drain_phone_dom_errors(page, steps: list) -> list:
    """Drain error nodes captured by the observer without changing the page."""
    try:
        errors = await page.evaluate(
            "() => (window.__faPhoneDom?.errors || []).splice(0, 20)")
    except Exception as e:
        _step(steps, "phone_dom_error", f"读取页面错误监听失败: {e}", ok=False)
        return []
    for error in errors:
        _step(steps, "phone_dom_error",
              json.dumps(error, ensure_ascii=False), ok=False)
    return errors


async def manual_phone_verification(page, email: str, steps: list) -> None:
    """Leave the OpenAI page untouched until the user completes phone entry."""
    _step(steps, "phone_verification_wait",
          "SDK 环境检测到手机号验证，保持页面等待用户输入手机号和验证码")
    while is_add_phone_url(page.url):
        await asyncio.sleep(PHONE_WAIT_POLL_SECONDS)
    _step(steps, "phone_verification_completed", "手机号验证页面已离开，继续授权流程")


async def _handle_add_phone(page, email: str, steps: list, *, cdp_engine: bool,
                            handler: PhoneVerificationHandler | None = None) -> None:
    """Cross one OpenAI phone-enrollment gate without touching the page.

    SDK keeps the browser open indefinitely for manual phone/code entry. A
    handler replaces only that waiting block when automatic phone/SMS support
    is added later.
    """
    if not is_add_phone_url(page.url):
        return
    if cdp_engine:
        _step(steps, "phone_verification_unsupported",
              f"CDP 环境检测到 {ADD_PHONE_URL}，终止流程", ok=False)
        raise RuntimeError("CDP 引擎不支持 OpenAI 手机号验证，已终止上号流程")

    if handler is not None:
        _step(steps, "phone_verification_provider", "调用手机号/验证码处理器")
        try:
            await handler(page, email, steps)
        except PhoneProviderNoNumbers as e:
            _step(steps, "phone_verification_no_numbers",
                  f"接码平台连续取号失败，任务停止: {e}", ok=False)
            raise
        except Exception as e:
            await collect_phone_dom_events(page, steps)
            # A provider outage must not strand a local headed browser at the
            # gate: the user can finish the same page manually.
            _step(steps, "phone_verification_fallback",
                  f"自动手机号验证失败，回退手动: {e}", ok=False)
            if is_add_phone_url(page.url):
                await manual_phone_verification(page, email, steps)
            else:
                raise
        if is_add_phone_url(page.url):
            await asyncio.sleep(PHONE_WAIT_POLL_SECONDS)
        return

    await manual_phone_verification(page, email, steps)


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
        await _sleep(5, 10)
    return False


async def _click_continue(page, attempts: int = 5, *,
                          allow_add_phone: bool = False) -> bool:
    # add-phone has its own handler. A navigation/URL update can land between
    # the caller's check and this click, so opt in explicitly only there.
    for _ in range(attempts):
        if not allow_add_phone and is_add_phone_url(page.url):
            return False
        try:
            btn = page.locator(SEL_CONTINUE)
            if await btn.count() > 0:
                if not allow_add_phone and is_add_phone_url(page.url):
                    return False
                await btn.first.click()
                return True
        except Exception:
            pass
        await _sleep(5, 10)
    return False


async def run_browser_auth(ctx, auth_url: str, email: str, password: str,
                           totp_secret: str, steps: list, *,
                           cdp_engine: bool = False,
                           phone_handler: PhoneVerificationHandler | None = None) -> dict:
    """执行通用 OpenAI 浏览器授权段。

    返回 {"callback_url", "code", "state"}；失败抛 RuntimeError（steps 已留痕）。
    """
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    page.set_default_timeout(30000)
    captured: dict = {}
    await install_phone_dom_observer(page)

    def _on_request(req):
        if not captured and is_localhost(req.url):
            captured["url"] = req.url

    # Manual phone entry can navigate straight to the localhost callback. The
    # listener must already be active before that wait starts.
    page.on("request", _on_request)

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
    await _handle_add_phone(page, email, steps, cdp_engine=cdp_engine,
                           handler=phone_handler)
    await _sleep(5, 10)
    if await _fill_first(page, SEL_EMAIL, email):
        await _sleep(3, 8)
        await _click_continue(page)
        _step(steps, "fill_email", email)
    else:
        _step(steps, "fill_email", "未找到邮箱输入框（可能已登录/已是授权页），继续", ok=False)

    await _handle_add_phone(page, email, steps, cdp_engine=cdp_engine,
                           handler=phone_handler)
    # 4) 填密码 -> Continue
    if not (password or "").strip():
        raise RuntimeError("账号未配置密码，无法自动完成授权")
    await _sleep(5, 10)
    if await _fill_first(page, SEL_PASSWORD, password):
        await _sleep(3, 8)
        await _click_continue(page)
        _step(steps, "fill_password", "***")
    else:
        _step(steps, "fill_password", "未找到密码输入框（可能已登录/无需密码），继续", ok=False)

    await _handle_add_phone(page, email, steps, cdp_engine=cdp_engine,
                           handler=phone_handler)
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
        await _sleep(3, 8)
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
    # 轮询会白等 CALLBACK_WAIT_SECONDS 超时（真实事故：task#8，fill_2fa 后卡满 5 分钟）。
    deadline = time.monotonic() + CALLBACK_WAIT_SECONDS
    continue_rounds = 0
    try:
        while True:
            if captured.get("url") or is_localhost(page.url):
                break

            # The phone gate is manual and unbounded by design. Returning from
            # it restarts the bounded callback wait for the next auth page.
            if is_add_phone_url(page.url):
                await _handle_add_phone(page, email, steps,
                                        cdp_engine=cdp_engine, handler=phone_handler)
                deadline = time.monotonic() + CALLBACK_WAIT_SECONDS
                continue_rounds = 0
                continue

            if time.monotonic() >= deadline:
                break
            if continue_rounds < 5:
                await _sleep(5, 10)
                if captured.get("url") or is_localhost(page.url):
                    break
                if is_add_phone_url(page.url):
                    continue
                await _click_continue(page, attempts=3, allow_add_phone=False)
                continue_rounds += 1
            else:
                await asyncio.sleep(1)
        if not (captured.get("url") or is_localhost(page.url)):
            _step(steps, "callback_timeout", page.url[:200])
            raise RuntimeError(
                f"等待 localhost 回调超时（{CALLBACK_WAIT_SECONDS}s），最后页面: {page.url[:200]}")

        callback_url = captured.get("url") or page.url
    finally:
        page.remove_listener("request", _on_request)
    code, state = parse_callback(callback_url)
    _step(steps, "callback", redact_callback_url(callback_url))
    return {"callback_url": callback_url, "code": code, "state": state}
