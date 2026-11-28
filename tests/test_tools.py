import unittest
import os
import sys
from unittest.mock import MagicMock, patch

if "astrbot" not in sys.modules:
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from astrbot_plugin_playwright_tools.tools.tools import (
    PwPageTool,
    PwReadTool,
    PwInteractTool,
    PwMediaTool,
    _extract_event_and_metadata,
)
from astrbot_plugin_playwright_tools.tools.schemas import (
    PW_PAGE_SCHEMA,
    PW_READ_SCHEMA,
    PW_INTERACT_SCHEMA,
    PW_MEDIA_SCHEMA,
)
from astrbot_plugin_playwright_tools.tools.handlers.page_handler import PageHandler
from astrbot_plugin_playwright_tools.tools.handlers.interact_handler import InteractHandler
from astrbot_plugin_playwright_tools.tools.handlers.media_handler import MediaHandler


def run_coro(coro):
    result = None
    stack = [coro]
    while stack:
        try:
            val = stack[-1].send(None)
            if hasattr(val, "send"):
                stack.append(val)
        except StopIteration as e:
            stack.pop()
            if stack:
                try:
                    stack[-1].send(e.value)
                except StopIteration as e2:
                    stack.pop()
                    result = e2.value
            else:
                result = e.value
    return result


async def fake_wait_for(fut, timeout):
    return await fut


async def timeout_wait_for(fut, timeout):
    raise TimeoutError()


