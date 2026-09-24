"""Browser orchestration on top of a normalized phone-provider adapter."""
import asyncio
import random
import re
import time

from ...phone import PhoneProviderAdapter
from ...phone.countries import country_by_iso2
from ._openai_browser import (
    _click_continue,
    _fill_first,
    _step,
    collect_phone_dom_events,
    drain_phone_dom_errors,
    is_add_phone_url,
)

NAVIGATION_POLL_SECONDS = 2.0
NAVIGATION_WAIT_ROUNDS = 90       # 3 minutes per page transition
CODE_POLL_SECONDS = 5.0
CODE_WAIT_SECONDS = 300           # provider's usual SMS window before cancelling
PHONE_NUMBER_ATTEMPTS = 3
PHONE_ERROR_WAIT_SECONDS = 125    # let OpenAI settle before releasing the order

SEL_COUNTRY_TRIGGER = 'button[aria-haspopup="listbox"]'
SEL_COUNTRY_OPTION = 'div[role="option"]'
SEL_PHONE_TEL = "input#tel"
SEL_SMS_RADIO = 'input[type="radio"][value="sms"]'
SEL_CODE_INPUT = 'input[name="code"]'
SCROLL_STEP = 200               # px per wheel tick inside the dropdown
SCROLL_MAX_ROUNDS = 60         # generous cap; ~12000 px total scroll


class PhoneNumberUnusableError(RuntimeError):
    """OpenAI rejected the number or refused SMS-only delivery."""


class PhoneVerificationTerminalError(RuntimeError):
    """A code-page failure must finish the task but leave its browser open."""

    keep_browser_open = True


def _strip_country_code(phone: str, page_country: str) -> str:
    """Normalize the provider number to the national number expected by OpenAI.

    Mexico may arrive as 52 + 10 digits or legacy 52 + 1 + 10 digits, while
    input#tel accepts only the final 10-digit national number.
    """
    cleaned = re.sub(r"[\s\-\(\)]", "", phone).strip()
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    info = country_by_iso2(page_country)
    dial_code = info["dial_code"] if info else ""
    if dial_code and cleaned.startswith(dial_code):
        cleaned = cleaned[len(dial_code):]
    if (page_country.upper() == "MX" and len(cleaned) == 11
            and cleaned.startswith("1")):
        cleaned = cleaned[1:]
    if not cleaned.isdigit():
        raise RuntimeError("接码平台返回的手机号不是纯数字")
    return cleaned


async def _wait_left_add_phone(page) -> None:
    for _ in range(NAVIGATION_WAIT_ROUNDS):
        if not is_add_phone_url(page.url):
            return
        await asyncio.sleep(NAVIGATION_POLL_SECONDS)
    raise RuntimeError("等待手机号验证页面跳转超时")


async def _wait_code_page_left(page, steps: list) -> None:
    for _ in range(NAVIGATION_WAIT_ROUNDS):
        if await drain_phone_dom_errors(page, steps):
            reason = await _page_error_reason(page)
            await collect_phone_dom_events(page, steps)
            raise PhoneVerificationTerminalError(
                f"验证码页面错误: {reason or 'DOM 监听捕获错误节点'}")
        if "/phone-verification" not in page.url:
            return
        await asyncio.sleep(NAVIGATION_POLL_SECONDS)
    raise RuntimeError("验证码提交后页面跳转超时")


async def _country_trigger_label(page) -> str:
    trigger = page.locator(SEL_COUNTRY_TRIGGER).first
    values = [await trigger.text_content(), await trigger.get_attribute("aria-label"),
              await trigger.get_attribute("data-value")]
    return " ".join(value for value in values if value).strip()


async def _click_locator_center(page, locator) -> None:
    """Click by coordinates; SDK does not support locator hover/nth resolvers."""
    box = await locator.first.bounding_box()
    if not box:
        raise RuntimeError("无法获取页面控件位置")
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    await page.mouse.move(x, y)
    await asyncio.sleep(0.15)
    await page.mouse.click(x, y)


