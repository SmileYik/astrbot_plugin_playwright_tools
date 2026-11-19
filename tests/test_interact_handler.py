import unittest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.handlers.interact_handler import InteractHandler

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

        self.mock_page = MagicMock()
        self.mock_page.url = "https://example.com"
        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.ref_map = {
            1: {"tag": "div", "text": "card1"},
            2: {"tag": "div", "text": "target_bin"},
            3: {"tag": "input", "text": ""}
        }

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = InteractHandler(self.mock_mgr, self.mock_sec, self.mock_audit)

    def test_hover_element(self):
        async def mock_eval(*args, **kwargs):
            return True
        self.mock_page.evaluate = mock_eval
        res = run_coro(self.handler.hover("s1", "u1", ref=1))
        self.assertIn("已成功悬停", res)

    def test_focus_and_blur(self):
        async def mock_eval(*args, **kwargs):
            return True
        self.mock_page.evaluate = mock_eval
        res_focus = run_coro(self.handler.focus("s1", "u1", ref=3))
        self.assertIn("已聚焦", res_focus)
        res_blur = run_coro(self.handler.blur("s1", "u1", ref=3))
        self.assertIn("已失焦", res_blur)

    def test_drag_element_missing_target(self):
        res = run_coro(self.handler.drag("s1", "u1", ref=1, target_ref=99))
        self.assertIn("无效的拖拽目标", res)

    def test_drag_denied_logs_audit(self):
        self.mock_sec.check_permission.return_value = (False, "没有点击权限")
        mock_log = unittest.mock.AsyncMock()
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
        async def mock_eval(*args, **kwargs):
            return True
        self.mock_page.evaluate = mock_eval
        res = run_coro(self.handler.drag("s1", "u1", ref=1, target_ref=2))
        self.assertIn("已成功将元素 [1] 拖拽至 [2]", res)

    def test_press_key(self):
        async def mock_key(key):
            return None
        self.mock_page.keyboard = MagicMock()
        self.mock_page.keyboard.press = mock_key
        res = run_coro(self.handler.press_key("s1", "u1", key="Enter"))
        self.assertIn("已成功向页面发送按键", res)

    def test_permission_denied_focus_and_press(self):
        self.mock_sec.check_permission.return_value = (False, "没有权限")
        res_focus = run_coro(self.handler.focus("s1", "u1", ref=1))
        self.assertIn("聚焦失败: 没有权限", res_focus)

        res_press = run_coro(self.handler.press_key("s1", "u1", key="Enter"))
        self.assertIn("按键失败: 没有权限", res_press)

if __name__ == "__main__":
    unittest.main()
