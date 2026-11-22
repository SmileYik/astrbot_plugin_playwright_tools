import json
import unittest


class TestConfSchema(unittest.TestCase):
    def test_conf_schema_grouped_structure(self):
        with open("_conf_schema.json", "r", encoding="utf-8") as f:
            schema = json.load(f)

        expected_groups = {"security", "runtime", "browser", "media", "storage_audit"}
        self.assertEqual(set(schema.keys()), expected_groups)

        for group_name, group in schema.items():
            self.assertEqual(group.get("type"), "object", f"Group {group_name} must have type: object")
            self.assertIn("items", group, f"Group {group_name} must contain items")
            self.assertIn("description", group, f"Group {group_name} must have description")

        # 验证 9 项特异交互控件
        # 1. 额外管理员 UID 为列表，使用 sender_id 选择器
        sec = schema["security"]["items"]
        self.assertEqual(sec["extra_admin_uids"]["type"], "list")
        self.assertEqual(sec["extra_admin_uids"]["_special"], "sender_id")
        self.assertEqual(sec["extra_admin_uids"]["default"], [])

        # 2. 上下文隔离模式为下拉框选择
        rt = schema["runtime"]["items"]
        self.assertEqual(rt["context_mode"]["type"], "string")
        self.assertEqual(rt["context_mode"]["options"], ["personal", "session"])
        self.assertEqual(len(rt["context_mode"]["labels"]), 2)
        self.assertEqual(len(rt["context_mode"]["subtitles"]), 2)

        # 3. 空闲销毁时间和单个工具执行超时时间使用拉杆调节
        self.assertEqual(rt["idle_timeout_minutes"]["type"], "int")
        self.assertIn("slider", rt["idle_timeout_minutes"])
        self.assertEqual(rt["idle_timeout_minutes"]["slider"]["min"], 1)
        self.assertEqual(rt["tool_execution_timeout_seconds"]["type"], "int")
        self.assertIn("slider", rt["tool_execution_timeout_seconds"])
        self.assertEqual(rt["tool_execution_timeout_seconds"]["slider"]["min"], 5)

        # 验证底层浏览器进程空闲退出配置
        self.assertIn("browser_idle_timeout_minutes", rt)
        self.assertEqual(rt["browser_idle_timeout_minutes"]["type"], "int")
        self.assertEqual(rt["browser_idle_timeout_minutes"]["default"], 5)
        self.assertEqual(rt["browser_idle_timeout_minutes"]["slider"]["min"], 0)
        self.assertEqual(rt["browser_idle_timeout_minutes"]["slider"]["max"], 120)

        # 4. 长截图的高度限制和超时时间使用拉杆调节
        med = schema["media"]["items"]
        self.assertEqual(med["screenshot_max_height_px"]["type"], "int")
        self.assertIn("slider", med["screenshot_max_height_px"])
        self.assertEqual(med["screenshot_timeout_seconds"]["type"], "int")
        self.assertIn("slider", med["screenshot_timeout_seconds"])

        # 5. 网站白名单与权限集合配置为 template_list，包含域名与权限多选下拉框
        self.assertEqual(sec["whitelist_rules"]["type"], "template_list")
        self.assertIn("templates", sec["whitelist_rules"])
        self.assertIn("rule", sec["whitelist_rules"]["templates"])
        rule_template = sec["whitelist_rules"]["templates"]["rule"]
        self.assertEqual(rule_template.get("display_item"), "domains")
        rule_items = rule_template["items"]
        self.assertEqual(rule_items["domains"]["type"], "list")
        self.assertEqual(rule_items["allowed_actions"]["type"], "list")
        self.assertEqual(
            rule_items["allowed_actions"]["options"],
            [
                "read",
                "click",
                "fill",
                "select",
                "hover",
                "focus",
                "drag",
                "press_key",
                "scroll",
                "screenshot",
                "screenshot_full",
                "download",
            ],
        )
        self.assertEqual(len(rule_items["allowed_actions"]["labels"]), 12)

        # 6. 浏览器适配器为下拉框选择
        br = schema["browser"]["items"]
        self.assertEqual(br["browser_adapter"]["type"], "string")
        self.assertEqual(br["browser_adapter"]["options"], ["camoufox", "playwright"])

        # 7. Playwright 浏览器类型为下拉选择（含 chromium, firefox, webkit, custom），选 custom 强制要求可执行路径
        self.assertEqual(
            br["playwright_browser_type"]["options"],
            ["chromium", "firefox", "webkit", "custom"],
        )
        self.assertEqual(
            br["playwright_browser_type"]["condition"],
            {"browser_adapter": "playwright"},
        )
        self.assertEqual(
            br["browser_executable_path"]["condition"],
            {"playwright_browser_type": "custom"},
        )

        # 8. 截图输出格式为下拉框选择，且 jpeg 时才显示压缩质量
        self.assertEqual(med["screenshot_format"]["options"], ["png", "jpeg"])
        self.assertEqual(
            med["screenshot_quality"]["condition"],
            {"screenshot_format": "jpeg"},
        )

        # 9. 压缩质量使用拉杆调节
        self.assertEqual(med["screenshot_quality"]["type"], "int")
        self.assertIn("slider", med["screenshot_quality"])
        self.assertEqual(med["screenshot_quality"]["slider"]["min"], 1)
        self.assertEqual(med["screenshot_quality"]["slider"]["max"], 100)

        # 验证分组 5 默认折叠
        self.assertTrue(schema["storage_audit"].get("collapsed", False))

    def test_new_extraction_and_security_config_schema(self):
        with open("_conf_schema.json", "r", encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("mask_password_inputs", schema["security"]["items"])
        self.assertIn("content_extraction_mode", schema["runtime"]["items"])
        self.assertIn("page_chunk_char_limit", schema["runtime"]["items"])
        self.assertEqual(schema["runtime"]["items"]["page_chunk_char_limit"]["default"], 2000)
        self.assertTrue(schema["security"]["items"]["mask_password_inputs"]["default"])

    def test_storage_paths_default_in_schema(self):
        with open("_conf_schema.json", "r", encoding="utf-8") as f:
            schema = json.load(f)
        storage_items = schema["storage_audit"]["items"]
        self.assertEqual(
            storage_items["download_save_path"]["default"],
            "data/plugin_data/astrbot_plugin_playwright_tools/downloads",
        )
        self.assertEqual(
            storage_items["screenshot_save_path"]["default"],
            "data/plugin_data/astrbot_plugin_playwright_tools/screenshots",
        )

    def test_no_logging_import_in_codebase(self):
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent
        for sub_dir in ["tools", "core", "adapts", "api"]:
            for py_file in (repo_root / sub_dir).rglob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                self.assertNotIn(
                    "import logging",
                    content,
                    f"File {py_file} must not contain 'import logging'. Use 'from astrbot.api import logger' instead.",
                )
        main_py = repo_root / "main.py"
        if main_py.exists():
            content = main_py.read_text(encoding="utf-8")
            self.assertNotIn(
                "import logging",
                content,
                f"File {main_py} must not contain 'import logging'. Use 'from astrbot.api import logger' instead.",
            )



if __name__ == "__main__":
    unittest.main()