def _country_label_matches(label: str, code: str) -> bool:
    normalized = (label or "").strip().lower()
    info = country_by_iso2(code)
    if not info:
        return False
    return (f'+{info["dial_code"]}' in normalized
            or info["en"].lower() in normalized
            or info["zh"] in normalized)


async def _country_option_label(page, option) -> str:
    values = [await option.text_content(), await option.get_attribute("aria-label"),
              await option.get_attribute("data-value")]
    return " ".join(value for value in values if value).strip()


async def _find_visible_country_option(page, options, code: str):
    """Match visible text, never OpenAI's implementation-specific data-key."""
    for index in range(await options.count()):
        option = options.nth(index)
        if not await option.is_visible():
            continue
        if _country_label_matches(await _country_option_label(page, option), code):
            return option
    return None


async def _stable_option_box(page, option):
    """Wait for mouse-wheel momentum to stop, then return the option box."""
    previous = None
    box = None
    for _ in range(12):
        if not await option.count() or not await option.first.is_visible():
            return None
        box = await option.first.bounding_box()
        if not box:
            await asyncio.sleep(0.2)
            continue
        scroll_top = await page.evaluate(
            """selector => document.querySelector(selector)?.scrollTop ?? null""",
            '[role="listbox"]')
        current = (
            scroll_top,
            round(box["x"]),
            round(box["y"]),
            round(box["width"]),
            round(box["height"]),
        )
        if current == previous:
            return box
        previous = current
        await asyncio.sleep(0.2)
    return box


async def _select_visible_country_option(page, options, code: str,
                                         steps: list) -> bool:
    """Select the target if it is currently visible in the dropdown."""
    option = await _find_visible_country_option(page, options, code)
    if option is None:
        return False

    # The option is already visible, so do not "center" it again: the
    # virtualized list can scroll past it and remount stale nth locators.
    # Wait for its box to settle, then hit-test and click page coordinates.
    box = await _stable_option_box(page, option)
    if not box:
        return False

    click_point = await _option_hit_test(
        page, option, box, SEL_COUNTRY_OPTION)
    if not isinstance(click_point, dict) or "x" not in click_point:
        # Virtualized options can report visible while their box is still
        # below/above the viewport. Return so the wheel search can continue.
        _step(steps, "phone_verification_option_skipped",
              f"国家选项 {code} 尚不可点击，继续滚动: {click_point}; box={box}",
              ok=False)
        return False

    await page.mouse.move(click_point["x"], click_point["y"])
    await page.mouse.click(click_point["x"], click_point["y"])
    return await _confirm_country(page, code, option, steps)


async def _option_hit_test(page, option, box, selector: str) -> object:
    """Return the actual element at a candidate point, preferring an option hit."""
    candidates = ((0.5, 0.5), (0.5, 0.3), (0.5, 0.7),
                  (0.35, 0.5), (0.65, 0.5))
    for x_frac, y_frac in candidates:
        x = box["x"] + box["width"] * x_frac
        y = box["y"] + box["height"] * y_frac
        hit = await page.evaluate(
            """point => {
                const el = document.elementFromPoint(point.x, point.y);
                if (!el) return {kind: 'none'};
                if (el.closest(point.selector)) return {kind: 'target'};
                return {
                    kind: 'other',
                    tag: el.tagName,
                    text: (el.textContent || '').slice(0, 80),
                };
            }""",
            {"x": x, "y": y, "selector": selector})
        if isinstance(hit, dict) and hit.get("kind") == "target":
            return {"x": x, "y": y}
    return hit


async def _confirm_country(page, code: str, option, steps: list) -> bool:
    """Wait briefly for React Aria to sync the trigger after a mouse click."""
    for _ in range(10):
        await asyncio.sleep(0.3)
        label = await _country_trigger_label(page)
        if _country_label_matches(label, code):
            _step(steps, "phone_verification_country",
                  f"已选中国家并确认（{code}；触发器：{label}）")
            return True
        if await option.count() == 0:
            break
    return False


