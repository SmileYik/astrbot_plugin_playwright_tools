import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.security_manager import SecurityManager

class TestSecurityManager(unittest.TestCase):
    def setUp(self):
        rules = [
            {"domain": "*.github.com", "allowed_actions": ["read", "click", "scroll"]},
            {"domain": "example.com", "allowed_actions": ["read", "click", "fill", "screenshot"]}
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

if __name__ == "__main__":
    unittest.main()
