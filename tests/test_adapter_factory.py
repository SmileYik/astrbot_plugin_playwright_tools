import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

if "astrbot" not in sys.modules:
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()

# 确保路径能够导入项目模块
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import pytest
except ImportError:
    class _MockMark:
        @staticmethod
        def asyncio(fn):
            return fn
    class _MockPytest:
        mark = _MockMark()
    pytest = _MockPytest()

from adapts.factory import AdapterFactory
from adapts.camoufox_adapter import CamoufoxAdapter
from adapts.playwright_adapter import PlaywrightAdapter


def test_adapter_factory_create_camoufox():
    config = {
        "browser_adapter": "camoufox",
        "browser_headless": True,
        "camoufox_geoip": True,
        "browser_window_width": 1920,
        "browser_window_height": 1080,
        "browser_user_agent": "Mozilla/5.0 TestUA",
    }
    adapter = AdapterFactory.create(config)
    assert isinstance(adapter, CamoufoxAdapter)
    assert adapter.headless is True
    assert adapter.geoip is True
    assert adapter.window_width == 1920
    assert adapter.window_height == 1080
    assert adapter.user_agent == "Mozilla/5.0 TestUA"


def test_adapter_factory_create_playwright():
    config = {
        "browser_adapter": "playwright",
        "playwright_browser_type": "firefox",
        "browser_headless": False,
        "browser_window_width": 1440,
        "browser_window_height": 900,
        "browser_user_agent": "Firefox/120.0",
        "browser_executable_path": "  C:/Program Files/Chrome/chrome.exe  ",
    }
    adapter = AdapterFactory.create(config)
    assert isinstance(adapter, PlaywrightAdapter)
    assert adapter.browser_type == "firefox"
    assert adapter.headless is False
    assert adapter.window_width == 1440
    assert adapter.window_height == 900
    assert adapter.user_agent == "Firefox/120.0"
    assert adapter.executable_path == "C:/Program Files/Chrome/chrome.exe"


@pytest.mark.asyncio
async def test_playwright_adapter_create_context():
    adapter = PlaywrightAdapter(browser_type="chromium", window_width=1280, window_height=720, user_agent="CustomUA")
    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock()
    adapter._browser = mock_browser

    await adapter.create_context()
    mock_browser.new_context.assert_called_once_with(
        viewport={"width": 1280, "height": 720},
        user_agent="CustomUA"
    )


@pytest.mark.asyncio
async def test_camoufox_adapter_create_context_applies_viewport_and_ua():
    adapter = CamoufoxAdapter(window_width=1920, window_height=1080, user_agent="CamouUA")
    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock()
    adapter._browser = mock_browser

    await adapter.create_context()
    mock_browser.new_context.assert_called_once_with(
        viewport={"width": 1920, "height": 1080},
        user_agent="CamouUA"
    )


def run_coro(coro):
    """在无网络沙箱环境下无开销执行普通协程，规避 socket.socketpair 挂起问题。"""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value


