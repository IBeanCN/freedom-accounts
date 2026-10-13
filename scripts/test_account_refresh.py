"""Regression checks: python -m unittest scripts.test_account_refresh -v."""
import unittest
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import aiosqlite

from app.automation import account_refresh, scheduler
from app.automation.flows.adapters import cpr, sub2api
from app.core import database


class AccountRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await aiosqlite.connect(":memory:")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(database._SCHEMA)
        await self.db.execute(
            """INSERT INTO groups(id, group_type, name, login_type, login_url, upstream_key)
               VALUES(1, 'OpenAI-openai', 'test', 'cpr', 'https://example.test', 'test')""")
        await self.db.execute(
            """INSERT INTO accounts(id, group_id, username, password, remote_id)
               VALUES(1, 1, 'test', 'test', 'upstream-1')""")
        await self.db.commit()
        self.patches = [
            patch.object(database, "get_db", AsyncMock(return_value=self.db)),
            patch.object(account_refresh, "interval_seconds", AsyncMock(return_value=60)),
            patch.object(scheduler, "_dispatcher", AsyncMock()),
            patch.object(scheduler, "_groups", {}),
            patch.object(scheduler, "_account_slots", set()),
            patch.object(scheduler, "_running_accounts", set()),
            patch.object(scheduler, "_stop_requests", set()),
            patch.object(scheduler, "_account_generations", {}),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        dispatchers = []
        for group in scheduler._groups.values():
            group["dispatcher"].cancel()
            dispatchers.append(group["dispatcher"])
        await asyncio.gather(*dispatchers, return_exceptions=True)
        for item in reversed(self.patches):
            item.stop()
        await self.db.close()

    async def refresh(self, adapter=cpr.CprAdapter, *, status="错误", failure=False):
        detail = AsyncMock(return_value={
            "status_label": status, "remark": "updated", "access_token_expires_at": 123,
        })
        if failure:
            detail.side_effect = RuntimeError("upstream unavailable")
        with patch.object(adapter, "get_account", detail):
            return await account_refresh.run_once()

    async def test_error_account_queues_once_and_keeps_refreshing(self):
        self.assertEqual((await self.refresh())["refreshed"], 1)
        row = await (await self.db.execute("SELECT * FROM accounts WHERE id=1")).fetchone()
        self.assertEqual(row["last_status"], "queued")
        self.assertEqual(row["remote_status"], "错误")
        self.assertEqual(row["remote_remark"], "updated")
        self.assertEqual(row["token_expires_at"], "123")
        await self.refresh()
        self.assertEqual(scheduler._groups[1]["queue"].qsize(), 1)

    async def test_gates_skip_ineligible_accounts(self):
        cases = [
            ("UPDATE accounts SET enabled=0", "错误"),
            ("UPDATE accounts SET password=''", "错误"),
            ("UPDATE accounts SET totp_secret='invalid!'", "错误"),
            ("UPDATE groups SET login_url=''", "错误"),
            ("UPDATE groups SET upstream_key=''", "错误"),
            *[(f"UPDATE accounts SET last_status='{state}'", "错误")
              for state in ("queued", "running", "token_queued", "token_running")],
            *[("UPDATE accounts SET last_status='never'", status)
              for status in ("正常", "配额耗尽", "限流中", "已停用", "退避中")],
        ]
        for sql, status in cases:
            with self.subTest(sql=sql, status=status):
                await self.db.execute(
                    "UPDATE accounts SET enabled=1, password='test', totp_secret='', last_status='never'")
                await self.db.execute("UPDATE groups SET login_url='https://example.test', upstream_key='test'")
                await self.db.execute(sql)
                await self.db.commit()
                await self.refresh(status=status)
                self.assertFalse(scheduler._account_slots)

    async def test_valid_optional_totp_allows_queue(self):
        await self.db.execute("UPDATE accounts SET totp_secret='JBSWY3DPEHPK3PXP'")
        await self.db.commit()
        await self.refresh()
        self.assertEqual(scheduler._account_slots, {1})

    async def test_sub2api_does_not_auto_queue(self):
        await self.db.execute("UPDATE groups SET login_type='sub2api'")
        await self.db.commit()
        self.assertEqual((await self.refresh(sub2api.Sub2ApiAdapter))["refreshed"], 1)
        self.assertFalse(scheduler._account_slots)

    async def test_failed_detail_does_not_queue_stale_error(self):
        await self.db.execute("UPDATE accounts SET remote_status='错误'")
        await self.db.commit()
        self.assertEqual((await self.refresh(failure=True))["refreshed"], 0)
        self.assertFalse(scheduler._account_slots)

    async def test_zero_interval_does_not_refresh_or_queue(self):
        with patch.object(account_refresh, "interval_seconds", AsyncMock(return_value=0)):
            self.assertTrue((await self.refresh())["skipped"])
        self.assertFalse(scheduler._account_slots)

    async def test_disabled_during_detail_request_does_not_queue(self):
        async def detail(*args):
            await self.db.execute("UPDATE accounts SET enabled=0")
            await self.db.commit()
            return {"status_label": "错误"}

        with patch.object(cpr.CprAdapter, "get_account", AsyncMock(side_effect=detail)):
            self.assertEqual((await account_refresh.run_once())["refreshed"], 1)
        self.assertFalse(scheduler._account_slots)

    async def test_enqueue_failure_preserves_detail_refresh(self):
        with patch.object(scheduler, "enqueue", AsyncMock(side_effect=RuntimeError("queue unavailable"))):
            with self.assertLogs(account_refresh._log, level="ERROR"):
                self.assertEqual((await self.refresh())["refreshed"], 1)
        row = await (await self.db.execute("SELECT remote_status FROM accounts")).fetchone()
        self.assertEqual(row["remote_status"], "错误")

    async def execute(self, *, flow_error=None, remote_status="正常", detail_error=None):
        group = await (await self.db.execute("SELECT * FROM groups WHERE id=1")).fetchone()
        account = await (await self.db.execute("SELECT * FROM accounts WHERE id=1")).fetchone()
        detail = AsyncMock(return_value={"status_label": remote_status, "remark": "checked"},
                           side_effect=detail_error)
        browser = scheduler.browser_mod
        with patch.object(browser, "resolve_browser_mode", AsyncMock(return_value="headless")), \
                patch.object(browser, "resolve_proxy", AsyncMock(return_value=None)), \
                patch.object(browser, "launch_with_autocleanup", AsyncMock(
                    return_value=(AsyncMock(), Mock(), "test", "{}"))), \
                patch.object(browser, "register_task_context", side_effect=lambda key, closer, ctx: closer), \
                patch.object(browser, "cdp_configured", AsyncMock(return_value=False)), \
                patch.object(scheduler, "_resolve_phone_handler", AsyncMock(return_value=None)), \
                patch.object(scheduler, "_capture_context_screenshot", AsyncMock(return_value=False)), \
                patch.object(scheduler.flows, "run_flow", AsyncMock(return_value={}, side_effect=flow_error)), \
                patch.object(cpr.CprAdapter, "get_account", detail):
            await scheduler._execute(self.db, group, account, password="test")
        row = await (await self.db.execute("SELECT * FROM accounts WHERE id=1")).fetchone()
        return row, detail

    async def test_failed_cpr_login_disables_and_stops_auto_queue(self):
        row, detail = await self.execute(flow_error=RuntimeError("login failed"))
        self.assertEqual(row["enabled"], 0)
        self.assertEqual(row["last_status"], "failed")
        self.assertIn("已停用", row["last_message"])
        detail.assert_not_awaited()
        await self.refresh()
        self.assertFalse(scheduler._account_slots)

    async def test_successful_cpr_login_with_upstream_error_disables(self):
        row, detail = await self.execute(remote_status="错误")
        self.assertEqual(row["enabled"], 0)
        self.assertEqual(row["remote_status"], "错误")
        self.assertEqual(row["last_status"], "success")
        self.assertIn("上游仍为错误", row["last_message"])
        detail.assert_awaited_once()

    async def test_recovered_cpr_login_stays_enabled(self):
        row, _ = await self.execute()
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["remote_status"], "正常")

    async def test_post_login_lookup_failure_does_not_disable_from_stale_error(self):
        await self.db.execute("UPDATE accounts SET remote_status='错误'")
        await self.db.commit()
        with self.assertLogs(scheduler._log, level="ERROR"):
            row, _ = await self.execute(detail_error=RuntimeError("lookup unavailable"))
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["last_status"], "success")

    async def test_cancelled_cpr_login_stays_enabled(self):
        row, detail = await self.execute(flow_error=scheduler.RunStopped())
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["last_status"], "cancelled")
        detail.assert_not_awaited()

    async def test_failed_sub2api_login_stays_enabled(self):
        await self.db.execute("UPDATE groups SET login_type='sub2api'")
        await self.db.commit()
        row, detail = await self.execute(flow_error=RuntimeError("login failed"))
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["last_status"], "failed")
        detail.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
