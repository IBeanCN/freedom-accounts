"""Regression checks: python -m unittest scripts.test_browser_persistence -v."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiosqlite

from app.automation import browser, scheduler
from app.automation.flows.adapters import _openai_browser as auth_browser
from app.automation.flows.adapters import cpr, sub2api
from app.core import database, settings
from app.routers import accounts_router, groups_router, system_router


class BrowserPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await aiosqlite.connect(":memory:")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(database._SCHEMA)
        self.db_patch = patch.object(database, "get_db", AsyncMock(return_value=self.db))
        self.db_patch.start()
        self.cache_patch = patch.object(settings, "_CACHE", dict(settings.SETTING_DEFAULTS))
        self.cache_patch.start()

    async def asyncTearDown(self):
        await browser.close_all_managed_sessions()
        self.cache_patch.stop()
        self.db_patch.stop()
        await self.db.close()

    async def test_cookie_setting_persists_and_controls_authorization(self):
        page = Mock()
        page.url = "http://localhost/callback?code=test-code&state=test-state"
        page.goto = AsyncMock()
        ctx = Mock(pages=[page], clear_cookies=AsyncMock())
        with patch.object(auth_browser, "install_phone_dom_observer", AsyncMock()), \
                patch.object(browser, "cloak_version", return_value="test"):
            self.assertTrue((await system_router.get_settings())["clear_cookies_before_auth"])
            for enabled in (False, True):
                await system_router.update_settings(system_router.SettingsBody(
                    clear_cookies_before_auth=enabled))
                await settings.refresh_cache()
                self.assertEqual((await system_router.get_settings())[
                    "clear_cookies_before_auth"], enabled)
                ctx.clear_cookies.reset_mock()
                steps = []
                result = await auth_browser.run_browser_auth(
                    ctx, "https://auth.openai.com/authorize", "test@example.com",
                    "test-password", "", steps)
                self.assertEqual(result["code"], "test-code")
                self.assertEqual(ctx.clear_cookies.await_count, int(enabled))
                self.assertEqual(any(s["step"] == "clear_cookies" for s in steps), enabled)
            # Unrelated partial updates must not reset an explicitly disabled switch.
            await system_router.update_settings(system_router.SettingsBody(
                clear_cookies_before_auth=False))
            await system_router.update_settings(system_router.SettingsBody(
                global_browser_mode="headed"))
            self.assertEqual(await settings.get("clear_cookies_before_auth"), "0")

    async def test_task_takes_over_manual_profile_including_retry(self):
        await self.db.execute("INSERT INTO groups(id,group_type,name,login_type,login_url) "
                              "VALUES(1,'openai','test','cpr','https://example.com')")
        await self.db.execute("INSERT INTO accounts(id,group_id,username,password) "
                              "VALUES(7,1,'test@example.com','')")
        g = await (await self.db.execute("SELECT * FROM groups WHERE id=1")).fetchone()
        a = await (await self.db.execute("SELECT * FROM accounts WHERE id=7")).fetchone()
        key = "a7_manual"
        for fail_first in (False, True):
            with self.subTest(retry=fail_first):
                events = []
                ctx = Mock(pages=[Mock()])

                async def close_manual():
                    events.append("manual_closed")

                async def hold_manual():
                    try:
                        await asyncio.Event().wait()
                    finally:
                        await close_manual()

                holder = asyncio.create_task(hold_manual())
                await asyncio.sleep(0)
                browser._MANUAL_SESSIONS[key] = {"closer": holder, "ctx": ctx}

                async def launch(fp, mode, profile_key=None, **kwargs):
                    self.assertEqual(profile_key, key)
                    self.assertNotIn(key, browser._MANUAL_SESSIONS)
                    self.assertEqual(events[0], "manual_closed")
                    events.append("task_launch")
                    if fail_first and events.count("task_launch") == 1:
                        raise browser.SessionLimitError("test seat limit")
                    return AsyncMock(), ctx, "test", "{}"

                with patch.object(browser, "cdp_configured", AsyncMock(return_value=False)), \
                        patch.object(browser, "acquire_seat", AsyncMock()), \
                        patch.object(browser, "force_free_seats", AsyncMock(return_value=True)), \
                        patch.object(browser, "launch_for_account", side_effect=launch), \
                        patch.object(scheduler.flows, "run_flow", AsyncMock(return_value={})), \
                        patch.object(scheduler, "_resolve_phone_handler", AsyncMock(return_value=None)):
                    await scheduler._execute(self.db, g, a, password="test-password")
                row = await (await self.db.execute(
                    "SELECT last_status FROM accounts WHERE id=7")).fetchone()
                self.assertEqual(row["last_status"], "success")
                self.assertEqual(events.count("task_launch"), 2 if fail_first else 1)
                self.assertNotIn("g1_a7", browser._TASK_CONTEXTS)

    async def test_active_profile_is_rejected_before_second_local_launch(self):
        key = "a7_manual"
        with patch.object(browser, "_ACTIVE_LOCAL_PROFILES", {key}):
            with self.assertRaisesRegex(RuntimeError, "Profile 正在使用"):
                await browser.launch_for_account({}, "headed", profile_key=key)

    async def test_cookie_priority_all_combinations_in_authorization(self):
        page = Mock()
        page.url = "http://localhost/callback?code=test-code&state=test-state"
        page.goto = AsyncMock()
        ctx = Mock(pages=[page], clear_cookies=AsyncMock())
        with patch.object(auth_browser, "install_phone_dom_observer", AsyncMock()):
            for system in (True, False):
                settings._CACHE["clear_cookies_before_auth"] = "1" if system else "0"
                for group in (None, True, False):
                    for account in (None, True, False):
                        with self.subTest(system=system, group=group, account=account):
                            expected = account if account is not None else group if group is not None else system
                            ctx.clear_cookies.reset_mock()
                            await auth_browser.run_browser_auth(
                                ctx, "https://auth.openai.com/authorize", "test@example.com",
                                "test-password", "", [],
                                group={"clear_cookies_before_auth": group},
                                account={"clear_cookies_before_auth": account})
                            self.assertEqual(ctx.clear_cookies.await_count, int(expected))

    async def test_group_and_account_setting_crud_and_omitted_field(self):
        group_data = dict(group_type="OpenAI-openai", name="test", login_type="cpr",
                          login_url="https://example.com")
        result = await groups_router.create_group(groups_router.GroupBody(**group_data))
        group_id = result["id"]
        account_data = dict(group_id=group_id, username="test@example.com")
        result = await accounts_router.create_account(accounts_router.AccountBody(
            **account_data, password="test-password"))
        account_id = result["id"]
        self.assertIsNone((await groups_router.get_group(group_id))["clear_cookies_before_auth"])
        self.assertIsNone((await accounts_router.list_accounts(group_id))["accounts"][0][
            "clear_cookies_before_auth"])
        for value in (False, True, None):
            await groups_router.update_group(group_id, groups_router.GroupBody(
                **group_data, clear_cookies_before_auth=value))
            await accounts_router.update_account(account_id, accounts_router.AccountBody(
                **account_data, clear_cookies_before_auth=value))
            # Older clients omitting the field retain the current override.
            await groups_router.update_group(group_id, groups_router.GroupBody(**group_data))
            await accounts_router.update_account(account_id, accounts_router.AccountBody(**account_data))
            self.assertIs((await groups_router.get_group(group_id))["clear_cookies_before_auth"], value)
            self.assertIs((await groups_router.list_groups())["groups"][0][
                "clear_cookies_before_auth"], value)
            self.assertIs((await accounts_router.list_accounts(group_id))["accounts"][0][
                "clear_cookies_before_auth"], value)

    async def test_legacy_database_migration_inherits_and_is_repeatable(self):
        await self.db.execute("ALTER TABLE groups DROP COLUMN clear_cookies_before_auth")
        await self.db.execute("ALTER TABLE accounts DROP COLUMN clear_cookies_before_auth")
        await self.db.execute("INSERT INTO groups(id,group_type,name,login_type,login_url) "
                              "VALUES(1,'OpenAI-openai','legacy','cpr','https://example.com')")
        await self.db.execute("INSERT INTO accounts(id,group_id,username,password) "
                              "VALUES(7,1,'test@example.com','')")
        await database.init_db()
        for table in ("groups", "accounts"):
            row = await (await self.db.execute(f"SELECT clear_cookies_before_auth FROM {table}")).fetchone()
            self.assertIsNone(row["clear_cookies_before_auth"])
            await self.db.execute(f"UPDATE {table} SET clear_cookies_before_auth=0")
        await database.init_db()
        for table in ("groups", "accounts"):
            row = await (await self.db.execute(f"SELECT clear_cookies_before_auth FROM {table}")).fetchone()
            self.assertEqual(row["clear_cookies_before_auth"], 0)

    async def test_both_adapters_pass_cookie_overrides_to_shared_auth(self):
        group = {"clear_cookies_before_auth": True}
        account = {"clear_cookies_before_auth": False}
        result = dict(callback_url="http://localhost/callback", code="test", state="test")
        for adapter, run in ((cpr, cpr.run_cpr_async), (sub2api, sub2api.run_sub2api_async)):
            with self.subTest(adapter=adapter.__name__):
                with patch.object(adapter, "run_browser_auth", AsyncMock(return_value=result)) as auth:
                    if adapter is cpr:
                        with patch.object(cpr.CprAdapter, "auth_link", AsyncMock(return_value={
                                "url": "https://auth.openai.com/authorize", "flow_id": "test"})), \
                                patch.object(cpr.CprAdapter, "redeem_token", AsyncMock()):
                            await run(Mock(), "test@example.com", "test-password", "", "https://example.com",
                                      [], group=group, account=account)
                    else:
                        with patch.object(sub2api, "_auth_link", AsyncMock(return_value={
                                "url": "https://auth.openai.com/authorize", "flow_id": "test"})), \
                                patch.object(sub2api, "_api_key", return_value="test"), \
                                patch.object(sub2api, "_exchange", AsyncMock()):
                            await run(Mock(), "test@example.com", "test-password", "", "https://example.com",
                                      [], group=group, account=account)
                    self.assertEqual(auth.await_args.kwargs["group"], group)
                    self.assertEqual(auth.await_args.kwargs["account"], account)


if __name__ == "__main__":
    unittest.main()
