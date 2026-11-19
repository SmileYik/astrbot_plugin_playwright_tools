import unittest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.handlers.page_handler import PageHandler
from core.page_extractor import PageExtractor

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestPageHandler(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_sec.is_url_allowed_navigation.return_value = (True, "")
        self.mock_audit = MagicMock()

        async def mock_log(*args, **kwargs):
            return None
        self.mock_audit.log_action = mock_log

        self.extractor = PageExtractor()

        self.mock_page = MagicMock()
        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.ref_map = {}
        self.mock_context.pages = [self.mock_page]

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = PageHandler(self.mock_mgr, self.mock_sec, self.mock_audit, self.extractor)

    def test_search_page_action(self):
        async def mock_eval(script):
            return {
                "title": "Test Page",
                "url": "https://test.com",
                "elements": [
                    {"tag": "button", "text": "确认申请", "type": "", "name": "", "placeholder": "", "value": ""}
                ],
                "text_blocks": ["这里包含重要搜索关键词内容"]
            }
        self.mock_page.evaluate = mock_eval

        res = run_coro(self.handler.search_page("s1", "u1", keyword="搜索关键词"))
        self.assertIn("找到", res)
        self.assertIn("重要搜索关键词内容", res)

    def test_handle_dialog_action(self):
        res = run_coro(self.handler.handle_dialog("s1", "u1", action="dismiss"))
        self.assertEqual(self.mock_context.dialog_action, {"action": "dismiss", "prompt_text": None})
        self.assertIn("已预设", res)

    def test_switch_tab_out_of_bounds(self):
        res = run_coro(self.handler.switch_tab("s1", "u1", tab_index=99))
        self.assertIn("超出范围", res)

if __name__ == "__main__":
    unittest.main()
