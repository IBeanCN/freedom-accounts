"""Generic username/password form login (the original platform flow).

Works for any site with a visible login form: fill user/pass -> optional
TOTP -> submit. Selectors are deliberately broad.
"""
import asyncio
import time

import pyotp


def _totp_code(secret: str) -> str | None:
    secret = (secret or "").strip()
    if not secret:
        return None
    try:
        return pyotp.TOTP(secret.replace(" ", "")).now()
    except Exception:
        return None


def _now() -> str:
    return time.strftime("%H:%M:%S")


# ---------------- sync flavor (cloakbrowser session thread) ----------------
def run_login_sync(ctx, username: str, password: str, totp_secret: str,
                   login_url: str, steps: list) -> dict:
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(30000)

    result: dict = {"login_url": login_url, "logged_in": False, "url": "", "title": ""}
    steps.append({"t": _now(), "step": "goto", "detail": login_url, "ok": True})
    page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_load_state("networkidle")
    result["url"], result["title"] = page.url, page.title()

    if _maybe_logged_in_sync(page):
        result["logged_in"] = True
        result["note"] = "session already active (persistent profile)"
        steps.append({"t": _now(), "step": "detect", "detail": "already logged in", "ok": True})
        return result

    user_sel = "input[name=username], input[type=email], #username, #email"
    pass_sel = "input[name=password], input[type=password], #password"
    submit_sel = ("button[type=submit], input[type=submit], "
                  "button:has-text('登录'), button:has-text('Log in')")
    page.fill(user_sel, username)
    steps.append({"t": _now(), "step": "fill_username", "detail": username, "ok": True})
    page.fill(pass_sel, password)
    steps.append({"t": _now(), "step": "fill_password", "detail": "***", "ok": True})
    page.click(submit_sel)
    steps.append({"t": _now(), "step": "submit", "detail": "clicked", "ok": True})

    page.wait_for_timeout(2000)
    otp = _totp_code(totp_secret)
    if otp:
        otp_input = page.locator(
            "input[name=code], input[name=totp], input[autocomplete=one-time-code], #code")
        if otp_input.count() > 0:
            otp_input.first.fill(otp)
            steps.append({"t": _now(), "step": "fill_2fa", "detail": "***", "ok": True})
            submit2 = page.locator(
                "button[type=submit], button:has-text('验证'), button:has-text('Verify')")
            if submit2.count() > 0:
                submit2.first.click()

    page.wait_for_load_state("networkidle")
    result["url"], result["title"] = page.url, page.title()
    result["logged_in"] = _maybe_logged_in_sync(page)
    steps.append({"t": _now(), "step": "verify",
                  "detail": f"logged_in={result['logged_in']}", "ok": result["logged_in"]})
    if not result["logged_in"]:
        raise RuntimeError("login could not be verified (selector mismatch or wrong credentials)")
    return result


def _maybe_logged_in_sync(page) -> bool:
    try:
        return page.locator("input[type=password]:visible").count() == 0
    except Exception:
        return False


# ---------------- async flavor (native async Playwright) ----------------
async def _maybe_logged_in_async(page) -> bool:
    try:
        return await page.locator("input[type=password]:visible").count() == 0
    except Exception:
        return False


async def run_login_async(ctx, username: str, password: str, totp_secret: str,
                          login_url: str, steps: list) -> dict:
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    page.set_default_timeout(30000)

    result: dict = {"login_url": login_url, "logged_in": False, "url": "", "title": ""}
    steps.append({"t": _now(), "step": "goto", "detail": login_url, "ok": True})
    await page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_load_state("networkidle")
    result["url"], result["title"] = page.url, await page.title()

    if await _maybe_logged_in_async(page):
        result["logged_in"] = True
        result["note"] = "session already active (persistent profile)"
        steps.append({"t": _now(), "step": "detect", "detail": "already logged in", "ok": True})
        return result

    user_sel = "input[name=username], input[type=email], #username, #email"
    pass_sel = "input[name=password], input[type=password], #password"
    submit_sel = ("button[type=submit], input[type=submit], "
                  "button:has-text('登录'), button:has-text('Log in')")
    await page.fill(user_sel, username)
    steps.append({"t": _now(), "step": "fill_username", "detail": username, "ok": True})
    await page.fill(pass_sel, password)
    steps.append({"t": _now(), "step": "fill_password", "detail": "***", "ok": True})
    await page.click(submit_sel)
    steps.append({"t": _now(), "step": "submit", "detail": "clicked", "ok": True})

    await asyncio.sleep(2)
    otp = _totp_code(totp_secret)
    if otp:
        otp_input = page.locator(
            "input[name=code], input[name=totp], input[autocomplete=one-time-code], #code")
        if await otp_input.count() > 0:
            await otp_input.first.fill(otp)
            steps.append({"t": _now(), "step": "fill_2fa", "detail": "***", "ok": True})
            submit2 = page.locator(
                "button[type=submit], button:has-text('验证'), button:has-text('Verify')")
            if await submit2.count() > 0:
                await submit2.first.click()

    await page.wait_for_load_state("networkidle")
    result["url"], result["title"] = page.url, await page.title()
    result["logged_in"] = await _maybe_logged_in_async(page)
    steps.append({"t": _now(), "step": "verify",
                  "detail": f"logged_in={result['logged_in']}", "ok": result["logged_in"]})
    if not result["logged_in"]:
        raise RuntimeError("login could not be verified (selector mismatch or wrong credentials)")
    return result


from .base import FlowAdapter


class PasswordAdapter(FlowAdapter):
    key = "password"
    label = "账密表单（通用）"
    description = "通用登录表单：填账号/密码 -> 可选 2FA -> 提交"
    run_sync = staticmethod(run_login_sync)
    run_async = staticmethod(run_login_async)
