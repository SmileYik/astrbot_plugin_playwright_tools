import unittest
import os
import sys
import tempfile
import base64
import time
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

if "astrbot" not in sys.modules:
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from astrbot_plugin_playwright_tools.tools.handlers.media_handler import MediaHandler

TEMP_DIR = Path(tempfile.gettempdir()) / "astrbot_test_media_v2"

def run_coro(coro):
    return asyncio.run(coro)

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
        self.mock_page.wait_for_load_state = AsyncMock()
        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.pages = [self.mock_page]
        self.mock_context.ref_map = {
            "1": {"tag": "a", "text": "download-file"},
            "e1": {"ref": "e1"},
            1: {"tag": "a", "text": "download-file"}
        }

        async def mock_resolve(session_id, sender_id, **kwargs):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            allow_screenshot_to_ai=True,
            download_dir=str(TEMP_DIR / "downloads"),
            screenshot_dir=str(TEMP_DIR / "screenshots"),
            audit_screenshots_dir=str(TEMP_DIR / "audit_screenshots"),
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
        res = run_coro(self.handler.download_file("s1", "u1", ref="99"))
        self.assertIn("无效的元素引用", res)

    def test_download_file_denied_logs_audit(self):
        self.mock_sec.check_permission.return_value = (False, "黑名单拦截下载")
        mock_log = unittest.mock.AsyncMock()
        self.mock_audit.log_action = mock_log
        res = run_coro(self.handler.download_file("s1", "u1", ref="1", session_name="群1", sender_name="用户1"))
        self.assertIn("下载失败: 黑名单拦截下载", res)
        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        self.assertEqual(kwargs.get("is_permitted"), False)
        self.assertEqual(kwargs.get("deny_reason"), "黑名单拦截下载")
        self.assertEqual(kwargs.get("session_name"), "群1")
        self.assertEqual(kwargs.get("sender_name"), "用户1")

    def test_download_file_aria_ref_locator(self):
        mock_download = MagicMock()
        mock_download.suggested_filename = "test.pdf"
        mock_download.save_as = AsyncMock()

        async def get_download():
            return mock_download

        class DummyEventInfo:
            @property
            def value(self):
                return get_download()

        class DummyExpectDownload:
            async def __aenter__(self):
                return DummyEventInfo()
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        self.mock_page.expect_download = MagicMock(return_value=DummyExpectDownload())
        mock_loc = AsyncMock()
        self.mock_page.locator = MagicMock(return_value=mock_loc)

        res = run_coro(self.handler.download_file("s1", "u1", ref="e1"))
        self.mock_page.locator.assert_called_with("aria-ref=e1")
        self.assertIn("已成功下载文件: test.pdf", res)

    def test_passive_cleanup_removes_expired_files(self):
        clean_dir = TEMP_DIR / "cleanup_test"
        dl_dir = clean_dir / "downloads"
        shot_dir = clean_dir / "screenshots"
        audit_dir = clean_dir / "audit"
        for d in (dl_dir, shot_dir, audit_dir):
            d.mkdir(parents=True, exist_ok=True)

        old_dl = dl_dir / "old_download.txt"
        new_dl = dl_dir / "new_download.txt"
        old_shot = shot_dir / "old_shot.jpg"
        new_shot = shot_dir / "new_shot.png"
        old_audit = audit_dir / "old_audit.jpg"
        new_audit = audit_dir / "new_audit.png"

        for f in (old_dl, new_dl, old_shot, new_shot, old_audit, new_audit):
            f.write_text("data")

        # 8 days ago (> 7 days)
        old_mtime = time.time() - 8 * 86400
        for f in (old_dl, old_shot, old_audit):
            os.utime(str(f), (old_mtime, old_mtime))

        handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            download_dir=str(dl_dir),
            screenshot_dir=str(shot_dir),
            audit_screenshots_dir=str(audit_dir),
            file_retention_days=7,
        )

        deleted = run_coro(handler.cleanup_expired_files())
        self.assertEqual(deleted, 3)

        self.assertFalse(old_dl.exists())
        self.assertFalse(old_shot.exists())
        self.assertFalse(old_audit.exists())
        self.assertTrue(new_dl.exists())
        self.assertTrue(new_shot.exists())
        self.assertTrue(new_audit.exists())

    def test_passive_cleanup_disabled_when_zero_or_negative(self):
        clean_dir = TEMP_DIR / "cleanup_disabled_test"
        dl_dir = clean_dir / "downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        old_dl = dl_dir / "old_download.txt"
        old_dl.write_text("data")
        old_mtime = time.time() - 30 * 86400
        os.utime(str(old_dl), (old_mtime, old_mtime))

        handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            download_dir=str(dl_dir),
            file_retention_days=0,
        )

        deleted = run_coro(handler.cleanup_expired_files())
        self.assertEqual(deleted, 0)
        self.assertTrue(old_dl.exists())

    def test_screenshot_format_and_quality_jpeg(self):
        shot_dir = TEMP_DIR / "screenshots_jpeg"
        shot_dir.mkdir(parents=True, exist_ok=True)

        screenshot_calls = []
        async def mock_screenshot(**kwargs):
            screenshot_calls.append(kwargs)
            return b"fake_jpeg_content"
        self.mock_page.screenshot = mock_screenshot

        handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            screenshot_dir=str(shot_dir),
            audit_screenshots_dir=str(TEMP_DIR / "audit_screenshots"),
            screenshot_format="jpeg",
            screenshot_quality=85,
        )

        res = run_coro(handler.screenshot_viewport("s1", "u1", target="chat"))
        self.assertEqual(len(screenshot_calls), 1)
        self.assertEqual(screenshot_calls[0].get("type"), "jpeg")
        self.assertEqual(screenshot_calls[0].get("quality"), 85)
        self.assertEqual(screenshot_calls[0].get("full_page"), False)

        self.assertTrue(res.startswith("[IMAGE_PATH:"))
        self.assertTrue(res.endswith(".jpg]"))
        file_path = res.replace("[IMAGE_PATH:", "").replace("]", "").strip()
        self.assertTrue(os.path.exists(file_path))

    def test_screenshot_format_png_default(self):
        shot_dir = TEMP_DIR / "screenshots_png"
        shot_dir.mkdir(parents=True, exist_ok=True)

        screenshot_calls = []
        async def mock_screenshot(**kwargs):
            screenshot_calls.append(kwargs)
            return b"fake_png_content"
        self.mock_page.screenshot = mock_screenshot

        handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            screenshot_dir=str(shot_dir),
            audit_screenshots_dir=str(TEMP_DIR / "audit_screenshots"),
            screenshot_format="png",
        )

        res = run_coro(handler.screenshot_viewport("s1", "u1", target="chat"))
        self.assertEqual(len(screenshot_calls), 1)
        self.assertIn(screenshot_calls[0].get("type"), (None, "png"))
        self.assertNotIn("quality", screenshot_calls[0])
        self.assertEqual(screenshot_calls[0].get("full_page"), False)

        self.assertTrue(res.startswith("[IMAGE_PATH:"))
        self.assertTrue(res.endswith(".png]"))

    def test_screenshot_viewport_jpeg_ai_target(self):
        async def mock_screenshot(**kwargs):
            return b"fake_jpeg_for_ai"
        self.mock_page.screenshot = mock_screenshot

        handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            allow_screenshot_to_ai=True,
            audit_screenshots_dir=str(TEMP_DIR / "audit_screenshots"),
            screenshot_format="jpg",
            screenshot_quality=75,
        )

        res = run_coro(handler.screenshot_viewport("s1", "u1", target="ai"))
        self.assertTrue(res.startswith("data:image/jpeg;base64,"))

    def test_screenshot_full_jpeg_parameters(self):
        shot_dir = TEMP_DIR / "screenshots_full_jpeg"
        shot_dir.mkdir(parents=True, exist_ok=True)

        screenshot_calls = []
        async def mock_eval(script):
            return 2000
        async def mock_screenshot(**kwargs):
            screenshot_calls.append(kwargs)
            return b"fake_full_jpeg_bytes"
        self.mock_page.evaluate = mock_eval
        self.mock_page.screenshot = mock_screenshot

        handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            screenshot_dir=str(shot_dir),
            audit_screenshots_dir=str(TEMP_DIR / "audit_screenshots"),
            screenshot_format="jpeg",
            screenshot_quality=90,
        )

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(handler.screenshot_full("s1", "u1", target="chat"))

        self.assertEqual(len(screenshot_calls), 1)
        self.assertEqual(screenshot_calls[0].get("type"), "jpeg")
        self.assertEqual(screenshot_calls[0].get("quality"), 90)
        self.assertEqual(screenshot_calls[0].get("full_page"), True)
        self.assertTrue(res.endswith(".jpg]"))

    def test_passive_cleanup_triggered_by_screenshot_and_download(self):
        handler = MediaHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            download_dir=str(TEMP_DIR / "downloads"),
            screenshot_dir=str(TEMP_DIR / "screenshots"),
            audit_screenshots_dir=str(TEMP_DIR / "audit_screenshots"),
            file_retention_days=7,
        )
        cleanup_mock = unittest.mock.AsyncMock(return_value=0)
        handler.cleanup_expired_files = cleanup_mock

        async def mock_screenshot(**kwargs):
            return b"shot"
        self.mock_page.screenshot = mock_screenshot

        run_coro(handler.screenshot_viewport("s1", "u1", target="chat"))
        self.assertEqual(cleanup_mock.call_count, 1)

        with patch("asyncio.wait_for", fake_wait_for):
            async def mock_eval(script):
                return 1000
            self.mock_page.evaluate = mock_eval
            run_coro(handler.screenshot_full("s1", "u1", target="chat"))
        self.assertEqual(cleanup_mock.call_count, 2)

        run_coro(handler.download_file("s1", "u1", ref=999))
        self.assertEqual(cleanup_mock.call_count, 3)

if __name__ == "__main__":
    unittest.main()
