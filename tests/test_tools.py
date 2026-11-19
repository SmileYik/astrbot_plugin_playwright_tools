import unittest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.browse_tools import BrowseTools
from tools.action_tools import ActionTools
from tools.media_tools import MediaTools
from tools.dialog_tools import DialogTools

TEMP_DIR = Path(tempfile.gettempdir()) / "astrbot_test_tools"

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestTools(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_sec.is_url_allowed_navigation.return_value = (True, "")
        self.mock_audit = MagicMock()
        self.mock_extractor = MagicMock()

        # async methods on mock_mgr and mock_audit
        async def mock_log_action(*args, **kwargs):
            return None
        self.mock_audit.log_action = mock_log_action

        self.mock_page = MagicMock()
        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.ref_map = {}
        self.mock_context.pages = [self.mock_page]

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.browse_tools = BrowseTools(self.mock_mgr, self.mock_sec, self.mock_audit, self.mock_extractor)
        self.action_tools = ActionTools(self.mock_mgr, self.mock_sec, self.mock_audit)
        self.media_tools = MediaTools(
            self.mock_mgr, self.mock_sec, self.mock_audit,
            allow_screenshot_to_ai=False,
            download_dir=str(TEMP_DIR / "downloads")
        )
        self.dialog_tools = DialogTools(self.mock_mgr, self.mock_sec, self.mock_audit)

    def test_screenshot_rejected_when_ai_target_disabled(self):
        res = run_coro(self.media_tools.take_screenshot(
            session_id="s1", sender_id="u1", target="ai"
        ))
        self.assertIn("未开启将截图发送给大模型", res)

    def test_screenshot_chat_target_success(self):
        async def mock_screenshot(*args, **kwargs):
            return b"fake_png_data"
        async def mock_eval(*args, **kwargs):
            return 123456789
        self.mock_page.screenshot = mock_screenshot
        self.mock_page.evaluate = mock_eval

        res = run_coro(self.media_tools.take_screenshot(
            session_id="s1", sender_id="u1", target="chat"
        ))
        self.assertTrue(res.startswith("[IMAGE_PATH:"))

    def test_navigation_guard_blocks_unauthorized_url(self):
        self.mock_sec.is_url_allowed_navigation.return_value = (False, "域名不在白名单中")
        res = run_coro(self.browse_tools.open_url(
            session_id="s1", sender_id="u1", url="https://forbidden.com"
        ))
        self.assertIn("域名不在白名单中", res)

    def test_stale_ref_handling(self):
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_page.url = "https://example.com"
        # ref_map is empty -> ref 99 does not exist
        res = run_coro(self.action_tools.click(
            session_id="s1", sender_id="u1", ref=99
        ))
        self.assertIn("无效的元素引用", res)

    def test_handle_dialog_sets_action(self):
        res = run_coro(self.dialog_tools.handle_dialog(
            session_id="s1", sender_id="u1", action="dismiss"
        ))
        self.assertEqual(self.mock_context.dialog_action, {"action": "dismiss", "prompt_text": None})
        self.assertIn("已预设", res)

if __name__ == "__main__":
    unittest.main()
