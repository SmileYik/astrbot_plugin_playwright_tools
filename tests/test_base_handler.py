import unittest
import os
import sys
from unittest.mock import MagicMock, AsyncMock

if "astrbot" not in sys.modules:
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from astrbot_plugin_playwright_tools.core.context_manager import BrowserSessionContext
from astrbot_plugin_playwright_tools.tools.handlers.base_handler import BaseActionHandler, clean_playwright_error
from astrbot.api import logger


class TestBaseActionHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logger.error.reset_mock()
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_audit = MagicMock()
        self.mock_audit.log_action = AsyncMock()

        self.mock_page = MagicMock()
        self.mock_page.url = "https://example.com"
        self.mock_page.is_closed = MagicMock(return_value=False)
        self.mock_page.bring_to_front = AsyncMock()
        self.mock_locator = AsyncMock()
        self.mock_locator.get_attribute = AsyncMock(return_value="text")
        self.mock_page.locator.return_value = self.mock_locator
        self.mock_page.wait_for_load_state = AsyncMock()

        mock_bc = MagicMock()
        mock_bc.pages = [self.mock_page]
        self.mock_context = BrowserSessionContext(
            session_id="s1",
            owner_id="u1",
            browser_context=mock_bc,
            current_page=self.mock_page,
            pages=[self.mock_page],
        )

        self.mock_mgr.resolve_context = AsyncMock(return_value=(self.mock_context, ""))
        self.handler = BaseActionHandler(
            self.mock_mgr, self.mock_sec, self.mock_audit, mask_password_inputs=True
        )

    async def test_permission_denied_returns_error_and_logs_audit(self):
        self.mock_sec.check_permission.return_value = (False, "没有点击权限")
        action_fn = AsyncMock()

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "1"},
            required_permission="click",
            action_desc="点击",
        )

        self.assertEqual(res, "点击失败: 没有点击权限")
        action_fn.assert_not_called()
        self.mock_audit.log_action.assert_awaited_once()
        call_kwargs = self.mock_audit.log_action.await_args.kwargs
        self.assertFalse(call_kwargs.get("is_permitted"))
        self.assertEqual(call_kwargs.get("deny_reason"), "没有点击权限")
        self.assertEqual(call_kwargs.get("output_result"), "没有点击权限")

    async def test_permission_denied_default_action_desc(self):
        self.mock_sec.check_permission.return_value = (False, "白名单限制")
        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=AsyncMock(),
            input_args={"ref": "1"},
            required_permission="click",
        )
        self.assertEqual(res, "点击失败: 白名单限制")

    async def test_context_none_returns_error(self):
        self.mock_mgr.resolve_context = AsyncMock(return_value=(None, ""))
        action_fn = AsyncMock()

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "1"},
            required_permission="click",
        )

        self.assertEqual(res, "操作失败: 无法获取浏览器上下文")
        action_fn.assert_not_called()
        self.mock_audit.log_action.assert_not_called()

    async def test_session_mode_uses_sender_id_for_permission(self):
        self.mock_mgr.mode = "session"
        self.mock_context.owner_id = "admin_user"
        self.mock_context.allowed_users = set()

        called_users = []
        def record_perm(user_id, url, action):
            called_users.append(user_id)
            return True, ""
        self.mock_sec.check_permission.side_effect = record_perm

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="normal_user",
            action_name="click",
            target_resource="",
            action_coro_fn=AsyncMock(return_value="ok"),
            input_args={"ref": "1"},
            required_permission="click",
        )
        self.assertEqual(res, "ok")
        self.assertEqual(called_users, ["normal_user"])
        self.assertEqual(self.mock_context.current_operator_id, "normal_user")

    async def test_personal_mode_collaborator_inherits_owner_permission(self):
        self.mock_mgr.mode = "personal"
        self.mock_context.owner_id = "owner_user"
        self.mock_context.allowed_users = {"invited_collab"}

        called_users = []
        def record_perm(user_id, url, action):
            called_users.append(user_id)
            return True, ""
        self.mock_sec.check_permission.side_effect = record_perm

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="invited_collab",
            action_name="click",
            target_resource="",
            action_coro_fn=AsyncMock(return_value="ok"),
            input_args={"ref": "1"},
            required_permission="click",
        )
        self.assertEqual(res, "ok")
        self.assertEqual(called_users, ["owner_user"])

    async def test_normal_execution_records_audit_and_returns_result(self):
        action_fn = AsyncMock(return_value="已成功点击元素 [1]")

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="https://example.com",
            action_coro_fn=action_fn,
            input_args={"ref": "1"},
            required_permission="click",
        )

        self.assertEqual(res, "已成功点击元素 [1]")
        action_fn.assert_awaited_once_with(self.mock_context, self.mock_page)
        self.mock_audit.log_action.assert_awaited_once()
        call_kwargs = self.mock_audit.log_action.await_args.kwargs
        self.assertTrue(call_kwargs.get("is_permitted"))
        self.assertEqual(call_kwargs.get("output_result"), "已成功点击元素 [1]")
        self.assertEqual(call_kwargs.get("input_args"), {"ref": "1"})

    async def test_execution_with_hint_prepends_hint(self):
        self.mock_mgr.resolve_context = AsyncMock(
            return_value=(self.mock_context, "提示: 正在使用会话共享浏览器")
        )
        action_fn = AsyncMock(return_value="已成功完成操作")

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="read_page",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={},
            required_permission="read",
        )

        self.assertTrue(res.startswith("提示: 正在使用会话共享浏览器\n已成功完成操作"))

    async def test_execution_exception_cleans_error_and_logs(self):
        action_fn = AsyncMock(
            side_effect=Exception("Locator.click: Timeout 10000ms exceeded waiting for locator")
        )

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "1"},
            required_permission="click",
        )

        self.assertIn("未能定位到目标元素", res)
        self.assertIn("pw_read()", res)
        self.mock_audit.log_action.assert_awaited_once()
        call_kwargs = self.mock_audit.log_action.await_args.kwargs
        self.assertTrue(call_kwargs.get("is_error"))
        self.assertTrue(call_kwargs.get("is_permitted"))
        logger.error.assert_called_once()

    async def test_password_masking_via_ref_map(self):
        self.mock_context.get_page_state(self.mock_page).ref_map["p1"] = {"type": "password", "tag": "input"}
        action_fn = AsyncMock(return_value="已成功在密码输入框 [p1] 填入内容: secret_pass_123")

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="fill_form",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "p1", "text": "secret_pass_123"},
            required_permission="fill",
        )

        self.assertNotIn("secret_pass_123", res)
        self.assertIn("******", res)

        self.mock_audit.log_action.assert_awaited_once()
        call_kwargs = self.mock_audit.log_action.await_args.kwargs
        logged_args = call_kwargs.get("input_args")
        self.assertEqual(logged_args.get("text"), "******")
        self.assertEqual(logged_args.get("ref"), "p1")

    async def test_password_masking_via_dom_probe(self):
        self.mock_context.get_page_state(self.mock_page).ref_map = {}
        self.mock_locator.get_attribute = AsyncMock(return_value="password")

        action_fn = AsyncMock(return_value="已成功填入密码")

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="fill_form",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "2", "text": "dom_pwd_999"},
            required_permission="fill",
        )

        self.assertEqual(res, "已成功填入密码")
        self.mock_audit.log_action.assert_awaited_once()
        logged_args = self.mock_audit.log_action.await_args.kwargs.get("input_args")
        self.assertEqual(logged_args.get("text"), "******")

    async def test_password_masking_on_exception_does_not_leak_secret(self):
        self.mock_context.get_page_state(self.mock_page).ref_map = {"p1": {"type": "password"}}
        action_fn = AsyncMock(side_effect=Exception("Failed while entering my_super_pwd into element"))

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="fill_form",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "p1", "text": "my_super_pwd"},
            required_permission="fill",
        )

        self.assertNotIn("my_super_pwd", res)
        self.assertIn("******", res)

        # Check logger.error call
        logger.error.assert_called_once()
        log_msg = logger.error.call_args[0][0]
        self.assertNotIn("my_super_pwd", log_msg)
        self.assertIn("******", log_msg)

        # Check audit log call
        call_kwargs = self.mock_audit.log_action.await_args.kwargs
        self.assertEqual(call_kwargs.get("input_args").get("text"), "******")
        self.assertNotIn("my_super_pwd", call_kwargs.get("error_message"))

    async def test_password_masking_disabled(self):
        handler_no_mask = BaseActionHandler(
            self.mock_mgr, self.mock_sec, self.mock_audit, mask_password_inputs=False
        )
        self.mock_context.get_page_state(self.mock_page).ref_map = {"p1": {"type": "password"}}
        action_fn = AsyncMock(return_value="已成功在输入框填入")

        await handler_no_mask.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="fill_form",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "p1", "text": "plain_password"},
            required_permission="fill",
        )

        call_kwargs = self.mock_audit.log_action.await_args.kwargs
        self.assertEqual(call_kwargs.get("input_args").get("text"), "plain_password")

    async def test_wait_page_stable_success(self):
        await self.handler.wait_page_stable(self.mock_page, timeout=1.5)
        self.assertEqual(self.mock_page.wait_for_load_state.await_count, 2)
        self.mock_page.wait_for_load_state.assert_any_await("domcontentloaded", timeout=10000)
        self.mock_page.wait_for_load_state.assert_any_await("networkidle", timeout=1500)

    async def test_wait_page_stable_timeout_silently_caught(self):
        self.mock_page.wait_for_load_state = AsyncMock(
            side_effect=TimeoutError("Timeout 1500ms exceeded")
        )
        # Should not raise exception
        await self.handler.wait_page_stable(self.mock_page, timeout=1.5)

    async def test_execute_action_with_wait_stabilize(self):
        self.handler.wait_page_stable = AsyncMock()
        action_fn = AsyncMock(return_value="ok")

        await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "1"},
            required_permission="click",
            wait_stabilize=True,
        )

        self.handler.wait_page_stable.assert_awaited_once_with(self.mock_page)

    async def test_empty_ref_or_no_secret_input_does_not_trigger_locator_probe(self):
        action_fn = AsyncMock(return_value="success")

        # 1. ref 为空字符串且无敏感输入
        self.mock_page.locator.reset_mock()
        await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="read_page",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"page": 1, "keyword": "", "refresh": False, "ref": ""},
            required_permission="read",
        )
        self.mock_page.locator.assert_not_called()

        # 2. ref 非空但无敏感文本输入项（如普通点击），不应探测 DOM
        self.mock_page.locator.reset_mock()
        await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "1"},
            required_permission="click",
        )
        self.mock_page.locator.assert_not_called()

        # 3. ref 非空且包含待填入的敏感文本，应当触发探测
        self.mock_page.locator.reset_mock()
        await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="fill",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "2", "text": "secret123"},
            required_permission="fill",
        )
        self.mock_page.locator.assert_called_once_with('[data-astr-ref="2"]')

    async def test_locator_probe_timeout_handled_gracefully(self):
        self.mock_context.get_page_state(self.mock_page).ref_map = {}
        self.mock_locator.get_attribute = AsyncMock(side_effect=TimeoutError("Timeout exceeded"))
        action_fn = AsyncMock(return_value="executed_successfully")

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="fill",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "99", "text": "password"},
            required_permission="fill",
        )
        self.assertEqual(res, "executed_successfully")
        action_fn.assert_awaited_once()

    def test_clean_playwright_error_patterns(self):
        # 1. Overlay intercepts pointer events
        e1 = Exception('<button class="submit"> intercepts pointer events')
        clean1 = clean_playwright_error(e1)
        self.assertIn("目标元素被页面弹层遮挡", clean1)
        self.assertIn("<button>", clean1)

        # 2. Timeout waiting for locator
        e2 = Exception("Timeout 10000ms exceeded waiting for locator")
        clean2 = clean_playwright_error(e2)
        self.assertIn("未能定位到目标元素", clean2)
        self.assertIn("pw_read()", clean2)

        # 3. Generic Timeout
        e3 = Exception("Timeout 10000ms exceeded")
        clean3 = clean_playwright_error(e3)
        self.assertIn("执行未在规定时间内完成", clean3)

        # 4. Strip call log
        e4 = Exception("Something went wrong\nCall log:\n  - extra details")
        clean4 = clean_playwright_error(e4)
        self.assertNotIn("Call log:", clean4)
        self.assertIn("Something went wrong", clean4)

    async def test_execute_action_resolves_ref_across_tabs_and_activates_page(self):
        page2 = MagicMock()
        page2.url = "https://tab2.example.com"
        page2.is_closed = MagicMock(return_value=False)
        page2.bring_to_front = AsyncMock()
        self.mock_context.browser_context.pages = [self.mock_page, page2]
        self.mock_context.pages = [self.mock_page, page2]
        self.mock_context.current_page = page2

        self.mock_context.get_page_state(self.mock_page).ref_map["5"] = {"ref": "5", "tag": "button"}
        self.mock_context.get_page_state(page2).ref_map["20"] = {"ref": "20", "tag": "a"}

        received_pages = []

        async def _action(ctx, page):
            received_pages.append(page)
            return "ok"

        res = await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=_action,
            input_args={"ref": "5"},
            required_permission="click",
        )
        self.assertEqual(res, "ok")
        self.assertIs(self.mock_context.current_page, self.mock_page)
        self.assertEqual(received_pages, [self.mock_page])
        self.mock_sec.check_permission.assert_called_with("u1", "https://example.com", "click")

    async def test_execute_action_password_detection_with_aria_ref(self):
        self.mock_context.get_page_state(self.mock_page).ref_map["15"] = {
            "ref": "15",
            "aria_ref": "e3",
            "role": "textbox",
        }
        self.mock_locator.get_attribute = AsyncMock(return_value="password")
        action_fn = AsyncMock(return_value="ok")

        await self.handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="fill_form",
            target_resource="",
            action_coro_fn=action_fn,
            input_args={"ref": "15", "text": "secret_aria"},
            required_permission="fill",
        )
        self.mock_page.locator.assert_called_once_with("aria-ref=e3")
        logged_args = self.mock_audit.log_action.await_args.kwargs.get("input_args")
        self.assertEqual(logged_args.get("text"), "******")


if __name__ == "__main__":
    unittest.main()
