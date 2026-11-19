import unittest
import os
import sys
import asyncio
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.tools import PwPageTool, PwInteractTool, PwMediaTool

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

    def test_media_tool_dispatch_viewport(self):
        async def mock_vp(s_id, u_id, target):
            return f"[IMAGE_PATH:vp.png]"
        self.mock_media_handler.screenshot_viewport = mock_vp

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="screenshot_viewport", target="chat"))
        self.assertEqual(res, "[IMAGE_PATH:vp.png]")

    def test_media_tool_dispatch_full(self):
        async def mock_full(s_id, u_id, target, max_height_px, timeout_sec):
            return f"[IMAGE_PATH:full.png]"
        self.mock_media_handler.screenshot_full = mock_full

        with patch("asyncio.wait_for", fake_wait_for):
            res = run_coro(self.media_tool.call(self.mock_context_wrapper, action="screenshot_full", target="chat"))
        self.assertEqual(res, "[IMAGE_PATH:full.png]")

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

    def test_media_tool_chat_delivery_with_send(self):
        sent_messages = []
        async def mock_send(chain):
            sent_messages.append(chain)

        ctx_with_send = MagicMock(spec=["event"])
        ctx_with_send.event = MagicMock()
        ctx_with_send.event.session_id = "s1"
        ctx_with_send.event.get_sender_id.return_value = "u1"
        ctx_with_send.event.send = mock_send

        async def mock_vp(s_id, u_id, target):
            return "[IMAGE_PATH:test.png]"
        self.mock_media_handler.screenshot_viewport = mock_vp

        # mock astrbot.api.message_components
        with patch.dict("sys.modules", {
            "astrbot.api.message_components": MagicMock(),
            "astrbot.api.event": MagicMock(),
        }):
            with patch("asyncio.wait_for", fake_wait_for):
                res = run_coro(self.media_tool.call(ctx_with_send, action="screenshot_viewport", target="chat"))
        self.assertIn("发送至聊天", res)
        self.assertEqual(len(sent_messages), 1)

if __name__ == "__main__":
    unittest.main()