class TestTools(unittest.TestCase):
    def setUp(self):
        self.mock_page_handler = MagicMock()
        self.mock_interact_handler = MagicMock()
        self.mock_media_handler = MagicMock()

        self.mock_context_wrapper = MagicMock()
        self.mock_context_wrapper.event.session_id = "s1"
        self.mock_context_wrapper.event.get_sender_id.return_value = "u1"

        self.page_tool = PwPageTool(self.mock_page_handler, timeout_seconds=5)
        self.read_tool = PwReadTool(self.mock_page_handler, timeout_seconds=5)
        self.interact_tool = PwInteractTool(self.mock_interact_handler, timeout_seconds=5)
        self.media_tool = PwMediaTool(self.mock_media_handler, timeout_seconds=5)

    def test_page_tool_actions_map_exists(self):
        self.assertTrue(hasattr(self.page_tool, "_actions"))
        for act in ["open", "switch_tab", "list_tabs", "dialog", "close"]:
            self.assertIn(act, self.page_tool._actions)
        self.assertNotIn("read", self.page_tool._actions)
        self.assertNotIn("search", self.page_tool._actions)

    def test_pw_page_schema_actions(self):
        actions = PW_PAGE_SCHEMA["properties"]["action"]["enum"]
        self.assertEqual(actions, ["open", "switch_tab", "list_tabs", "dialog", "close"])
        self.assertNotIn("page", PW_PAGE_SCHEMA["properties"])
        self.assertNotIn("target", PW_PAGE_SCHEMA["properties"])
        self.assertNotIn("keyword", PW_PAGE_SCHEMA["properties"])

    def test_page_tool_call_is_coroutine(self):
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="unknown_action"))
        self.assertIsInstance(res, str)
        self.assertIn("未知的动作", res)

    def test_page_tool_invalid_action(self):
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="unknown_action"))
        self.assertIn("未知的动作: unknown_action。支持的动作包括: open, switch_tab, list_tabs, dialog, close", res)

    def test_page_tool_dispatch_open(self):
        async def mock_open(s_id, u_id, url, **kwargs):
            return f"打开成功: {url}"
        self.mock_page_handler.open_url = mock_open

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="open", url="https://example.com"))
        self.assertEqual(res, "打开成功: https://example.com")

    def test_page_tool_dispatch_list_tabs(self):
        async def mock_list_tabs(s_id, u_id, **kwargs):
            return "当前共 2 个标签页"
        self.mock_page_handler.list_tabs = mock_list_tabs
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="list_tabs"))
        self.assertEqual(res, "当前共 2 个标签页")

    def test_read_tool_dispatch_read(self):
        called_args = {}
        async def mock_read(s_id, u_id, page=1, keyword="", refresh=False, **kwargs):
            called_args["page"] = page
            called_args["keyword"] = keyword
            called_args["refresh"] = refresh
            return f"页面内容第 {page} 页"
        self.mock_page_handler.read_page = mock_read

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.read_tool.call(self.mock_context_wrapper, page=2, refresh=True))
        self.assertEqual(called_args.get("page"), 2)
        self.assertEqual(called_args.get("keyword"), "")
        self.assertTrue(called_args.get("refresh"))
        self.assertEqual(res, "页面内容第 2 页")

    def test_read_tool_dispatch_search(self):
        called_args = {}
        async def mock_read(s_id, u_id, page=1, keyword="", refresh=False, **kwargs):
            called_args["page"] = page
            called_args["keyword"] = keyword
            called_args["refresh"] = refresh
            return f"搜索结果: {keyword}"
        self.mock_page_handler.read_page = mock_read

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.read_tool.call(self.mock_context_wrapper, keyword="测试关键字"))
        self.assertEqual(called_args.get("page"), 1)
        self.assertEqual(called_args.get("keyword"), "测试关键字")
        self.assertFalse(called_args.get("refresh"))
        self.assertEqual(res, "搜索结果: 测试关键字")

    def test_pw_read_schema_has_ref_property(self):
        self.assertIn("ref", PW_READ_SCHEMA["properties"])
        self.assertEqual(PW_READ_SCHEMA["properties"]["ref"]["type"], "string")

    def test_read_tool_dispatch_ref_query(self):
        called_args = {}
        async def mock_read(s_id, u_id, page=1, keyword="", refresh=False, ref="", **kwargs):
            called_args["page"] = page
            called_args["keyword"] = keyword
            called_args["refresh"] = refresh
            called_args["ref"] = ref
            return f"Ref 查询结果: {ref}"
        self.mock_page_handler.read_page = mock_read

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.read_tool.call(self.mock_context_wrapper, ref="12"))
        self.assertEqual(called_args.get("ref"), "12")
        self.assertEqual(res, "Ref 查询结果: 12")

    def test_read_tool_schema(self):
        props = PW_READ_SCHEMA["properties"]
        self.assertIn("page", props)
        self.assertIn("keyword", props)
        self.assertIn("refresh", props)

    def test_page_tool_switch_tab_default_index(self):
        called_args = {}
        async def mock_switch_tab(s_id, u_id, tab_index, **kwargs):
            called_args["tab_index"] = tab_index
            return f"切换至: {tab_index}"
        self.mock_page_handler.switch_tab = mock_switch_tab

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="switch_tab"))
        self.assertEqual(called_args.get("tab_index"), 1)
        self.assertEqual(res, "切换至: 1")

        # Test empty string tab_index gracefully falls back to 1
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="switch_tab", tab_index=""))
        self.assertEqual(called_args.get("tab_index"), 1)

        # Test non-numeric string tab_index gracefully falls back to 1
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="switch_tab", tab_index="invalid"))
        self.assertEqual(called_args.get("tab_index"), 1)

    def test_execute_with_timeout_logs_traceback(self):
        async def mock_fail(*args, **kwargs):
            raise ValueError("测试异常内容")
        self.mock_page_handler.open_url = mock_fail

        with patch("astrbot_plugin_playwright_tools.tools.tools.logger") as mock_logger:
            with patch("asyncio.wait_for", fake_wait_for):
                res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="open", url="https://example.com"))
            self.assertIn("测试异常内容", res)
            self.assertTrue(mock_logger.error.called)
            logged_msg = mock_logger.error.call_args[0][0]
            self.assertIn("ValueError", logged_msg)
            self.assertIn("Traceback", logged_msg)

    def test_page_tool_timeout(self):
        async def mock_open(s_id, u_id, url, **kwargs):
            return "ok"
        self.mock_page_handler.open_url = mock_open

        with patch("asyncio.wait_for", timeout_wait_for):
            res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="open", url="https://example.com"))
        self.assertIn("操作超时", res)
        self.assertIn("5", res)

    def test_interact_tool_actions_map_exists(self):
        self.assertTrue(hasattr(self.interact_tool, "_actions"))
        for act in ["click", "fill", "select", "hover", "focus", "blur", "drag", "press_key", "scroll"]:
            self.assertIn(act, self.interact_tool._actions)

    def test_interact_tool_call_is_coroutine(self):
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.interact_tool.call(self.mock_context_wrapper, action="unknown_action"))
        self.assertIsInstance(res, str)
        self.assertIn("未知的动作", res)

    def test_interact_and_media_schemas_ref_is_string(self):
        interact_props = PW_INTERACT_SCHEMA["properties"]
        self.assertEqual(interact_props["ref"]["type"], "string")
        self.assertIn("e2", interact_props["ref"]["description"])
        self.assertEqual(interact_props["target_ref"]["type"], "string")

        media_props = PW_MEDIA_SCHEMA["properties"]
        self.assertEqual(media_props["ref"]["type"], "string")
        self.assertIn("e2", media_props["ref"]["description"])

    def test_interact_tool_dispatch_click(self):
        called = {}
        async def mock_click(s_id, u_id, ref, **kwargs):
            called["ref"] = ref
            return f"点击元素成功: {ref}"
        self.mock_interact_handler.click = mock_click

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.interact_tool.call(self.mock_context_wrapper, action="click", ref="e2"))
        self.assertEqual(called.get("ref"), "e2")
        self.assertEqual(res, "点击元素成功: e2")

    def test_interact_tool_dispatch_drag_string_refs(self):
        called = {}
        async def mock_drag(s_id, u_id, ref, target_ref, **kwargs):
            called["ref"] = ref
            called["target_ref"] = target_ref
            return f"拖拽成功: {ref} -> {target_ref}"
        self.mock_interact_handler.drag = mock_drag

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.interact_tool.call(self.mock_context_wrapper, action="drag", ref="e1", target_ref="e2"))
        self.assertEqual(called.get("ref"), "e1")
        self.assertEqual(called.get("target_ref"), "e2")
        self.assertEqual(res, "拖拽成功: e1 -> e2")

    def test_interact_tool_dispatch_actions_pass_string_ref(self):
        # Test fill, select, hover, focus, blur all pass string ref
        called = {}
        async def mock_fill(s_id, u_id, ref, text, **kwargs):
            called["fill"] = (ref, text)
            return "ok"
        async def mock_select(s_id, u_id, ref, value, **kwargs):
            called["select"] = (ref, value)
            return "ok"
        async def mock_hover(s_id, u_id, ref, **kwargs):
            called["hover"] = ref
            return "ok"
        async def mock_focus(s_id, u_id, ref, **kwargs):
            called["focus"] = ref
            return "ok"
        async def mock_blur(s_id, u_id, ref, **kwargs):
            called["blur"] = ref
            return "ok"

        self.mock_interact_handler.fill_form = mock_fill
        self.mock_interact_handler.select_option = mock_select
        self.mock_interact_handler.hover = mock_hover
        self.mock_interact_handler.focus = mock_focus
        self.mock_interact_handler.blur = mock_blur

        with patch("asyncio.wait_for", fake_wait_for):
            run_coro(self.interact_tool.call(self.mock_context_wrapper, action="fill", ref="e3", text="abc"))
            run_coro(self.interact_tool.call(self.mock_context_wrapper, action="select", ref="e4", value="v1"))
            run_coro(self.interact_tool.call(self.mock_context_wrapper, action="hover", ref="e5"))
            run_coro(self.interact_tool.call(self.mock_context_wrapper, action="focus", ref="e6"))
            run_coro(self.interact_tool.call(self.mock_context_wrapper, action="blur", ref="e7"))

        self.assertEqual(called["fill"], ("e3", "abc"))
        self.assertEqual(called["select"], ("e4", "v1"))
        self.assertEqual(called["hover"], "e5")
        self.assertEqual(called["focus"], "e6")
        self.assertEqual(called["blur"], "e7")

    def test_interact_tool_missing_ref(self):
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.interact_tool.call(self.mock_context_wrapper, action="click"))
        self.assertIn("参数错误", res)

    def test_media_tool_actions_map_exists(self):
        self.assertTrue(hasattr(self.media_tool, "_actions"))
        for act in ["screenshot_viewport", "screenshot_full", "download"]:
            self.assertIn(act, self.media_tool._actions)

    def test_media_tool_call_is_coroutine(self):
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="unknown_action"))
        self.assertIsInstance(res, str)
        self.assertIn("未知的动作", res)

    def test_media_tool_chat_sends_image_and_returns_text(self):
        async def mock_send(msg):
            return None
        self.mock_context_wrapper.event.send = mock_send

        async def mock_vp(s_id, u_id, target, **kwargs):
            return "[IMAGE_PATH:/tmp/vp.png]\n视口截图已截取"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="chat"))
        self.assertIn("[IMAGE_PATH:/tmp/vp.png]", res)
        self.assertIn("视口截图已截取", res)

    def test_media_tool_chat_full_screenshot_sends_image_and_returns_text(self):
        async def mock_send(msg):
            return None
        self.mock_context_wrapper.event.send = mock_send

        async def mock_full(s_id, u_id, target, max_height_px, timeout_sec, **kwargs):
            return "[IMAGE_PATH:/tmp/full.png]\n长截图完成"
        self.mock_media_handler.screenshot_full = mock_full

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="screenshot_full", target="chat"))
        self.assertIn("[IMAGE_PATH:/tmp/full.png]", res)

    def test_media_tool_ai_target_returns_call_tool_result(self):
        from astrbot_plugin_playwright_tools.tools.handlers.base_handler import (
            build_image_tool_result,
        )

        expected = build_image_tool_result("screenshot ready", b"abc123", "image/png")

        async def mock_vp(s_id, u_id, target, **kwargs):
            return expected
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="ai"))
        self.assertIs(res, expected)
        self.assertFalse(self.mock_context_wrapper.event.send.called)

    def test_media_tool_chat_failure_returns_error_text(self):
        async def mock_vp(s_id, u_id, target, **kwargs):
            return "截图失败: 权限不足"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="chat"))
        self.assertEqual(res, "截图失败: 权限不足")

    def test_media_tool_download_dispatch(self):
        called = {}
        async def mock_dl(s_id, u_id, ref, **kwargs):
            called["ref"] = ref
            return f"[FILE_PATH:/tmp/down.pdf]\n下载成功: {ref}"
        self.mock_media_handler.download_file = mock_dl

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="download", ref="e1"))
        self.assertEqual(called.get("ref"), "e1")
        self.assertEqual(res, "[FILE_PATH:/tmp/down.pdf]\n下载成功: e1")

    def test_tool_handler_attribute_is_none(self):
        self.assertIsNone(self.page_tool.handler)
        self.assertIsNone(self.read_tool.handler)
        self.assertIsNone(self.interact_tool.handler)
        self.assertIsNone(self.media_tool.handler)

    def test_read_tool_dynamic_description(self):
        mock_handler = MagicMock()
        mock_handler.reader.get_tool_metadata.return_value = {
            "description": "自定义读取器描述内容"
        }
        tool = PwReadTool(mock_handler, timeout_seconds=10)
        self.assertEqual(tool.description, "自定义读取器描述内容")

    def test_context_wrapper_unwrapping(self):
        nested_wrapper = MagicMock(spec=["context"])
        agent_context = MagicMock()
        agent_context.event.session_id = "nested_s1"
        agent_context.event.get_sender_id.return_value = "nested_u1"
        nested_wrapper.context = agent_context

        captured = {}
        async def mock_open(s_id, u_id, url, **kwargs):
            captured["session_id"] = s_id
            captured["sender_id"] = u_id
            return "ok"
        self.mock_page_handler.open_url = mock_open

        with patch("asyncio.wait_for", fake_wait_for):
            run_coro(self.page_tool.call(nested_wrapper, action="open", url="https://example.com"))

        self.assertEqual(captured.get("session_id"), "nested_s1")
        self.assertEqual(captured.get("sender_id"), "nested_u1")

    def test_media_tool_chat_fallback_when_event_send_raises(self):
        async def mock_send(msg):
            raise RuntimeError("send error")
        self.mock_context_wrapper.event.send = mock_send

        async def mock_vp(s_id, u_id, target, **kwargs):
            return "[IMAGE_PATH:/tmp/err.png]"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="chat"))
        self.assertEqual(res, "[IMAGE_PATH:/tmp/err.png]")

    def test_extract_event_and_metadata_group_chat(self):
        ctx = MagicMock()
        event = MagicMock()
        event.session_id = "s_group_1"
        event.get_sender_id.return_value = "u_100"
        event.get_sender_name.return_value = "测试昵称"
        event.message_obj.group.group_name = "开发交流群"
        ctx.event = event

        ev, s_id, u_id, session_name, sender_name = _extract_event_and_metadata(ctx)
        self.assertEqual(s_id, "s_group_1")
        self.assertEqual(u_id, "u_100")
        self.assertEqual(session_name, "开发交流群")
        self.assertEqual(sender_name, "测试昵称")

    def test_extract_event_and_metadata_private_chat(self):
        ctx = MagicMock()
        event = MagicMock()
        event.session_id = "s_priv_1"
        event.get_sender_id.return_value = "u_200"
        event.get_sender_name.return_value = "Bob"
        event.message_obj.group = None
        ctx.event = event

        ev, s_id, u_id, session_name, sender_name = _extract_event_and_metadata(ctx)
        self.assertEqual(session_name, "私聊: Bob")
        self.assertEqual(sender_name, "Bob")

    def test_extract_event_and_metadata_fallback(self):
        ctx = MagicMock(spec=["event"])
        event = MagicMock(spec=["session_id", "get_sender_id"])
        event.session_id = "s_raw"
        event.get_sender_id.return_value = "u_raw"
        ctx.event = event

        ev, s_id, u_id, session_name, sender_name = _extract_event_and_metadata(ctx)
        self.assertEqual(session_name, "s_raw")
        self.assertEqual(sender_name, "u_raw")

    def test_tool_chain_forwards_metadata_to_handlers(self):
        ctx = MagicMock()
        event = MagicMock()
        event.session_id = "s_chain"
        event.get_sender_id.return_value = "u_chain"
        event.get_sender_name.return_value = "ChainUser"
        event.message_obj.group.group_name = "ChainGroup"
        ctx.event = event

        captured = {}
        async def mock_open(s_id, u_id, session_name="", sender_name="", **kwargs):
            captured["page"] = (s_id, u_id, session_name, sender_name)
            return "ok"
        self.mock_page_handler.open_url = mock_open

        with patch("asyncio.wait_for", fake_wait_for):
            run_coro(self.page_tool.call(ctx, action="open", url="https://example.com"))

        self.assertEqual(captured["page"], ("s_chain", "u_chain", "ChainGroup", "ChainUser"))

    def test_handlers_forward_metadata_to_audit_logger(self):
        mock_ctx_mgr = MagicMock()
        mock_sec_mgr = MagicMock()
        mock_audit = MagicMock()
        async def mock_log(*args, **kwargs):
            return None
        mock_audit.log_action = mock_log
        mock_extractor = MagicMock()

        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_user_ctx = MagicMock()
        mock_user_ctx.owner_id = "u_audit"
        mock_user_ctx.current_page = mock_page
        mock_ctx_mgr.resolve_context.return_value = (mock_user_ctx, "")

        mock_sec_mgr.is_url_allowed_navigation.return_value = (False, "黑名单域名")
        mock_sec_mgr.check_permission.return_value = (False, "权限不足")

        logged_kwargs = {}
        async def capture_log(*args, **kwargs):
            logged_kwargs.update(kwargs)
            return None
        mock_audit.log_action = capture_log

        handler = PageHandler(mock_ctx_mgr, mock_sec_mgr, mock_audit, mock_extractor)
        run_coro(handler.open_url(
            session_id="s_test", sender_id="u_test", url="https://blocked.com",
            session_name="测试群", sender_name="测试者"
        ))

        self.assertEqual(logged_kwargs.get("session_name"), "测试群")
        self.assertEqual(logged_kwargs.get("sender_name"), "测试者")

    def test_base_handler_single_hop_fallback_allows_read_but_not_open_url(self):
        from unittest.mock import AsyncMock
        from astrbot_plugin_playwright_tools.core.navigation_guard import NavigationGuard, SingleHopGrant
        from astrbot_plugin_playwright_tools.core.security_manager import SecurityManager
        from astrbot_plugin_playwright_tools.tools.handlers.base_handler import BaseActionHandler

        sec = SecurityManager(admin_only=False, whitelist_rules=[
            {"domains": ["search.example.com"], "allowed_actions": ["read", "click"], "allow_single_hop": True}
        ])
        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.mode = "personal"
        mock_audit = MagicMock()
        mock_audit.log_action = AsyncMock()

        mock_page = MagicMock()
        mock_page.url = "https://target.com/post"
        nav_guard = NavigationGuard(security=sec, get_user_id=lambda: "u1")
        nav_guard._page_grants[id(mock_page)] = SingleHopGrant(
            allowed_actions={"read"},
            follow_redirects=True,
            granted_url="https://target.com/post",
        )

        mock_user_ctx = MagicMock()
        mock_user_ctx.owner_id = "u1"
        mock_user_ctx.allowed_users = {"u1"}
        mock_user_ctx.current_page = mock_page
        mock_user_ctx.navigation_guard = nav_guard
        mock_ctx_mgr.resolve_context = AsyncMock(return_value=(mock_user_ctx, ""))

        handler = BaseActionHandler(mock_ctx_mgr, sec, mock_audit, mask_password_inputs=True)
        handler.wait_page_stable = AsyncMock()

        # read on single-hopped page -> allowed
        res_read = run_coro(handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="read_page",
            target_resource="",
            action_coro_fn=lambda ctx, page: "read_ok",
            required_permission="read",
        ))
        self.assertIn("read_ok", res_read)

        # click on single-hopped page -> denied
        res_click = run_coro(handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="click",
            target_resource="",
            action_coro_fn=lambda ctx, page: "click_ok",
            required_permission="click",
            action_desc="点击",
        ))
        self.assertIn("点击失败", res_click)

        # open_url to non-whitelisted URL -> still denied
        res_open = run_coro(handler.execute_action(
            session_id="s1",
            sender_id="u1",
            action_name="open_url",
            target_resource="https://target.com/post",
            action_coro_fn=lambda ctx, page: "open_ok",
            required_permission="navigate",
            action_desc="打开",
        ))
        self.assertIn("打开失败", res_open)

    def test_read_tool_omits_empty_ref_arg(self):
        called_kwargs = {}
        async def mock_read(s_id, u_id, **kwargs):
            called_kwargs.update(kwargs)
            return "ok"
        self.mock_page_handler.read_page = mock_read

        # 1. 不传 ref
        with patch("asyncio.wait_for", fake_wait_for):
            run_coro(self.read_tool.call(self.mock_context_wrapper, page=1))
        self.assertNotIn("ref", called_kwargs)

        # 2. 传空字符串 ref
        called_kwargs.clear()
        with patch("asyncio.wait_for", fake_wait_for):
            run_coro(self.read_tool.call(self.mock_context_wrapper, page=1, ref="   "))
        self.assertNotIn("ref", called_kwargs)

        # 3. 传有效 ref
        called_kwargs.clear()
        with patch("asyncio.wait_for", fake_wait_for):
            run_coro(self.read_tool.call(self.mock_context_wrapper, page=1, ref="e5"))
        self.assertEqual(called_kwargs.get("ref"), "e5")

    def test_tool_triggers_history_cleaner_before_execution(self):
        from unittest.mock import AsyncMock
        mock_cleaner = MagicMock()
        mock_cleaner.process_contexts = AsyncMock(return_value=True)

        async def mock_open(s_id, u_id, url, **kwargs):
            return "ok"
        self.mock_page_handler.open_url = mock_open

        tool = PwPageTool(self.mock_page_handler, timeout_seconds=5, history_cleaner=mock_cleaner)
        context = MagicMock()
        context.messages = [{"role": "user", "content": "test"}]
        context.event.session_id = "s1"
        context.event.get_sender_id.return_value = "u1"

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(tool.call(context, action="open", url="https://example.com"))
        self.assertEqual(res, "ok")
        mock_cleaner.process_contexts.assert_awaited_once_with(context.event, context.messages)

    def test_all_tools_trigger_history_cleaner(self):
        from unittest.mock import AsyncMock
        mock_cleaner = MagicMock()
        mock_cleaner.process_contexts = AsyncMock(return_value=True)

        self.mock_page_handler.read_page = MagicMock(return_value="read_ok")
        async def mock_read(*args, **kwargs):
            return "read_ok"
        self.mock_page_handler.read_page = mock_read

        async def mock_click(*args, **kwargs):
            return "click_ok"
        self.mock_interact_handler.click = mock_click

        async def mock_ss(*args, **kwargs):
            return "ss_ok"
        self.mock_media_handler.screenshot_viewport = mock_ss

        context = MagicMock()
        context.messages = [{"role": "user", "content": "subagent msg"}]
        context.event.session_id = "s1"
        context.event.get_sender_id.return_value = "u1"

        r_tool = PwReadTool(self.mock_page_handler, timeout_seconds=5, history_cleaner=mock_cleaner)
        i_tool = PwInteractTool(self.mock_interact_handler, timeout_seconds=5, history_cleaner=mock_cleaner)
        m_tool = PwMediaTool(self.mock_media_handler, timeout_seconds=5, history_cleaner=mock_cleaner)

        with patch("asyncio.wait_for", fake_wait_for):
            run_coro(r_tool.call(context, page=1))
            run_coro(i_tool.call(context, action="click", ref="1"))
            run_coro(m_tool.call(context, action="screenshot_viewport"))

        self.assertEqual(mock_cleaner.process_contexts.await_count, 3)

    def test_tool_history_cleaner_exception_isolated(self):
        from unittest.mock import AsyncMock
        mock_cleaner = MagicMock()
        mock_cleaner.process_contexts = AsyncMock(side_effect=RuntimeError("Cleaner failure"))

        async def mock_close(*args, **kwargs):
            return "closed"
        self.mock_page_handler.close_browser = mock_close

        tool = PwPageTool(self.mock_page_handler, timeout_seconds=5, history_cleaner=mock_cleaner)
        context = MagicMock()
        context.messages = [{"role": "user", "content": "test"}]
        context.event.session_id = "s1"
        context.event.get_sender_id.return_value = "u1"

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(tool.call(context, action="close"))
        self.assertEqual(res, "closed")


if __name__ == "__main__":
    unittest.main()
