import asyncio
import httpx
import logging

log = logging.getLogger(__name__)

from .base import PhoneCountry, PhoneOrder, PhoneProviderAdapter, PhoneProviderNoNumbers

BASE_URL = "https://hero-sms.com/stubs/handler_api.php"
TIMEOUT = 30
NUMBER_ATTEMPTS = 5
NUMBER_RETRY_SECONDS = 3
# HeroSMS's legacy API code for its OpenAI/ChatGPT service; visible in the
# website asset path as dr0.webp while the public page slug is "chatgpt".
SERVICE = "dr"
# QA escape hatch only; must stay false in production so no mock orders run.
MOCK_GET_NUMBER = False


class HeroSmsAdapter(PhoneProviderAdapter):
    key = "hero_sms"
    label = "HeroSMS"

    async def _api(self, api_key: str, **params: object) -> str:
        """Single helper for the text-protocol endpoints; raises on HTTP errors."""
        await self._acquire_request_slot(api_key)
        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            resp = await client.get(BASE_URL, params={"api_key": api_key, **params})
            resp.raise_for_status()
        return resp.text.strip()

    async def get_countries(self, api_key: str) -> list[PhoneCountry]:
        """Fetch provider countries; handles both list and dict-keyed responses."""
        await self._acquire_request_slot(api_key)
        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            resp = await client.get(BASE_URL, params={
                "action": "getCountries", "api_key": api_key})
            log.info("HeroSMS getCountries status=%s body=%r", resp.status_code,
                     resp.text[:500])
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, dict):
            # Some providers key the list by country id: {"0": {...}, "1": {...}}
            data = list(data.values())
        elif not isinstance(data, list):
            raise RuntimeError(
                f"HeroSMS getCountries 返回异常: {resp.text[:500]}")
        countries: dict[str, PhoneCountry] = {}
        for item in data:
            if not isinstance(item, dict) or not item.get("visible"):
                continue
            code = str(item.get("id", "")).strip()
            if not code:
                continue
            name = str(item.get("chn") or item.get("eng") or "").strip()
            countries.setdefault(code, PhoneCountry(code=code, name=name))
        return sorted(countries.values(), key=lambda c: c.name.lower())

    async def get_balance(self, api_key: str) -> str:
        resp = await self._api(api_key, action="getBalance")
        if resp.startswith("ACCESS_BALANCE:"):
            return resp.split(":", 1)[1].strip()
        raise RuntimeError(f"HeroSMS getBalance 失败: {resp}")

    async def get_number(self, api_key: str, country: str) -> PhoneOrder:
        country_code = country.strip()
        if not country_code:
            raise RuntimeError("HeroSMS 取号缺少国家 ID")
        if MOCK_GET_NUMBER:
            await asyncio.sleep(0.2)
            return PhoneOrder(phone="525500000000",
                              provider_order_id=f"mock-{country_code}")
        for attempt in range(1, NUMBER_ATTEMPTS + 1):
            resp = await self._api(
                api_key, action="getNumber", service=SERVICE,
                country=country_code)
            if resp.startswith("ACCESS_NUMBER:"):
                break
            if resp != "NO_NUMBERS":
                raise RuntimeError(f"HeroSMS getNumber 失败: {resp}")
            log.warning("HeroSMS getNumber 无库存（第 %d/%d 次）: country=%s",
                        attempt, NUMBER_ATTEMPTS, country_code)
            if attempt < NUMBER_ATTEMPTS:
                await asyncio.sleep(NUMBER_RETRY_SECONDS)

        if not resp.startswith("ACCESS_NUMBER:"):
            log.error("HeroSMS getNumber 连续 %d 次无库存: country=%s",
                      NUMBER_ATTEMPTS, country_code)
            raise PhoneProviderNoNumbers(
                f"HeroSMS 连续 {NUMBER_ATTEMPTS} 次取号无库存")
        parts = resp.split(":", 2)
        if len(parts) != 3 or not parts[1].strip() or not parts[2].strip():
            raise RuntimeError(f"HeroSMS getNumber 返回格式异常: {resp}")
        return PhoneOrder(phone=parts[2].strip(),
                          provider_order_id=parts[1].strip())

    async def get_code(self, api_key: str, order: PhoneOrder) -> str:
        if not order.provider_order_id:
            raise RuntimeError("HeroSMS 查询验证码缺少激活 ID")
        if order.provider_order_id.startswith("mock-"):
            return ""
        resp = await self._api(
            api_key, action="getStatus", id=order.provider_order_id)
        if resp.startswith("STATUS_OK:"):
            code = resp.split(":", 1)[1].strip()
            if not code:
                raise RuntimeError(f"HeroSMS getStatus 验证码为空: {resp}")
            return code
        if resp in {"STATUS_WAIT_CODE", "STATUS_WAIT_RESEND"}:
            return ""
        if resp.startswith("STATUS_WAIT_RETRY:"):
            return ""
        if resp in {"STATUS_CANCEL", "STATUS_CANCELLED"}:
            raise RuntimeError(f"HeroSMS 激活已取消: {resp}")
        raise RuntimeError(f"HeroSMS getStatus 失败: {resp}")

    async def confirm_received(self, api_key: str, order: PhoneOrder) -> None:
        if not order.provider_order_id:
            raise RuntimeError("HeroSMS 确认接收缺少激活 ID")
        if order.provider_order_id.startswith("mock-"):
            return
        resp = await self._api(
            api_key, action="setStatus", id=order.provider_order_id, status=6)
        if resp != "ACCESS_ACTIVATION":
            raise RuntimeError(f"HeroSMS setStatus 失败: {resp}")

    async def cancel_order(self, api_key: str, order: PhoneOrder) -> None:
        if not order.provider_order_id:
            raise RuntimeError("HeroSMS 取消激活缺少激活 ID")
        if order.provider_order_id.startswith("mock-"):
            return
        resp = await self._api(
            api_key, action="setStatus", id=order.provider_order_id, status=8)
        if resp != "ACCESS_CANCEL":
            raise RuntimeError(f"HeroSMS 取消激活失败: {resp}")
