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
        self.assertEqual(rule_template.get("display_item"), "domain")
        rule_items = rule_template["items"]
        self.assertEqual(rule_items["domain"]["type"], "string")
        self.assertEqual(rule_items["allowed_actions"]["type"], "list")
        self.assertEqual(
            rule_items["allowed_actions"]["options"],
            ["read", "click", "fill", "scroll", "screenshot", "download"],
        )

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


if __name__ == "__main__":
    unittest.main()
