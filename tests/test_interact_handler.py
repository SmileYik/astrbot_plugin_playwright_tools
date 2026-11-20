import unittest
import os
import sys
from unittest.mock import MagicMock, AsyncMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from astrbot_plugin_playwright_tools.tools.handlers.interact_handler import InteractHandler, clean_playwright_error

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestInteractHandler(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_audit = MagicMock()

        async def mock_log(*args, **kwargs):
            return None
        self.mock_audit.log_action = mock_log

        self.mock_locator = AsyncMock()
        self.mock_page = MagicMock()
        self.mock_page.url = "https://example.com"
        self.mock_page.locator.return_value = self.mock_locator
        self.mock_page.keyboard = AsyncMock()
        self.mock_page.mouse = AsyncMock()

        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.last_dialog_message = None
        self.mock_context.ref_map = {
            1: {"tag": "button", "text": "btn1"},
            2: {"tag": "div", "text": "target_bin"},
            3: {"tag": "input", "text": ""},
            4: {"tag": "select", "text": ""}
        }

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = InteractHandler(self.mock_mgr, self.mock_sec, self.mock_audit)

    def test_click_element(self):
        res = run_coro(self.handler.click("s1", "u1", ref=1))
        self.assertIn("已成功点击 [1]", res)
        self.mock_page.locator.assert_called_with('[data-astr-ref="1"]')
        self.mock_locator.click.assert_called_once()

    def test_fill_form(self):
        res = run_coro(self.handler.fill_form("s1", "u1", ref=3, text="Hello Playwright"))
        self.assertIn("已成功在输入框 [3] 填入内容", res)
        self.mock_page.locator.assert_called_with('[data-astr-ref="3"]')
        self.mock_locator.fill.assert_called_with("Hello Playwright", timeout=10000)

    def test_select_option(self):
        res = run_coro(self.handler.select_option("s1", "u1", ref=4, value="opt2"))
        self.assertIn("已在下拉框 [4] 成功选取 'opt2'", res)
        self.mock_page.locator.assert_called_with('[data-astr-ref="4"]')
        self.mock_locator.select_option.assert_called()

    def test_hover_element(self):
        res = run_coro(self.handler.hover("s1", "u1", ref=1))
        self.assertIn("已成功悬停在元素 [1]", res)
        self.mock_page.locator.assert_called_with('[data-astr-ref="1"]')
        self.mock_locator.hover.assert_called_once()

    def test_focus_and_blur(self):
        res_focus = run_coro(self.handler.focus("s1", "u1", ref=3))
        self.assertIn("已聚焦到元素 [3]", res_focus)
        self.mock_locator.focus.assert_called_once()

        res_blur = run_coro(self.handler.blur("s1", "u1", ref=3))
        self.assertIn("元素 [3] 已失焦", res_blur)
        self.mock_locator.evaluate.assert_called_with("el => el.blur()")

    def test_drag_element_missing_target(self):
        res = run_coro(self.handler.drag("s1", "u1", ref=1, target_ref=99))
        self.assertIn("无效的拖拽目标", res)

    def test_drag_denied_logs_audit(self):
        self.mock_sec.check_permission.return_value = (False, "没有点击权限")
        mock_log = AsyncMock()
        self.mock_audit.log_action = mock_log
        res = run_coro(self.handler.drag("s1", "u1", ref=1, target_ref=2, session_name="群1", sender_name="用户1"))
        self.assertIn("拖拽失败: 没有点击权限", res)
        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        self.assertEqual(kwargs.get("is_permitted"), False)
        self.assertEqual(kwargs.get("deny_reason"), "没有点击权限")
        self.assertEqual(kwargs.get("session_name"), "群1")
        self.assertEqual(kwargs.get("sender_name"), "用户1")

    def test_drag_element_success(self):
        target_locator = AsyncMock()
        def mock_loc(sel):
            if 'data-astr-ref="1"' in sel:
                return self.mock_locator
            return target_locator
        self.mock_page.locator.side_effect = mock_loc

        res = run_coro(self.handler.drag("s1", "u1", ref=1, target_ref=2))
        self.assertIn("已成功将元素 [1] 拖拽至 [2]", res)
        self.mock_locator.drag_to.assert_called_with(target_locator, timeout=10000)

    def test_press_key(self):
        res = run_coro(self.handler.press_key("s1", "u1", key="Enter"))
        self.assertIn("已成功向页面发送按键", res)
        self.mock_page.keyboard.press.assert_called_with("Enter")

    def test_scroll(self):
        res = run_coro(self.handler.scroll("s1", "u1", direction="down", amount=300))
        self.assertIn("页面已向下滚动 300 像素", res)
        self.mock_page.mouse.wheel.assert_called_with(0, 300)

    def test_permission_denied_focus_and_press(self):
        self.mock_sec.check_permission.return_value = (False, "没有权限")
        res_focus = run_coro(self.handler.focus("s1", "u1", ref=1))
        self.assertIn("聚焦失败: 没有权限", res_focus)

        res_press = run_coro(self.handler.press_key("s1", "u1", key="Enter"))
        self.assertIn("按键失败: 没有权限", res_press)

    def test_clean_playwright_error_strips_call_log(self):
        raw_error = Exception(
            "Locator.click: Timeout 10000ms exceeded.\n"
            "Call log:\n"
            "  - waiting for locator(\"[data-astr-ref=\\\"311\\\"]\")\n"
            "  - <dialog open=\"\" role=\"dialog\"> intercepts pointer events\n"
        )
        cleaned = clean_playwright_error(raw_error)
        self.assertNotIn("Call log:", cleaned)
        self.assertIn("页面弹层遮挡", cleaned)
        self.assertIn("[推荐操作:", cleaned)

if __name__ == "__main__":
    unittest.main()
