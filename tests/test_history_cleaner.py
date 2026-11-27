import unittest
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Ensure parent directory is in sys.path
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from astrbot.core.agent.message import Message, ToolCall
except ImportError:
    class ToolCall:
        def __init__(self, id, name, args="{}"):
            self.id = id
            self.type = "function"
            self.function = MagicMock()
            self.function.name = name
            self.function.arguments = args

    class Message:
        def __init__(self, role, content=None, tool_calls=None, tool_call_id=None):
            self.role = role
            self.content = content
            self.tool_calls = tool_calls
            self.tool_call_id = tool_call_id


class TestHistoryCleaner(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = MagicMock()
        self.config = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 2000,
                "cleanup_strategy": "delete",
                "compress_max_input_chars": 0,
            }
        }

    def test_tool_recognition(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        self.assertTrue(cleaner.is_plugin_tool("pw_page"))
        self.assertTrue(cleaner.is_plugin_tool("pw_read"))
        self.assertTrue(cleaner.is_plugin_tool("pw_interact"))
        self.assertTrue(cleaner.is_plugin_tool("pw_media"))
        self.assertFalse(cleaner.is_plugin_tool("calculator"))
        self.assertFalse(cleaner.is_plugin_tool("search"))

    def test_is_processed_tool(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        self.assertTrue(cleaner.is_processed_tool("[该历史工具调用结果已按策略清理]"))
        self.assertTrue(cleaner.is_processed_tool("[已并入本轮浏览摘要]"))
        self.assertTrue(cleaner.is_processed_tool("[历史浏览摘要]:\n这是一段摘要"))
        self.assertFalse(cleaner.is_processed_tool("Normal page markdown content"))

    def test_calculate_uncompressed_chars_dict(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        contexts = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                    {"id": "call_2", "type": "function", "function": {"name": "other_tool", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "pw_read", "content": "A" * 3000},
            {"role": "tool", "tool_call_id": "call_2", "name": "other_tool", "content": "B" * 5000},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_3", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_3", "name": "pw_page", "content": "[该历史工具调用结果已按策略清理]"},
        ]

        total = cleaner.calculate_uncompressed_chars(contexts)
        self.assertEqual(total, 3000)

    def test_group_tool_calls(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        contexts = [
            {"role": "user", "content": "step 1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "opened"},
            {"role": "tool", "tool_call_id": "c2", "content": "read page 1"},
            {"role": "assistant", "content": "Found something"},
            {"role": "user", "content": "step 2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c3", "type": "function", "function": {"name": "pw_interact", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c3", "content": "clicked button"},
            {"role": "assistant", "content": "Done clicking"},
        ]

        groups = cleaner.group_tool_calls(contexts)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], [2, 3])  # c1, c2 indices
        self.assertEqual(groups[1], [7])     # c3 index

    async def test_process_contexts_delete_watermark(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        # Total uncompressed: 3000 (group 1) + 3000 (group 2) = 6000 > high_watermark (5000)
        # Low watermark is 2000.
        # FIFO deletes group 1 (reduces by 3000 -> remains 3000 > 2000), then deletes group 2 (remains 0 <= 2000).
        contexts = [
            {"role": "user", "content": "query 1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "1" * 3000},
            {"role": "assistant", "content": "answer 1"},
            {"role": "user", "content": "query 2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c2", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c2", "content": "2" * 3000},
            {"role": "assistant", "content": "answer 2"},
        ]

        req = MagicMock()
        req.contexts = contexts
        event = MagicMock()

        changed = await cleaner.process_contexts(event, req)
        self.assertTrue(changed)
        self.assertEqual(contexts[2]["content"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(contexts[6]["content"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(cleaner.calculate_uncompressed_chars(contexts), 0)

    async def test_process_contexts_delete_partial_drainage(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        # high: 5000, low: 3000.
        # Group 1: 4000. Group 2: 2500. Total = 6500 > 5000.
        # Deleting Group 1 drops total to 2500 <= 3000 (low watermark). Group 2 MUST remain untouched!
        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 3000,
                "cleanup_strategy": "delete",
            }
        }
        cleaner = HistoryCleaner(self.context, cfg)

        contexts = [
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "A" * 4000},
            {"role": "assistant", "content": "ans 1"},
            {"role": "user", "content": "q2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c2", "content": "B" * 2500},
            {"role": "assistant", "content": "ans 2"},
        ]

        req = MagicMock()
        req.contexts = contexts
        event = MagicMock()

        changed = await cleaner.process_contexts(event, req)
        self.assertTrue(changed)
        self.assertEqual(contexts[2]["content"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(contexts[6]["content"], "B" * 2500)
        self.assertEqual(cleaner.calculate_uncompressed_chars(contexts), 2500)

    async def test_process_contexts_below_watermark_no_change(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        contexts = [
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "A" * 2000},
            {"role": "assistant", "content": "ans 1"},
        ]
        req = MagicMock()
        req.contexts = contexts
        event = MagicMock()

        changed = await cleaner.process_contexts(event, req)
        self.assertFalse(changed)
        self.assertEqual(contexts[2]["content"], "A" * 2000)


if __name__ == "__main__":
    unittest.main()
