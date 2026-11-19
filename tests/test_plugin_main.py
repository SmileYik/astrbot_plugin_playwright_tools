import unittest
import json
import os
import sys
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
        self.assertEqual(meta["version"], "v1.0.0")

if __name__ == "__main__":
    unittest.main()
