import unittest
import json
import os
import sys
import tempfile
import yaml
from pathlib import Path
from unittest.mock import MagicMock

TEMP_DIR = Path(tempfile.gettempdir()) / "astrbot_test_plugin_main"

# Ensure mock astrbot is available before importing main
def _mock_dec(*args, **kwargs):
    def wrap(f):
        return f
    return wrap

mock_astrbot = MagicMock()
mock_api = MagicMock()
mock_event = MagicMock()
mock_filter = MagicMock()
mock_filter.command.side_effect = _mock_dec
mock_filter.on_llm_request.side_effect = _mock_dec
mock_filter.llm_tool.side_effect = _mock_dec
mock_event.filter = mock_filter

mock_star_module = MagicMock()
mock_star_module.register.side_effect = _mock_dec
class Star:
    def __init__(self, ctx):
        self.context = ctx
mock_star_module.Star = Star

sys.modules["astrbot"] = mock_astrbot
sys.modules["astrbot.api"] = mock_api
sys.modules["astrbot.api.event"] = mock_event
sys.modules["astrbot.api.star"] = mock_star_module

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import main

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestPluginMain(unittest.TestCase):
    def test_conf_schema_valid_json(self):
        schema_path = Path("_conf_schema.json")
        self.assertTrue(schema_path.exists(), "_conf_schema.json must exist")
        with open(schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("admin_only", data)
        self.assertIn("allow_screenshot_to_ai", data)
        self.assertIn("context_mode", data)
        self.assertIn("whitelist_rules", data)
        self.assertIn("idle_timeout_minutes", data)
        self.assertIn("audit_retention_days", data)

    def test_metadata_synced(self):
        meta_path = Path("metadata.yaml")
        self.assertTrue(meta_path.exists())
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f)
        self.assertEqual(meta["name"], "astrbot_plugin_playwright_tools")
        self.assertEqual(meta["display_name"], "PlaywrightTool")
        self.assertEqual(meta["version"], "v2.0.1")

    def test_conf_schema_v2_fields(self):
        with open("_conf_schema.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("tool_execution_timeout_seconds", data)
        self.assertIn("screenshot_max_height_px", data)
        self.assertIn("screenshot_timeout_seconds", data)
        self.assertIn("system_prompt_injection", data)

    def test_plugin_init_and_tool_registration(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "reg_test.db")
        mock_ctx = MagicMock()
        mock_ctx.add_llm_tools = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
            "tool_execution_timeout_seconds": 25,
            "system_prompt_injection": "你是一个网页浏览助手。",
        })
        mock_ctx.add_llm_tools.assert_called_once()
        tools_registered = mock_ctx.add_llm_tools.call_args[0]
        self.assertEqual(len(tools_registered), 3)
        tool_names = [t.name for t in tools_registered]
        self.assertIn("pw_page", tool_names)
        self.assertIn("pw_interact", tool_names)
        self.assertIn("pw_media", tool_names)

    def test_on_llm_request_injection(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "inj_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
            "system_prompt_injection": "CUSTOM_PROMPT",
        })
        req = MagicMock()
        req.system_prompt = "ORIGINAL_PROMPT"
        event = MagicMock()
        run_coro(plugin.on_llm_request(event, req))
        self.assertEqual(req.system_prompt, "ORIGINAL_PROMPT\n\nCUSTOM_PROMPT")

    def test_on_llm_request_empty_no_injection(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "empty_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
            "system_prompt_injection": "",
        })
        req = MagicMock()
        req.system_prompt = "ORIGINAL_PROMPT"
        event = MagicMock()
        event.get_sender_id.return_value = "admin_999"
        event.is_admin.return_value = True

        run_coro(plugin.on_llm_request(event, req))
        self.assertEqual(req.system_prompt, "ORIGINAL_PROMPT")
        self.assertIn("admin_999", plugin.security_manager.admin_uids)

if __name__ == "__main__":
    unittest.main()