class TestAdapterFactory(unittest.TestCase):
    def test_adapter_factory_create_camoufox(self):
        test_adapter_factory_create_camoufox()

    def test_adapter_factory_create_playwright(self):
        test_adapter_factory_create_playwright()

    def test_adapter_factory_grouped_browser_config(self):
        config = {
            "browser": {
                "browser_adapter": "playwright",
                "playwright_browser_type": "webkit",
                "browser_headless": True,
            }
        }
        adapter = AdapterFactory.create(config)
        self.assertIsInstance(adapter, PlaywrightAdapter)
        self.assertEqual(adapter.browser_type, "webkit")

    def test_adapter_factory_custom_browser_without_path_raises(self):
        config = {
            "browser": {
                "browser_adapter": "playwright",
                "playwright_browser_type": "custom",
                "browser_executable_path": "",
            }
        }
        with self.assertRaises(ValueError) as ctx:
            AdapterFactory.create(config)
        self.assertIn("必须指定可执行文件路径", str(ctx.exception))

    def test_adapter_factory_custom_browser_with_path_maps_chromium(self):
        config = {
            "browser": {
                "browser_adapter": "playwright",
                "playwright_browser_type": "custom",
                "browser_executable_path": "C:/Browser/chrome.exe",
            }
        }
        adapter = AdapterFactory.create(config)
        self.assertIsInstance(adapter, PlaywrightAdapter)
        self.assertEqual(adapter.browser_type, "chromium")
        self.assertEqual(adapter.executable_path, "C:/Browser/chrome.exe")

    def test_adapter_factory_default(self):
        adapter = AdapterFactory.create({})
        self.assertIsInstance(adapter, CamoufoxAdapter)
        self.assertTrue(adapter.headless)
        self.assertFalse(adapter.geoip)
        self.assertEqual(adapter.window_width, 1280)
        self.assertEqual(adapter.window_height, 720)
        self.assertEqual(adapter.user_agent, "")

    def test_adapter_factory_unsupported_type(self):
        with self.assertRaises(ValueError):
            AdapterFactory.create({"browser_adapter": "unsupported_xyz"})

    def test_playwright_adapter_create_context(self):
        run_coro(test_playwright_adapter_create_context())

    def test_camoufox_adapter_create_context_applies_viewport_and_ua(self):
        run_coro(test_camoufox_adapter_create_context_applies_viewport_and_ua())

    @patch("adapts.playwright_adapter.async_playwright")
    def test_playwright_adapter_start_and_stop(self, mock_async_playwright):
        mock_cm = MagicMock()
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_cm.start = AsyncMock(return_value=mock_pw)
        mock_cm.stop = AsyncMock(return_value=None)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.close = AsyncMock(return_value=None)
        mock_async_playwright.return_value = mock_cm

        adapter = PlaywrightAdapter(browser_type="chromium", headless=True)
        self.assertIsNone(adapter.browser)
        run_coro(adapter.start())
        self.assertEqual(adapter.browser, mock_browser)

        run_coro(adapter.stop())
        self.assertIsNone(adapter.browser)
        mock_browser.close.assert_called_once()
        mock_cm.stop.assert_called_once()

    @patch("adapts.playwright_adapter.async_playwright")
    def test_playwright_adapter_invalid_browser_type(self, mock_async_playwright):
        mock_cm = MagicMock()
        mock_pw = MagicMock()
        mock_cm.start = AsyncMock(return_value=mock_pw)
        mock_pw.invalid_type = None
        mock_async_playwright.return_value = mock_cm

        adapter = PlaywrightAdapter(browser_type="invalid_type")
        with self.assertRaises(ValueError):
            run_coro(adapter.start())

    @patch("adapts.playwright_adapter.async_playwright")
    def test_playwright_adapter_start_with_custom_executable_path(self, mock_async_playwright):
        mock_cm = MagicMock()
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_cm.start = AsyncMock(return_value=mock_pw)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_async_playwright.return_value = mock_cm

        adapter = PlaywrightAdapter(browser_type="chromium", executable_path="C:/custom/chrome.exe")
        run_coro(adapter.start())
        mock_pw.chromium.launch.assert_called_once_with(
            headless=True,
            executable_path="C:/custom/chrome.exe"
        )

    @patch("adapts.playwright_adapter.async_playwright")
    def test_playwright_adapter_disconnect_callback_and_is_running(self, mock_async_playwright):
        mock_cm = MagicMock()
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_cm.start = AsyncMock(return_value=mock_pw)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_async_playwright.return_value = mock_cm

        adapter = PlaywrightAdapter(browser_type="chromium")
        self.assertFalse(adapter.is_running)

        called = []
        adapter.set_disconnect_callback(lambda: called.append("disconnected"))

        run_coro(adapter.start())
        self.assertTrue(adapter.is_running)
        mock_browser.on.assert_called_once()
        event_name, handler = mock_browser.on.call_args[0]
        self.assertEqual(event_name, "disconnected")

        # 触发 disconnected 回调
        handler()
        self.assertEqual(called, ["disconnected"])
        self.assertIsNone(adapter.browser)
        self.assertFalse(adapter.is_running)

    def test_camoufox_adapter_disconnect_callback_and_is_running(self):
        adapter = CamoufoxAdapter()
        self.assertFalse(adapter.is_running)

        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        adapter._browser = mock_browser
        self.assertTrue(adapter.is_running)

        called = []
        adapter.set_disconnect_callback(lambda: called.append("camoufox_disconnected"))

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        with patch("adapts.camoufox_adapter.AsyncCamoufox", return_value=mock_cm):
            adapter._browser = None
            run_coro(adapter.start())
            self.assertTrue(adapter.is_running)
            mock_browser.on.assert_called_once()
            event_name, handler = mock_browser.on.call_args[0]
            self.assertEqual(event_name, "disconnected")
            handler()
            self.assertEqual(called, ["camoufox_disconnected"])
            self.assertIsNone(adapter.browser)
            self.assertFalse(adapter.is_running)


if __name__ == "__main__":
    unittest.main()
