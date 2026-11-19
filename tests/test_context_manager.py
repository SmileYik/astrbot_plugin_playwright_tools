import unittest
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.context_manager import ContextManager
from core.security_manager import SecurityManager

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestContextManager(unittest.TestCase):
    def setUp(self):
        self.mock_adapter = MagicMock()
        self.mock_ctx = MagicMock()
        self.mock_page = MagicMock()

        # setup async methods
        async def mock_new_page():
            return self.mock_page
        async def mock_close():
            return None
        self.mock_ctx.new_page = mock_new_page
        self.mock_ctx.close = mock_close

        async def mock_create_context(storage_state_path=None):
            return self.mock_ctx
        self.mock_adapter.create_context = mock_create_context

        self.security = SecurityManager(admin_only=False, admin_uids=["admin_1"], whitelist_rules=[])
        self.mgr = ContextManager(
            adapter=self.mock_adapter,
            security=self.security,
            mode="personal",
            idle_timeout_minutes=10,
            storage_state_path="state.json"
        )

    def test_personal_mode_isolation_and_invite(self):
        # 1. user_a creates personal context
        ctx_a, hint_a = run_coro(self.mgr.resolve_context(session_id="s1", sender_id="user_a"))
        self.assertIsNotNone(ctx_a)
        self.assertEqual(ctx_a.owner_id, "user_a")
        self.assertEqual(hint_a, "")

        # 2. user_b calls resolve_context (user_b gets own context by default)
        ctx_b, hint_b = run_coro(self.mgr.resolve_context(session_id="s1", sender_id="user_b"))
        self.assertIsNotNone(ctx_b)
        self.assertEqual(ctx_b.owner_id, "user_b")

        # 3. user_a invites user_b to user_a's context
        ok, msg = self.mgr.invite_user(session_id="s1", owner_id="user_a", target_user_id="user_b")
        self.assertTrue(ok)

        # 4. user_b explicitly switches to user_a's context
        switch_ok, _ = self.mgr.switch_user_context(session_id="s1", sender_id="user_b", target_owner_id="user_a")
        self.assertTrue(switch_ok)

        # 5. user_b now resolves to user_a's context with hint
        ctx_switched, hint_switched = run_coro(self.mgr.resolve_context(session_id="s1", sender_id="user_b"))
        self.assertEqual(ctx_switched.owner_id, "user_a")
        self.assertIn("user_a", hint_switched)

    def test_close_user_context(self):
        run_coro(self.mgr.resolve_context(session_id="s1", sender_id="user_a"))
        ok, msg = run_coro(self.mgr.close_user_context(session_id="s1", sender_id="user_a"))
        self.assertTrue(ok)
        self.assertNotIn(("s1", "user_a"), self.mgr.contexts)

    def test_storage_state_admin_only_injection(self):
        # admin_1 context gets storage_state passed to adapter
        called_with = []
        async def mock_admin_create(storage_state_path=None):
            called_with.append(storage_state_path)
            return self.mock_ctx
        self.mock_adapter.create_context = mock_admin_create

        run_coro(self.mgr.resolve_context(session_id="s1", sender_id="admin_1"))
        self.assertEqual(called_with[-1], "state.json")

        # regular user does NOT get storage_state
        run_coro(self.mgr.resolve_context(session_id="s1", sender_id="user_x"))
        self.assertIsNone(called_with[-1])

    def test_peek_does_not_create_context(self):
        ctx, _ = run_coro(self.mgr.resolve_context(session_id="s1", sender_id="peek_user", peek=True))
        self.assertIsNone(ctx)
        self.assertNotIn(("s1", "peek_user"), self.mgr.contexts)

    def test_admin_only_blocks_context_creation_for_non_admin(self):
        admin_sec = SecurityManager(admin_only=True, admin_uids=["admin_1"], whitelist_rules=[])
        mgr_admin = ContextManager(self.mock_adapter, admin_sec, mode="personal")
        ctx, msg = run_coro(mgr_admin.resolve_context(session_id="s1", sender_id="normal_user"))
        self.assertIsNone(ctx)
        self.assertIn("仅管理员可用", msg)
        self.assertNotIn(("s1", "normal_user"), mgr_admin.contexts)

if __name__ == "__main__":
    unittest.main()
