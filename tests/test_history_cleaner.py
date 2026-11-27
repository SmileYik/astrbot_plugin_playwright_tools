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

    def test_watermark_inversion_defense(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 4000,
                "low_watermark": 5000,
            }
        }
        cleaner = HistoryCleaner(self.context, cfg)
        self.assertEqual(cleaner.high_watermark, 4000)
        self.assertEqual(cleaner.low_watermark, 2000)

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

    def test_calculate_uncompressed_chars_objects(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        tc1 = ToolCall(id="call_1", name="pw_read")
        tc2 = ToolCall(id="call_2", name="other_tool")
        tc3 = ToolCall(id="call_3", name="pw_page")

        contexts = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="", tool_calls=[tc1, tc2]),
            Message(role="tool", tool_call_id="call_1", content="A" * 3000),
            Message(role="tool", tool_call_id="call_2", content="B" * 5000),
            Message(role="assistant", content="", tool_calls=[tc3]),
            Message(role="tool", tool_call_id="call_3", content="[该历史工具调用结果已按策略清理]"),
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

    def test_prepare_compress_input(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, {"history_cleanup": {"compress_max_input_chars": 0}})
        res = cleaner._prepare_compress_input(["Line 1", "Line 2"])
        self.assertEqual(res, "Line 1\nLine 2")

        cleaner_limited = HistoryCleaner(self.context, {"history_cleanup": {"compress_max_input_chars": 10}})
        res_limited = cleaner_limited._prepare_compress_input(["123456789012345"])
        self.assertTrue(res_limited.startswith("1234567890"))
        self.assertIn("已截断", res_limited)

    async def test_resolve_system_prompt_with_persona(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        # 1. Without persona
        cleaner = HistoryCleaner(self.context, {"history_cleanup": {"compress_use_persona": False, "compress_prompt": "Test Prompt"}})
        prompt = await cleaner._resolve_system_prompt()
        self.assertEqual(prompt, "Test Prompt")

        # 2. With specific persona
        mock_persona = MagicMock()
        mock_persona.system_prompt = "Persona System Prompt"
        self.context.persona_manager.get_persona = AsyncMock(return_value=mock_persona)

        cleaner_p = HistoryCleaner(self.context, {
            "history_cleanup": {
                "compress_use_persona": True,
                "compress_persona_id": "custom_p",
                "compress_prompt": "Test Prompt",
            }
        })
        prompt_p = await cleaner_p._resolve_system_prompt()
        self.context.persona_manager.get_persona.assert_awaited_with("custom_p")
        self.assertIn("Persona System Prompt", prompt_p)
        self.assertIn("Test Prompt", prompt_p)

        # 3. With default persona fallback
        self.context.persona_manager.default_persona = "default_p"
        cleaner_def = HistoryCleaner(self.context, {
            "history_cleanup": {
                "compress_use_persona": True,
                "compress_persona_id": "",
                "compress_prompt": "Test Prompt",
            }
        })
        prompt_def = await cleaner_def._resolve_system_prompt()
        self.context.persona_manager.get_persona.assert_awaited_with("default_p")
        self.assertIn("Persona System Prompt", prompt_def)

    async def test_process_contexts_compress_mode_success(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        mock_provider = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "这是副AI总结的网页摘要"
        mock_provider.text_chat = AsyncMock(return_value=mock_resp)
        self.context.get_provider_by_id.return_value = mock_provider

        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 2000,
                "cleanup_strategy": "compress",
                "compress_provider_id": "mock_p",
            }
        }
        cleaner = HistoryCleaner(self.context, cfg)

        contexts = [
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "Opened page"},
            {"role": "tool", "tool_call_id": "c2", "content": "A" * 6000},
            {"role": "assistant", "content": "ans 1"},
        ]
        req = MagicMock()
        req.contexts = contexts
        event = MagicMock()

        changed = await cleaner.process_contexts(event, req)
        self.assertTrue(changed)
        mock_provider.text_chat.assert_awaited_once()
        self.assertEqual(contexts[2]["content"], "[已并入本轮浏览摘要]")
        self.assertTrue(contexts[3]["content"].startswith("[历史浏览摘要]:\n这是副AI总结的网页摘要"))
        self.assertEqual(cleaner.calculate_uncompressed_chars(contexts), 0)

    async def test_process_contexts_compress_fallback_on_error(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        mock_provider = MagicMock()
        mock_provider.text_chat = AsyncMock(side_effect=RuntimeError("API Connection Timeout"))
        self.context.get_provider_by_id.return_value = mock_provider

        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 2000,
                "cleanup_strategy": "compress",
                "compress_provider_id": "mock_p",
            }
        }
        cleaner = HistoryCleaner(self.context, cfg)

        contexts = [
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "Opened page"},
            {"role": "tool", "tool_call_id": "c2", "content": "A" * 6000},
            {"role": "assistant", "content": "ans 1"},
        ]
        req = MagicMock()
        req.contexts = contexts
        event = MagicMock()

        changed = await cleaner.process_contexts(event, req)
        self.assertTrue(changed)
        # Fallback to delete placeholder
        self.assertEqual(contexts[2]["content"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(contexts[3]["content"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(cleaner.calculate_uncompressed_chars(contexts), 0)

    def test_init_with_audit_logger(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        mock_audit = MagicMock()
        cleaner = HistoryCleaner(self.context, self.config, audit_logger=mock_audit)
        self.assertEqual(cleaner.audit_logger, mock_audit)

        cleaner_default = HistoryCleaner(self.context, self.config)
        self.assertIsNone(cleaner_default.audit_logger)

    def test_extract_event_info_normal(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        # 1. Event with methods and attributes
        mock_event = MagicMock()
        mock_event.get_session_id.return_value = "session_123"
        mock_event.get_sender_id.return_value = "user_456"
        mock_event.get_sender_name.return_value = "Alice"
        mock_event.session_name = "TechGroup"
        mock_event.context_key = "ctx_tech_123"

        info = cleaner._extract_event_info(mock_event)
        self.assertEqual(info["session_id"], "session_123")
        self.assertEqual(info["sender_id"], "user_456")
        self.assertEqual(info["sender_name"], "Alice")
        self.assertEqual(info["session_name"], "TechGroup")
        self.assertEqual(info["context_key"], "ctx_tech_123")

        # 2. Event with unified_msg_origin object
        mock_event_umo = MagicMock(spec=["unified_msg_origin"])
        mock_umo = MagicMock()
        mock_umo.group_id = "group_789"
        mock_umo.group_name = "AstrBotDev"
        mock_umo.user_id = "user_999"
        mock_umo.user_name = "Bob"
        mock_umo.context_key = "umo_ctx_789"
        mock_event_umo.unified_msg_origin = mock_umo

        info_umo = cleaner._extract_event_info(mock_event_umo)
        self.assertEqual(info_umo["session_id"], "group_789")
        self.assertEqual(info_umo["session_name"], "AstrBotDev")
        self.assertEqual(info_umo["sender_id"], "user_999")
        self.assertEqual(info_umo["sender_name"], "Bob")
        self.assertEqual(info_umo["context_key"], "umo_ctx_789")

        # 3. Context key fallback to session_id when not provided
        mock_event_simple = MagicMock()
        mock_event_simple.get_session_id.return_value = "sess_fallback"
        mock_event_simple.get_sender_id.return_value = "user_simple"
        mock_event_simple.get_sender_name.return_value = ""
        mock_event_simple.session_name = ""
        mock_event_simple.context_key = ""
        mock_event_simple.unified_msg_origin = None

        info_simple = cleaner._extract_event_info(mock_event_simple)
        self.assertEqual(info_simple["session_id"], "sess_fallback")
        self.assertEqual(info_simple["context_key"], "sess_fallback")

    def test_extract_event_info_none_or_partial(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)

        # 1. event = None
        info_none = cleaner._extract_event_info(None)
        self.assertIsInstance(info_none, dict)
        self.assertEqual(info_none["session_id"], "")
        self.assertEqual(info_none["session_name"], "")
        self.assertEqual(info_none["sender_id"], "")
        self.assertEqual(info_none["sender_name"], "")
        self.assertEqual(info_none["context_key"], "")

        # 2. empty custom object
        class EmptyEvent:
            pass

        info_empty = cleaner._extract_event_info(EmptyEvent())
        self.assertEqual(info_empty["session_id"], "")
        self.assertEqual(info_empty["session_name"], "")
        self.assertEqual(info_empty["sender_id"], "")
        self.assertEqual(info_empty["sender_name"], "")
        self.assertEqual(info_empty["context_key"], "")

        # 3. Partial event with only session_id
        class PartialEvent:
            session_id = "partial_sess"

        info_partial = cleaner._extract_event_info(PartialEvent())
        self.assertEqual(info_partial["session_id"], "partial_sess")
        self.assertEqual(info_partial["context_key"], "partial_sess")
        self.assertEqual(info_partial["sender_id"], "")
        self.assertEqual(info_partial["sender_name"], "")
        self.assertEqual(info_partial["session_name"], "")


if __name__ == "__main__":
    unittest.main()
