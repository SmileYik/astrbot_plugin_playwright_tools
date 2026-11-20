import unittest
import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from astrbot_plugin_playwright_tools.adapts.base import BrowserAdapterBase
from astrbot_plugin_playwright_tools.adapts.camoufox_adapter import CamoufoxAdapter

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestBrowserAdapter(unittest.TestCase):
    def test_adapter_interface(self):
        adapter = CamoufoxAdapter(headless=True)
        self.assertIsInstance(adapter, BrowserAdapterBase)

    @patch("astrbot_plugin_playwright_tools.adapts.camoufox_adapter.AsyncCamoufox")
    def test_start_and_create_context(self, mock_camoufox):
        mock_instance = MagicMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        
        # mock async context manager (__aenter__)
        async def mock_aenter(*args, **kwargs):
            return mock_browser
        async def mock_aexit(*args, **kwargs):
            return None
        mock_instance.__aenter__ = mock_aenter
        mock_instance.__aexit__ = mock_aexit
        mock_camoufox.return_value = mock_instance

        adapter = CamoufoxAdapter(headless=True)
        run_coro(adapter.start())
        ctx = run_coro(adapter.create_context(storage_state_path="test_state.json"))
        self.assertIsNotNone(ctx)
        run_coro(adapter.stop())

if __name__ == "__main__":
    unittest.main()
