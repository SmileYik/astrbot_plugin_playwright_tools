import unittest
import os
import sys
from unittest.mock import AsyncMock, MagicMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from astrbot_plugin_playwright_tools.core.context_manager import ContextManager, BrowserSessionContext
from astrbot_plugin_playwright_tools.core.security_manager import SecurityManager

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestContextManager(unittest.IsolatedAsyncioTestCase):
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

    def test_context_manager_lifecycle_logging_on_create_and_close(self):
        mock_audit = MagicMock()
        mock_audit.log_lifecycle = AsyncMock()

        mgr = ContextManager(
            adapter=self.mock_adapter,
            security=self.security,
            mode="personal",
            idle_timeout_minutes=10,
            storage_state_path="state.json",
            audit_logger=mock_audit,
        )

        # 1. create lifecycle event
        ctx, _ = run_coro(mgr.resolve_context(
            session_id="s1", sender_id="user_a",
            session_name="测试群", sender_name="用户张三"
        ))
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.session_name, "测试群")
        self.assertEqual(ctx.owner_name, "用户张三")
        mock_audit.log_lifecycle.assert_called()
        calls = mock_audit.log_lifecycle.call_args_list
        create_call = calls[-1]
        self.assertEqual(create_call.kwargs["session_id"], "s1")
        self.assertEqual(create_call.kwargs["context_key"], "s1:user_a")
        self.assertEqual(create_call.kwargs["owner_id"], "user_a")
        self.assertEqual(create_call.kwargs["event_type"], "create")
        self.assertEqual(create_call.kwargs["operator_id"], "user_a")
        self.assertEqual(create_call.kwargs["session_name"], "测试群")
        self.assertEqual(create_call.kwargs["operator_name"], "用户张三")
        self.assertEqual(create_call.kwargs["owner_name"], "用户张三")
        self.assertEqual(create_call.kwargs["details"], {"mode": "personal"})

        # 2. join lifecycle event (invite)
        mgr.invite_user(session_id="s1", owner_id="user_a", target_user_id="user_b")
        calls = mock_audit.log_lifecycle.call_args_list
        join_call = calls[-1]
        self.assertEqual(join_call.kwargs["event_type"], "join")
        self.assertEqual(join_call.kwargs["operator_id"], "user_a")
        self.assertEqual(join_call.kwargs["details"], {"invited_user": "user_b"})

        # 3. switch lifecycle event
        mgr.switch_user_context(session_id="s1", sender_id="user_b", target_owner_id="user_a")
        calls = mock_audit.log_lifecycle.call_args_list
        switch_call = calls[-1]
        self.assertEqual(switch_call.kwargs["event_type"], "switch")
        self.assertEqual(switch_call.kwargs["operator_id"], "user_b")
        self.assertEqual(switch_call.kwargs["details"], {"target_owner": "user_a"})

        # 4. timeout lifecycle event
        ctx.last_active_time = 0.0
        run_coro(mgr.cleanup_idle_contexts())
        calls = mock_audit.log_lifecycle.call_args_list
        timeout_call = calls[-1]
        self.assertEqual(timeout_call.kwargs["event_type"], "timeout")
        self.assertEqual(timeout_call.kwargs["operator_id"], "system")
        self.assertEqual(timeout_call.kwargs["details"], {"idle_minutes": 10})

        # 5. close lifecycle event
        ctx2, _ = run_coro(mgr.resolve_context(session_id="s1", sender_id="user_c"))
        run_coro(mgr.close_user_context(session_id="s1", sender_id="user_c"))
        calls = mock_audit.log_lifecycle.call_args_list
        close_call = calls[-1]
        self.assertEqual(close_call.kwargs["event_type"], "close")
        self.assertEqual(close_call.kwargs["operator_id"], "user_c")

    def test_context_manager_get_active_contexts_detail(self):
        mock_audit = MagicMock()
        mock_audit.log_lifecycle = AsyncMock()

        mgr = ContextManager(
            adapter=self.mock_adapter,
            security=self.security,
            audit_logger=mock_audit,
        )

        ctx = MagicMock()
        ctx.session_id = "sess_1"
        ctx.owner_id = "user_1"
        ctx.allowed_users = {"user_1", "user_2"}
        ctx.last_active_time = 1700000000.0
        ctx.created_time = 1699999000.0

        page1 = MagicMock(url="https://example.com")
        page1.title = AsyncMock(return_value="Example Domain")
        page2 = MagicMock(url="https://github.com")
        page2.title = AsyncMock(return_value="GitHub")
        ctx.browser_context.pages = [page1, page2]
        ctx.current_page = page1

        mgr.contexts[("sess_1", "user_1")] = ctx

        details = run_coro(mgr.get_active_contexts_detail())
        self.assertEqual(len(details), 1)
        item = details[0]
        self.assertEqual(item["context_key"], "sess_1:user_1")
        self.assertEqual(item["session_id"], "sess_1")
        self.assertEqual(item["owner_id"], "user_1")
        self.assertEqual(set(item["allowed_users"]), {"user_1", "user_2"})
        self.assertEqual(item["created_time"], 1699999000.0)
        self.assertEqual(item["last_active_time"], 1700000000.0)
        self.assertEqual(item["tab_count"], 2)
        self.assertEqual(item["active_tab_url"], "https://example.com")
        self.assertEqual(len(item["tabs"]), 2)
        self.assertEqual(item["tabs"][0]["index"], 0)
        self.assertEqual(item["tabs"][0]["url"], "https://example.com")
        self.assertEqual(item["tabs"][0]["title"], "Example Domain")
        self.assertTrue(item["tabs"][0]["is_active"])
        self.assertEqual(item["tabs"][1]["index"], 1)
        self.assertEqual(item["tabs"][1]["url"], "https://github.com")
        self.assertEqual(item["tabs"][1]["title"], "GitHub")
        self.assertFalse(item["tabs"][1]["is_active"])

    def test_context_manager_force_kill_context(self):
        mock_audit = MagicMock()
        mock_audit.log_lifecycle = AsyncMock()

        mgr = ContextManager(
            adapter=self.mock_adapter,
            security=self.security,
            audit_logger=mock_audit,
        )

        mock_bc = MagicMock()
        mock_bc.close = AsyncMock()
        ctx = MagicMock()
        ctx.session_id = "sess_1"
        ctx.owner_id = "user_1"
        ctx.browser_context = mock_bc

        mgr.contexts[("sess_1", "user_1")] = ctx
        mgr.user_active_pointer[("sess_1", "user_2")] = "user_1"

        ok, msg = run_coro(mgr.force_kill_context("sess_1:user_1", operator_id="admin_user"))
        self.assertTrue(ok)
        self.assertIn("上下文已成功强制关闭", msg)
        self.assertNotIn(("sess_1", "user_1"), mgr.contexts)
        self.assertNotIn(("sess_1", "user_2"), mgr.user_active_pointer)
        mock_bc.close.assert_called_once()

        mock_audit.log_lifecycle.assert_called_once()
        call_kwargs = mock_audit.log_lifecycle.call_args.kwargs
        self.assertEqual(call_kwargs["session_id"], "sess_1")
        self.assertEqual(call_kwargs["context_key"], "sess_1:user_1")
        self.assertEqual(call_kwargs["owner_id"], "user_1")
        self.assertEqual(call_kwargs["event_type"], "force_kill")
        self.assertEqual(call_kwargs["operator_id"], "admin_user")
        self.assertEqual(call_kwargs["details"], {"operator": "admin_user"})

        # Killing non-existent context returns False
        ok_fail, msg_fail = run_coro(mgr.force_kill_context("non_existent", operator_id="admin_user"))
        self.assertFalse(ok_fail)
        self.assertIn("未找到上下文: non_existent", msg_fail)

    def test_allocate_ref_id_monotonic_and_rollover(self):
        ctx = BrowserSessionContext(session_id="s1", owner_id="u1", browser_context=MagicMock(), current_page=MagicMock())
        self.assertEqual(ctx.allocate_ref_id(), "1")
        ctx.next_ref_id = 1_000_000
        self.assertEqual(ctx.allocate_ref_id(), "1000000")
        self.assertEqual(ctx.allocate_ref_id(), "0")

    async def test_create_context_cleans_up_on_failure(self):
        mock_adapter = MagicMock()
        mock_browser_ctx = AsyncMock()
        mock_adapter.create_context = AsyncMock(return_value=mock_browser_ctx)
        mock_browser_ctx.new_page = AsyncMock(side_effect=RuntimeError("New page failed"))
        mgr = ContextManager(adapter=mock_adapter, security=MagicMock())
        with self.assertRaises(RuntimeError):
            await mgr._create_new_context("s1", "u1")
        mock_browser_ctx.close.assert_awaited_once()

    async def test_frame_navigation_invalidates_snapshot_and_ref_map(self):
        mock_adapter = MagicMock()
        mock_browser_ctx = MagicMock()
        mock_page = MagicMock()
        mock_adapter.create_context = AsyncMock(return_value=mock_browser_ctx)
        mock_browser_ctx.new_page = AsyncMock(return_value=mock_page)

        callbacks = {}
        def mock_page_on(event, cb):
            callbacks[event] = cb
        mock_page.on = mock_page_on

        mgr = ContextManager(adapter=mock_adapter, security=MagicMock())
        ctx = await mgr._create_new_context("s1", "u1")

        # verify listener attached
        self.assertIn("framenavigated", callbacks)
        on_frame_nav = callbacks["framenavigated"]

        # set some snapshot and ref_map
        ctx.is_snapshot_dirty = False
        ctx.current_snapshot = "fake_snapshot"
        ctx.ref_map = {"1": {}}

        # subframe navigation should not invalidate
        sub_frame = MagicMock()
        sub_frame.parent_frame = MagicMock()
        on_frame_nav(sub_frame)
        self.assertFalse(ctx.is_snapshot_dirty)
        self.assertEqual(ctx.current_snapshot, "fake_snapshot")
        self.assertEqual(ctx.ref_map, {"1": {}})

        # main frame navigation should invalidate
        main_frame = MagicMock()
        main_frame.parent_frame = None
        on_frame_nav(main_frame)
        self.assertTrue(ctx.is_snapshot_dirty)
        self.assertIsNone(ctx.current_snapshot)
        self.assertEqual(ctx.ref_map, {})

    async def test_popup_page_frame_navigation_listener(self):
        mock_adapter = MagicMock()
        mock_browser_ctx = MagicMock()
        mock_page = MagicMock()
        mock_adapter.create_context = AsyncMock(return_value=mock_browser_ctx)
        mock_browser_ctx.new_page = AsyncMock(return_value=mock_page)

        ctx_callbacks = {}
        mock_browser_ctx.on = lambda evt, cb: ctx_callbacks.update({evt: cb})

        mgr = ContextManager(adapter=mock_adapter, security=MagicMock())
        ctx = await mgr._create_new_context("s1", "u1")

        self.assertIn("page", ctx_callbacks)
        on_page = ctx_callbacks["page"]

        popup_page = MagicMock()
        popup_callbacks = {}
        popup_page.on = lambda evt, cb: popup_callbacks.update({evt: cb})

        on_page(popup_page)
        self.assertIn(popup_page, ctx.pages)
        self.assertEqual(ctx.current_page, popup_page)
        self.assertIn("framenavigated", popup_callbacks)

        # Main frame nav on popup invalidates
        ctx.is_snapshot_dirty = False
        ctx.current_snapshot = "popup_snapshot"
        ctx.ref_map = {"1": {}}

        main_frame = MagicMock()
        main_frame.parent_frame = None
        popup_callbacks["framenavigated"](main_frame)
        self.assertTrue(ctx.is_snapshot_dirty)
        self.assertIsNone(ctx.current_snapshot)
        self.assertEqual(ctx.ref_map, {})

if __name__ == "__main__":
    unittest.main()