async def _wait_dropdown_closed(page) -> None:
    """Wait through React Aria's close/remount window before page input."""
    listbox = page.locator('[role="listbox"]')
    for _ in range(20):
        if not await listbox.count():
            return
        await asyncio.sleep(0.25)


async def _pick_country(page, code: str, steps: list) -> None:
    """Wheel-search both directions, then mouse-click the target option."""
    trigger = page.locator(SEL_COUNTRY_TRIGGER)
    if await trigger.count() == 0:
        raise RuntimeError("未找到区号选择器 button[aria-haspopup=listbox]")

    await _click_locator_center(page, trigger)
    await asyncio.sleep(1)

    listbox = page.locator('[role="listbox"]')
    for _ in range(10):
        if await listbox.count() > 0:
            break
        await asyncio.sleep(0.5)
    if await listbox.count() == 0:
        raise RuntimeError("国家下拉列表未出现")
    _step(steps, "phone_verification_dropdown", "已打开国家下拉列表")

    lb_box = await listbox.first.bounding_box()
    if not lb_box:
        raise RuntimeError("无法获取国家下拉列表位置")
    await page.mouse.move(
        lb_box["x"] + lb_box["width"] / 2,
        lb_box["y"] + lb_box["height"] / 2)
    await asyncio.sleep(0.3)

    options = page.locator(SEL_COUNTRY_OPTION)
    # React Aria opens around the selected country, so scan the initial
    # viewport once. If absent, wheel-search both directions instead of
    # idling in a direction that never scrolls.
    if await _select_visible_country_option(page, options, code, steps):
        await _wait_dropdown_closed(page)
        return

    for direction in (-1, 1):
        idle_rounds = 0
        for _ in range(SCROLL_MAX_ROUNDS):
            before = await page.evaluate(
                "selector => document.querySelector(selector)?.scrollTop ?? 0",
                '[role="listbox"]')
            await page.mouse.wheel(0, SCROLL_STEP * direction)
            await asyncio.sleep(0.35)
            after = await page.evaluate(
                "selector => document.querySelector(selector)?.scrollTop ?? 0",
                '[role="listbox"]')
            idle_rounds = idle_rounds + 1 if after == before else 0
            if idle_rounds >= 2:
                break
            if await _select_visible_country_option(page, options, code, steps):
                await _wait_dropdown_closed(page)
                return

    if await listbox.count():
        await page.keyboard.press("Escape")
    await collect_phone_dom_events(page, steps)
    label = await _country_trigger_label(page)
    raise RuntimeError(f"滚动后未找到或未选中国家选项 {code}（触发器：{label}）")


async def _receive_and_submit_code(page, steps: list, *,
                                   adapter: PhoneProviderAdapter,
                                   api_key: str, order,
                                   status: dict) -> None:
    _step(steps, "phone_verification_code_waiting", "已提交手机号，等待接码平台返回验证码")
    deadline = time.monotonic() + CODE_WAIT_SECONDS
    while True:
        code = await adapter.get_code(api_key, order)
        dom_errors = await drain_phone_dom_errors(page, steps)
        if dom_errors:
            reason = await _page_error_reason(page)
            await collect_phone_dom_events(page, steps)
            raise PhoneVerificationTerminalError(
                f"验证码页面错误: {reason or 'DOM 监听捕获错误节点'}")
        if code:
            _step(steps, "phone_verification_code_received", "接码平台已返回验证码")
            break
        if time.monotonic() >= deadline:
            await collect_phone_dom_events(page, steps)
            raise PhoneVerificationTerminalError(
                f"等待验证码超时（{CODE_WAIT_SECONDS:.0f}s）")
        await asyncio.sleep(CODE_POLL_SECONDS)

    if not await _fill_first(page, SEL_CODE_INPUT, code, attempts=5):
        await collect_phone_dom_events(page, steps)
        raise PhoneVerificationTerminalError("未找到验证码输入框 input[name=code]")
    _step(steps, "phone_verification_code_filled", "已填入验证码")
    await asyncio.sleep(random.uniform(5, 10))
    if not await _click_continue(page, attempts=5):
        await collect_phone_dom_events(page, steps)
        raise PhoneVerificationTerminalError("未找到验证码页 Continue 按钮")
    status["code_submitted"] = True
    _step(steps, "phone_verification_code_submitted", "已提交验证码")
    await _wait_code_page_left(page, steps)
    try:
        await adapter.confirm_received(api_key, order)
        _step(steps, "phone_verification_confirmed", "已确认接码平台收到验证码")
    except Exception as e:
        # OpenAI has already accepted the code; provider acknowledgement is
        # best-effort and must not fail the completed authorization.
        _step(steps, "phone_verification_confirm_failed",
              f"确认接码订单失败（OpenAI 验证已继续）: {e}", ok=False)


