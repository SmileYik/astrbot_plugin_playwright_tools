import unittest
import os
import sys
import asyncio
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.tools import PwPageTool, PwInteractTool, PwMediaTool, _extract_event_and_metadata
from tools.handlers.page_handler import PageHandler
from tools.handlers.interact_handler import InteractHandler
from tools.handlers.media_handler import MediaHandler

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

def run_gen(gen):
    async def _drain():
        items = []
        async for item in gen:
            items.append(item)
        return items
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_drain())
    finally:
        loop.close()

async def fake_wait_for(fut, timeout):
    return await fut

async def timeout_wait_for(fut, timeout):
    raise asyncio.TimeoutError()

class TestToolsV2(unittest.TestCase):
    def setUp(self):
        self.mock_page_handler = MagicMock()
        self.mock_interact_handler = MagicMock()
        self.mock_media_handler = MagicMock()

        self.mock_context_wrapper = MagicMock()
        self.mock_context_wrapper.event.session_id = "s1"
        self.mock_context_wrapper.event.get_sender_id.return_value = "u1"

        self.page_tool = PwPageTool(self.mock_page_handler, timeout_seconds=5)
        self.interact_tool = PwInteractTool(self.mock_interact_handler, timeout_seconds=5)
        self.media_tool = PwMediaTool(self.mock_media_handler, timeout_seconds=5)

    def test_page_tool_actions_map_exists(self):
        self.assertTrue(hasattr(self.page_tool, "_actions"))
        for act in ["open", "read", "search", "switch_tab", "dialog", "close"]:
            self.assertIn(act, self.page_tool._actions)

    def test_page_tool_call_is_async_generator(self):
        gen = self.page_tool.call(self.mock_context_wrapper, action="unknown_action")
        self.assertTrue(hasattr(gen, "__aiter__"))
        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(gen)
        self.assertEqual(len(items), 1)
        self.assertIn("未知的动作", items[0])

    def test_page_tool_invalid_action(self):
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_gen(self.page_tool.call(self.mock_context_wrapper, action="unknown_action"))[0]
        self.assertIn("未知的动作", res)

    def test_page_tool_dispatch_open(self):
        async def mock_open(s_id, u_id, url):
            return f"打开成功: {url}"
        self.mock_page_handler.open_url = mock_open

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_gen(self.page_tool.call(self.mock_context_wrapper, action="open", url="https://example.com"))[0]
        self.assertEqual(res, "打开成功: https://example.com")

    def test_page_tool_dispatch_search(self):
        async def mock_search(s_id, u_id, keyword):
            return f"搜索结果: {keyword}"
        self.mock_page_handler.search_page = mock_search

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_gen(self.page_tool.call(self.mock_context_wrapper, action="search", keyword="关键词"))[0]
        self.assertEqual(res, "搜索结果: 关键词")

    def test_page_tool_timeout(self):
        async def mock_open(s_id, u_id, url):
            return "ok"
        self.mock_page_handler.open_url = mock_open

        with patch("asyncio.wait_for", timeout_wait_for):
            res = run_gen(self.page_tool.call(self.mock_context_wrapper, action="open", url="https://example.com"))[0]
        self.assertIn("操作超时", res)
        self.assertIn("5", res)

    def test_interact_tool_actions_map_exists(self):
        self.assertTrue(hasattr(self.interact_tool, "_actions"))
        for act in ["click", "fill", "select", "hover", "focus", "blur", "drag", "press_key", "scroll"]:
            self.assertIn(act, self.interact_tool._actions)

    def test_interact_tool_call_is_async_generator(self):
        gen = self.interact_tool.call(self.mock_context_wrapper, action="unknown_action")
        self.assertTrue(hasattr(gen, "__aiter__"))
        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(gen)
        self.assertEqual(len(items), 1)
        self.assertIn("未知的动作", items[0])

    def test_interact_tool_dispatch_click(self):
        async def mock_click(s_id, u_id, ref):
            return f"点击元素成功: {ref}"
        self.mock_interact_handler.click = mock_click

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_gen(self.interact_tool.call(self.mock_context_wrapper, action="click", ref=3))[0]
        self.assertEqual(res, "点击元素成功: 3")

    def test_interact_tool_missing_ref(self):
        with patch("asyncio.wait_for", fake_wait_for):
            res = run_gen(self.interact_tool.call(self.mock_context_wrapper, action="click"))[0]
        self.assertIn("参数错误", res)

    def test_media_tool_actions_map_exists(self):
        self.assertTrue(hasattr(self.media_tool, "_actions"))
        for act in ["screenshot_viewport", "screenshot_full", "download"]:
            self.assertIn(act, self.media_tool._actions)

    def test_media_tool_call_is_async_generator(self):
        gen = self.media_tool.call(self.mock_context_wrapper, action="unknown_action")
        self.assertTrue(hasattr(gen, "__aiter__"))
        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(gen)
        self.assertEqual(len(items), 1)
        self.assertIn("未知的动作", items[0])

    def test_media_tool_chat_yields_image_result_and_stops(self):
        self.mock_context_wrapper.event.image_result = MagicMock(return_value="MOCK_IMAGE_CHAIN")
        async def mock_vp(s_id, u_id, target):
            return "[IMAGE_PATH:/tmp/vp.png]\n视口截图已截取"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="chat"))
        self.assertEqual(items, ["MOCK_IMAGE_CHAIN"])
        self.assertEqual(len(items), 1)
        self.mock_context_wrapper.event.image_result.assert_called_once_with("/tmp/vp.png")

    def test_media_tool_chat_full_screenshot_yields_image_result_and_stops(self):
        self.mock_context_wrapper.event.image_result = MagicMock(return_value="MOCK_FULL_IMAGE_CHAIN")
        async def mock_full(s_id, u_id, target, max_height_px, timeout_sec):
            return "[IMAGE_PATH:/tmp/full.png]"
        self.mock_media_handler.screenshot_full = mock_full

        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(self.media_tool.call(self.mock_context_wrapper, action="screenshot_full", target="chat"))
        self.assertEqual(items, ["MOCK_FULL_IMAGE_CHAIN"])
        self.assertEqual(len(items), 1)
        self.mock_context_wrapper.event.image_result.assert_called_once_with("/tmp/full.png")

    def test_media_tool_ai_target_yields_text(self):
        async def mock_vp(s_id, u_id, target):
            return "data:image/png;base64,abc123xyz"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="ai"))
        self.assertEqual(items, ["data:image/png;base64,abc123xyz"])

    def test_media_tool_chat_failure_yields_error_text(self):
        async def mock_vp(s_id, u_id, target):
            return "截图失败: 权限不足"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="chat"))
        self.assertEqual(items, ["截图失败: 权限不足"])

    def test_media_tool_download_dispatch(self):
        async def mock_dl(s_id, u_id, ref):
            return "[FILE_PATH:/tmp/down.pdf]\n下载成功"
        self.mock_media_handler.download_file = mock_dl

        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(self.media_tool.call(self.mock_context_wrapper, action="download", ref=1))
        self.assertEqual(items, ["[FILE_PATH:/tmp/down.pdf]\n下载成功"])

    def test_tool_handler_attribute_is_none(self):
        self.assertIsNone(self.page_tool.handler)
        self.assertIsNone(self.interact_tool.handler)
        self.assertIsNone(self.media_tool.handler)

    def test_context_wrapper_unwrapping(self):
        # Nested ContextWrapper: wrapper.context.event
        nested_wrapper = MagicMock(spec=["context"])
        agent_context = MagicMock()
        agent_context.event.session_id = "nested_s1"
        agent_context.event.get_sender_id.return_value = "nested_u1"
        nested_wrapper.context = agent_context

        captured = {}
        async def mock_open(s_id, u_id, url):
            captured["session_id"] = s_id
            captured["sender_id"] = u_id
            return "ok"
        self.mock_page_handler.open_url = mock_open

        with patch("asyncio.wait_for", fake_wait_for):
            run_gen(self.page_tool.call(nested_wrapper, action="open", url="https://example.com"))

        self.assertEqual(captured.get("session_id"), "nested_s1")
        self.assertEqual(captured.get("sender_id"), "nested_u1")

    def test_media_tool_chat_fallback_when_image_result_raises(self):
        self.mock_context_wrapper.event.image_result = MagicMock(side_effect=RuntimeError("image build error"))
        async def mock_vp(s_id, u_id, target):
            return "[IMAGE_PATH:/tmp/err.png]"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="chat"))
        self.assertEqual(items, ["[IMAGE_PATH:/tmp/err.png]"])

    def test_media_tool_chat_fallback_when_no_image_result(self):
        ctx_without_img_res = MagicMock(spec=["event"])
        ctx_without_img_res.event = MagicMock(spec=["session_id", "get_sender_id"])
        ctx_without_img_res.event.session_id = "s1"
        ctx_without_img_res.event.get_sender_id.return_value = "u1"

        async def mock_vp(s_id, u_id, target):
            return "[IMAGE_PATH:/tmp/test.png]"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            items = run_gen(self.media_tool.call(ctx_without_img_res, action="screenshot_viewport", target="chat"))
        self.assertEqual(items, ["[IMAGE_PATH:/tmp/test.png]"])

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
            run_gen(self.page_tool.call(ctx, action="open", url="https://example.com"))

        self.assertEqual(captured["page"], ("s_chain", "u_chain", "ChainGroup", "ChainUser"))

    def test_handlers_forward_metadata_to_audit_logger(self):
        mock_ctx_mgr = MagicMock()
        mock_sec_mgr = MagicMock()
        mock_audit = MagicMock()
        mock_audit.log_action = unittest.mock.AsyncMock()
        mock_extractor = MagicMock()

        # 模拟上下文与页面
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_user_ctx = MagicMock()
        mock_user_ctx.owner_id = "u_audit"
        mock_user_ctx.current_page = mock_page
        mock_ctx_mgr.resolve_context.return_value = (mock_user_ctx, "")

        mock_sec_mgr.is_url_allowed_navigation.return_value = (False, "黑名单域名")
        mock_sec_mgr.check_permission.return_value = (False, "权限不足")

        handler = PageHandler(mock_ctx_mgr, mock_sec_mgr, mock_audit, mock_extractor)
        run_coro(handler.open_url(
            session_id="s_test", sender_id="u_test", url="https://blocked.com",
            session_name="测试群", sender_name="测试者"
        ))

        mock_audit.log_action.assert_called_once()
        _, kwargs = mock_audit.log_action.call_args
        self.assertEqual(kwargs.get("session_name"), "测试群")
        self.assertEqual(kwargs.get("sender_name"), "测试者")

if __name__ == "__main__":
    unittest.main()
