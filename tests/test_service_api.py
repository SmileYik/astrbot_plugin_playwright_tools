import unittest
import os
import sys
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from astrbot_plugin_playwright_tools.core.context_manager import ContextManager
from astrbot_plugin_playwright_tools.core.service_api import PlaywrightServiceAPI


class TestPlaywrightServiceAPI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_adapter = MagicMock()
        self.mock_browser_ctx = MagicMock()
        self.mock_page = MagicMock()

        self.mock_browser_ctx.new_page = AsyncMock(return_value=self.mock_page)
        self.mock_browser_ctx.close = AsyncMock(return_value=None)
        self.mock_browser_ctx.route = AsyncMock(return_value=None)

        self.callbacks = {}
        def mock_on(evt, cb):
            self.callbacks[evt] = cb
        self.mock_browser_ctx.on = mock_on

        self.mock_adapter.create_context = AsyncMock(return_value=self.mock_browser_ctx)
        self.mock_security = MagicMock()
        self.mock_security.is_admin.return_value = False

        self.mgr = ContextManager(
            adapter=self.mock_adapter,
            security=self.mock_security,
            mode="personal",
            idle_timeout_minutes=10,
        )
        self.plugin = MagicMock()
        self.service = PlaywrightServiceAPI(self.plugin, self.mgr)

    async def test_service_wait_ready_timeout(self):
        self.assertFalse(self.service.ready)
        with self.assertRaises(TimeoutError):
            await self.service.get_browser_context("test_plugin", timeout=0.05)

    async def test_external_service_lifecycle_and_reuse(self):
        self.service.set_ready()
        self.assertTrue(self.service.ready)

        b_ctx1 = await self.service.get_browser_context("my_plugin")
        self.assertIs(b_ctx1, self.mock_browser_ctx)

        # 再次获取同一外部插件，幂等复用已有上下文
        b_ctx2 = await self.service.get_browser_context("my_plugin")
        self.assertIs(b_ctx1, b_ctx2)
        self.assertEqual(self.mock_adapter.create_context.await_count, 1)

        # 验证内部 SessionContext 标记 is_external=True
        session_ctx = self.mgr.contexts.get(("external", "my_plugin"))
        self.assertIsNotNone(session_ctx)
        self.assertTrue(session_ctx.is_external)
        self.assertEqual(session_ctx.plugin_name, "my_plugin")

        # 主动释放
        released = await self.service.release_browser_context("my_plugin")
        self.assertTrue(released)
        self.assertNotIn(("external", "my_plugin"), self.mgr.contexts)
        self.mock_browser_ctx.close.assert_awaited_once()

    async def test_external_service_async_context_manager(self):
        self.service.set_ready()

        async with self.service.context("temp_plugin") as b_ctx:
            self.assertIs(b_ctx, self.mock_browser_ctx)
            self.assertIn(("external", "temp_plugin"), self.mgr.contexts)

        # 退出上下文管理器后自动释放
        self.assertNotIn(("external", "temp_plugin"), self.mgr.contexts)
        self.mock_browser_ctx.close.assert_awaited_once()

    async def test_external_service_activity_tracker_resets_last_active(self):
        self.service.set_ready()
        await self.service.get_browser_context("active_plugin")

        session_ctx = self.mgr.contexts[("external", "active_plugin")]
        old_time = time.time() - 100
        session_ctx.last_active_time = old_time

        # 触发原生事件回调
        self.assertIn("request", self.callbacks)
        self.callbacks["request"](MagicMock())
        self.assertGreater(session_ctx.last_active_time, old_time)

    async def test_external_context_skips_route_guard(self):
        self.service.set_ready()
        await self.service.get_browser_context("trusted_plugin")
        # 外部插件为受信代码，跳过 route 守卫安装
        self.mock_browser_ctx.route.assert_not_called()


if __name__ == "__main__":
    unittest.main()