async def _cancel_order_safely(adapter: PhoneProviderAdapter, api_key: str,
                               order, steps: list, reason: str) -> None:
    try:
        await adapter.cancel_order(api_key, order)
        _step(steps, "phone_verification_order_cancelled", reason)
    except Exception as e:
        # HTTP client errors include the request URL; never persist the key.
        detail = str(e).replace(api_key, "***") if api_key else str(e)
        _step(steps, "phone_verification_order_cancel_failed",
              f"{reason}失败: {detail}", ok=False)


async def _fill_phone_number(page, phone: str, steps: list) -> bool:
    """Focus once and type exactly one value; never retry over stale input."""
    try:
        # React Aria can keep the closing dropdown mounted while the phone
        # field remounts. Wait for the field, but never retype over a value.
        loc = page.locator(SEL_PHONE_TEL)
        for _ in range(20):
            if await loc.count():
                break
            await asyncio.sleep(0.25)
        if not await loc.count():
            return False
        await loc.first.click()
        await page.keyboard.type(phone, delay=random.uniform(30, 80))
        await asyncio.sleep(0.5)
        tel_digits = re.sub(r"\D", "",
                            await loc.first.input_value() or "")
        return tel_digits == phone
    except Exception as e:
        await collect_phone_dom_events(page, steps)
        _step(steps, "phone_verification_input_error",
              f"手机号输入失败: {e}", ok=False)
        return False


async def _page_error_reason(page) -> str:
    """Return visible field/page errors; any error means this number failed."""
    text = await page.evaluate(
        """() => [...document.querySelectorAll('[role="alert"], .react-aria-FieldError, [aria-live]')]
            .map(el => (el.innerText || el.textContent || '').trim())
            .filter(Boolean)
            .slice(0, 10)
            .join(' | ')"""
    )
    return (text or "").strip()[:300]


async def _require_sms_selected(page, steps: list) -> None:
    """Force SMS selection and reject OpenAI's WhatsApp fallback."""
    radio = page.locator(SEL_SMS_RADIO)
    if await radio.count() == 0:
        raise PhoneNumberUnusableError("页面未提供 SMS 选项")

    if not await radio.first.is_checked():
        await radio.first.check(force=True)
        await asyncio.sleep(0.5)

    if not await radio.first.is_checked():
        raise PhoneNumberUnusableError("SMS 选项未选中（页面可能已切换 WhatsApp）")
    _step(steps, "phone_verification_sms_only", "已确认仅使用 SMS 接收验证码")


