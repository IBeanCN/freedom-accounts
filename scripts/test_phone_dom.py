"""Diagnostic: verify add-phone DOM selectors with a local headed browser.

Usage:
  python scripts/test_phone_dom.py

Launches a Chromium instance in headed mode, navigates to the OpenAI
add-phone page, and tests each selector step by step with output.
"""
import asyncio


SEL_COUNTRY_TRIGGER = 'div[data-trigger="Select"]'
SEL_PHONE_TEL = "input#tel"
SEL_SMS_RADIO = 'input[type="radio"][value="sms"]'
SEL_LISTBOX = '[role="listbox"]'
SEL_OPTION = 'div[role="option"]'


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await (await browser.new_context()).new_page()

        url = "https://auth.openai.com/add-phone"
        print(f"[*] navigating to {url}")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        print(f"[*] current URL: {page.url}")

        # 1) country trigger
        trigger = page.locator(SEL_COUNTRY_TRIGGER)
        count = await trigger.count()
        print(f"\n[1] {SEL_COUNTRY_TRIGGER} => count={count}")
        if not count:
            print("    !!! NOT FOUND - check selector")
            await browser.close()
            return
        await trigger.first.hover()
        print("    hover() OK")
        await asyncio.sleep(2)

        # 2) listbox
        listbox = page.locator(SEL_LISTBOX)
        lb_count = await listbox.count()
        print(f"\n[2] {SEL_LISTBOX} => count={lb_count}")
        if lb_count:
            box = await listbox.first.bounding_box()
            print(f"    bounding_box={box}")
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await page.mouse.move(cx, cy)
                print(f"    mouse.move({cx:.0f}, {cy:.0f}) OK")

        # 3) options
        options = page.locator(SEL_OPTION)
        opt_count = await options.count()
        print(f"\n[3] {SEL_OPTION} => count={opt_count}")
        for i in range(min(3, opt_count)):
            text = await options.nth(i).text_content()
            key = await options.nth(i).get_attribute("data-key")
            print(f"    option[{i}]: data-key={key!r} text={text!r}")

        # 4) scroll test
        print("\n[4] scroll test (5 x wheel 300px)...")
        for i in range(5):
            await page.mouse.wheel(0, 300)
            await asyncio.sleep(0.3)
            print(f"    wheel {i + 1}: options count={await options.count()}")

        # 5) phone input
        tel = page.locator(SEL_PHONE_TEL)
        tel_count = await tel.count()
        print(f"\n[5] {SEL_PHONE_TEL} => count={tel_count}")

        # 6) SMS radio
        radio = page.locator(SEL_SMS_RADIO)
        radio_count = await radio.count()
        print(f"\n[6] {SEL_SMS_RADIO} => count={radio_count}")

        print("\n[*] done - review output above")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
