import unittest
import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

if "astrbot" not in sys.modules:
    from unittest.mock import MagicMock
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()
from astrbot_plugin_playwright_tools.core.security_manager import SecurityManager

class TestSecurityManager(unittest.TestCase):
    def setUp(self):
        rules = [
            {"domains": ["*.github.com"], "allowed_actions": ["read", "click", "scroll"]},
            {"domains": ["example.com"], "allowed_actions": ["read", "click", "fill", "screenshot"]}
        ]
        self.sec = SecurityManager(
            admin_only=False,
            admin_uids=["admin_1"],
            whitelist_rules=rules,
            admin_bypass=True
        )

    def test_admin_bypass(self):
        allowed, reason = self.sec.check_permission("admin_1", "https://danger.com", "fill")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_whitelist_domain_matching_and_actions(self):
        # Allowed action on wildcard subdomain with port and query
        allowed, _ = self.sec.check_permission("user_1", "https://gist.github.com:8443/test?a=1", "read")
        self.assertTrue(allowed)

        # Allowed action on apex domain when rule is *.github.com
        allowed_apex, _ = self.sec.check_permission("user_1", "https://github.com", "read")
        self.assertTrue(allowed_apex)

        # Denied action on allowed domain
        allowed, reason = self.sec.check_permission("user_1", "https://gist.github.com/test", "fill")
        self.assertFalse(allowed)
        self.assertIn("fill", reason)

        # Disallowed domain
        allowed, reason = self.sec.check_permission("user_1", "https://bilibili.com", "read")
        self.assertFalse(allowed)
        self.assertIn("未在白名单", reason)

    def test_navigation_security_non_http(self):
        allowed, reason = self.sec.is_url_allowed_navigation("user_1", "javascript:alert(1)")
        self.assertFalse(allowed)
        self.assertIn("协议", reason)

        allowed_file, reason_file = self.sec.is_url_allowed_navigation("user_1", "file:///etc/passwd")
        self.assertFalse(allowed_file)

    def test_admin_only_mode(self):
        sec_admin_only = SecurityManager(admin_only=True, admin_uids=["admin_1"], whitelist_rules=[])
        allowed, _ = sec_admin_only.check_permission("admin_1", "https://anything.com", "read")
        self.assertTrue(allowed)
        allowed, reason = sec_admin_only.check_permission("user_1", "https://anything.com", "read")
        self.assertFalse(allowed)
        self.assertIn("仅管理员可用", reason)

    def test_whitelist_rules_multi_domains_match(self):
        rules = [
            {
                "domains": ["*.github.com", "github.com", "git-scm.com"],
                "allowed_actions": ["read", "click"]
            }
        ]
        mgr = SecurityManager(admin_only=False, whitelist_rules=rules)
        # 测试导航
        nav_ok, _ = mgr.is_url_allowed_navigation("user1", "https://git-scm.com/docs")
        self.assertTrue(nav_ok)
        nav_fail, _ = mgr.is_url_allowed_navigation("user1", "https://gitlab.com")
        self.assertFalse(nav_fail)

        # 测试列表中不同域名
        ok1, _ = mgr.check_permission("user1", "https://api.github.com/repos", "read")
        self.assertTrue(ok1)
        ok2, _ = mgr.check_permission("user1", "https://github.com/SmileYik", "click")
        self.assertTrue(ok2)
        ok3, _ = mgr.check_permission("user1", "https://git-scm.com/docs", "read")
        self.assertTrue(ok3)
        # 拒绝未在列表的域名与未授权动作
        ok4, _ = mgr.check_permission("user1", "https://gitlab.com", "read")
        self.assertFalse(ok4)
        ok5, _ = mgr.check_permission("user1", "https://github.com", "download")
        self.assertFalse(ok5)

    def test_most_specific_rule_wins_regardless_of_order(self):
        rules = [
            {
                "domains": ["*.example.com"],
                "allowed_actions": ["read"],
                "allow_single_hop": False,
            },
            {
                "domains": ["search.example.com"],
                "allowed_actions": ["read", "click"],
                "allow_single_hop": True,
                "single_hop_allowed_actions": ["read", "screenshot"],
                "single_hop_follow_redirects": True,
            },
        ]
        mgr = SecurityManager(admin_only=False, whitelist_rules=rules)
        ok_click, _ = mgr.check_permission("u1", "https://search.example.com/q", "click")
        self.assertTrue(ok_click)
        hop_ok, hop_actions, follow = mgr.get_single_hop_policy("https://search.example.com/q")
        self.assertTrue(hop_ok)
        self.assertEqual(hop_actions, {"read", "screenshot"})
        self.assertTrue(follow)

        # 其余子域名仍只有通配规则权限
        no_click, _ = mgr.check_permission("u1", "https://docs.example.com/a", "click")
        self.assertFalse(no_click)
        hop_sub, _, _ = mgr.get_single_hop_policy("https://docs.example.com/a")
        self.assertFalse(hop_sub)

        # 深度通配 *.sub.example.com 优先于 *.example.com
        rules_nested = [
            {"domains": ["*.example.com"], "allowed_actions": ["read"]},
            {"domains": ["*.sub.example.com"], "allowed_actions": ["read", "click"]},
        ]
        mgr_nested = SecurityManager(admin_only=False, whitelist_rules=rules_nested)
        ok_nested, _ = mgr_nested.check_permission("u1", "https://a.sub.example.com", "click")
        self.assertTrue(ok_nested)

    def test_legacy_single_domain_field_ignored(self):
        rules = [{"domain": "example.com", "allowed_actions": ["read"]}]
        mgr = SecurityManager(admin_only=False, whitelist_rules=rules)
        ok, _ = mgr.check_permission("user1", "https://example.com", "read")
        self.assertFalse(ok)
        nav_ok, _ = mgr.is_url_allowed_navigation("user1", "https://example.com")
        self.assertFalse(nav_ok)

    def test_get_allowed_actions(self):
        from astrbot_plugin_playwright_tools.core.security_manager import ALL_KNOWN_ACTIONS

        rules = [
            {"domains": ["docs.example.com"], "allowed_actions": ["read", "screenshot"]},
        ]
        mgr = SecurityManager(
            admin_only=False,
            admin_uids=["admin1"],
            admin_bypass=True,
            whitelist_rules=rules,
        )
        self.assertEqual(mgr.get_allowed_actions("u1", "https://docs.example.com/guide"), {"read", "screenshot"})
        self.assertEqual(mgr.get_allowed_actions("u1", "https://other.example.com"), set())
        self.assertEqual(mgr.get_allowed_actions("u1", "file:///etc/passwd"), set())
        self.assertEqual(mgr.get_allowed_actions("admin1", "https://other.example.com"), set(ALL_KNOWN_ACTIONS))

        mgr_admin_only = SecurityManager(admin_only=True, admin_uids=["admin1"], admin_bypass=False)
        self.assertEqual(mgr_admin_only.get_allowed_actions("u1", "https://docs.example.com"), set())
        self.assertEqual(mgr_admin_only.get_allowed_actions("admin1", "https://docs.example.com"), set(ALL_KNOWN_ACTIONS))

if __name__ == "__main__":
    unittest.main()