async def provider_phone_verification(page, email: str, steps: list, *,
                                      adapter: PhoneProviderAdapter,
                                      api_key: str, country: str,
                                      page_country: str) -> None:
    """Reserve a real number, verify it, and hand the callback back to the flow."""
    del email  # Reserved for platforms that bind orders to account email.

    balance = await adapter.get_balance(api_key)
    _step(steps, "phone_verification_balance", f"{adapter.label} 余额: {balance}")

    page_country = page_country.strip().upper()
    if not country.strip() or not page_country:
        raise RuntimeError("接码配置缺少平台国家 ID 或页面国家编码")

    # Reserve a provider order only after the page has accepted the requested
    # country. Otherwise a country-selection failure would strand an order.
    await _pick_country(page, page_country, steps)

    for attempt in range(1, PHONE_NUMBER_ATTEMPTS + 1):
        order = await adapter.get_number(api_key, country, page_country=page_country)
        code_submitted = False
        verification_status = {"code_submitted": False}
        phone = _strip_country_code(order.phone, page_country)
        _step(steps, "phone_verification_phone",
              f"第 {attempt}/{PHONE_NUMBER_ATTEMPTS} 个号码："
              f"原始手机号 {order.phone}；填入手机号 {phone}；"
              f"订单 {order.provider_order_id}")

        try:
            if not await _fill_phone_number(page, phone, steps):
                raise RuntimeError("未找到手机号输入框 input#tel")
            tel_value = await page.locator(SEL_PHONE_TEL).first.input_value()
            trigger_label = await _country_trigger_label(page)
            if not _country_label_matches(trigger_label, page_country):
                raise PhoneNumberUnusableError(
                    f"手机号输入后国家被重置（触发器：{trigger_label}）")
            _step(steps, "phone_verification_filled",
                  f"已人工输入并回读手机号 {tel_value}；国家仍为 {trigger_label}")

            reason = await _page_error_reason(page)
            if reason:
                raise PhoneNumberUnusableError(f"OpenAI 提示号码不可用: {reason}")

            await _require_sms_selected(page, steps)
            await asyncio.sleep(random.uniform(5, 10))
            reason = await _page_error_reason(page)
            if reason:
                raise PhoneNumberUnusableError(f"提交前检测到号码不可用: {reason}")

            if not await _click_continue(page, attempts=5, allow_add_phone=True):
                raise RuntimeError("未找到手机号页 Continue 按钮")
            _step(steps, "phone_verification_submitted", "已以 SMS 方式提交手机号")
            await asyncio.sleep(2)

            if is_add_phone_url(page.url):
                reason = await _page_error_reason(page)
                if reason:
                    raise PhoneNumberUnusableError(f"提交后 OpenAI 返回错误: {reason}")

            if "/phone-verification" in page.url:
                _step(steps, "phone_verification_code_page", "已进入验证码页面")
                await collect_phone_dom_events(page, steps)
                await asyncio.sleep(random.uniform(5, 10))
                await _receive_and_submit_code(
                    page, steps, adapter=adapter, api_key=api_key, order=order,
                    status=verification_status)
                code_submitted = verification_status["code_submitted"]
            else:
                await _wait_left_add_phone(page)
            _step(steps, "phone_verification_completed", "手机号验证流程已完成")
            return
        except asyncio.CancelledError:
            await _cancel_order_safely(
                adapter, api_key, order, steps, "任务取消，已取消接码订单")
            raise
        except PhoneNumberUnusableError as e:
            # OpenAI sometimes flips delivery method or revises the field error
            # right after submission. Do not touch the page during this window;
            # cancelling too early made HeroSMS return 409 in production.
            _step(steps, "phone_verification_error_wait",
                  f"第 {attempt} 个号码被拒绝，保持页面不动并等待 "
                  f"{PHONE_ERROR_WAIT_SECONDS} 秒: {e}", ok=False)
            try:
                await asyncio.sleep(PHONE_ERROR_WAIT_SECONDS)
            except asyncio.CancelledError:
                if not code_submitted:
                    await _cancel_order_safely(
                        adapter, api_key, order, steps, "任务取消，已取消接码订单")
                raise
            if not code_submitted:
                await _cancel_order_safely(
                    adapter, api_key, order, steps,
                    "号码被拒绝，等待后已取消当前接码订单")
            if attempt >= PHONE_NUMBER_ATTEMPTS:
                raise
            _step(steps, "phone_verification_number_replacement",
                  f"第 {attempt} 个号码已取消，准备获取新号码", ok=False)
        except Exception:
            if not code_submitted:
                await _cancel_order_safely(
                    adapter, api_key, order, steps,
                    "手机号验证中断，已取消未使用的接码订单")
            raise

    raise RuntimeError(f"连续 {PHONE_NUMBER_ATTEMPTS} 个手机号均不可用，任务停止")
