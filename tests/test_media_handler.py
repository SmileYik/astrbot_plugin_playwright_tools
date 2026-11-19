import unittest
import os
import sys
import tempfile
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.handlers.media_handler import MediaHandler

TEMP_DIR = Path(tempfile.gettempdir()) / "astrbot_test_media_v2"

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

async def fake_wait_for(fut, timeout):
    return await fut

class TestMediaHandler(unittest.TestCase):
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
        self.mock_context.pages = [self.mock_page]
        self.mock_context.ref_map = {1: {"tag": "a", "text": "download-file"}}

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            allow_screenshot_to_ai=True,
            download_dir=str(TEMP_DIR / "downloads")
        )

    def test_screenshot_viewport_chat(self):
        async def mock_screenshot(**kwargs):
            return b"fake_viewport_png"
        self.mock_page.screenshot = mock_screenshot

        res = run_coro(self.handler.screenshot_viewport("s1", "u1", target="chat"))
        self.assertTrue(res.startswith("[IMAGE_PATH:"))

    def test_screenshot_viewport_ai_allowed(self):
        async def mock_screenshot(**kwargs):
            return b"fake_viewport_png"
        self.mock_page.screenshot = mock_screenshot

        res = run_coro(self.handler.screenshot_viewport("s1", "u1", target="ai"))
        self.assertTrue(res.startswith("data:image/png;base64,"))

    def test_screenshot_viewport_ai_disallowed(self):
        handler_no_ai = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            allow_screenshot_to_ai=False,
            download_dir=str(TEMP_DIR / "downloads")
        )
        res = run_coro(handler_no_ai.screenshot_viewport("s1", "u1", target="ai"))
        self.assertIn("拒绝操作", res)

    def test_screenshot_full_height_clipped(self):
        async def mock_eval(script):
            return 12000
        async def mock_screenshot(**kwargs):
            self.assertIn("clip", kwargs)
            return b"fake_clipped_png"
        self.mock_page.evaluate = mock_eval
        self.mock_page.screenshot = mock_screenshot

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.handler.screenshot_full(
                "s1", "u1", target="chat", max_height_px=8000, timeout_sec=15
            ))
        self.assertTrue(res.startswith("[IMAGE_PATH:"))
        self.assertIn("已自动截断", res)

    def test_screenshot_full_timeout_fallback(self):
        import asyncio
        async def mock_eval(script):
            return 4000
        async def mock_screenshot(**kwargs):
            return b"fake_fallback_viewport_png"
        self.mock_page.evaluate = mock_eval
        self.mock_page.screenshot = mock_screenshot

        async def timeout_wait_for(fut, timeout):
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", timeout_wait_for):
            res = run_coro(self.handler.screenshot_full(
                "s1", "u1", target="chat", max_height_px=8000, timeout_sec=15
            ))
        self.assertTrue(res.startswith("[IMAGE_PATH:"))
        self.assertIn("降级为当前视口截图", res)

    def test_download_file_invalid_ref(self):
        res = run_coro(self.handler.download_file("s1", "u1", ref=99))
        self.assertIn("无效的元素引用", res)

if __name__ == "__main__":
    unittest.main()
