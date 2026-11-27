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

    def test_include_compressed_in_watermark_config(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, {})
        self.assertFalse(cleaner.include_compressed_in_watermark)

        cleaner_with_hc = HistoryCleaner(self.context, {"history_cleanup": {"include_compressed_in_watermark": True}})
        self.assertTrue(cleaner_with_hc.include_compressed_in_watermark)

        cleaner_with_root = HistoryCleaner(self.context, {"include_compressed_in_watermark": True})
        self.assertTrue(cleaner_with_root.include_compressed_in_watermark)

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

    def test_is_candidate_tool(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner_default = HistoryCleaner(self.context, {"history_cleanup": {"include_compressed_in_watermark": False}})
        self.assertFalse(cleaner_default.is_candidate_tool(None))
        self.assertFalse(cleaner_default.is_candidate_tool(""))
        self.assertFalse(cleaner_default.is_candidate_tool("[该历史工具调用结果已按策略清理]"))
        self.assertFalse(cleaner_default.is_candidate_tool("[已并入本轮浏览摘要]"))
        self.assertFalse(cleaner_default.is_candidate_tool("[历史浏览摘要]:\n这是一段摘要"))
        self.assertTrue(cleaner_default.is_candidate_tool("Normal page markdown content"))

        cleaner_include = HistoryCleaner(self.context, {"history_cleanup": {"include_compressed_in_watermark": True}})
        self.assertFalse(cleaner_include.is_candidate_tool(None))
        self.assertFalse(cleaner_include.is_candidate_tool(""))
        self.assertFalse(cleaner_include.is_candidate_tool("[该历史工具调用结果已按策略清理]"))
        self.assertFalse(cleaner_include.is_candidate_tool("[已并入本轮浏览摘要]"))
        self.assertTrue(cleaner_include.is_candidate_tool("[历史浏览摘要]:\n这是一段摘要"))
        self.assertTrue(cleaner_include.is_candidate_tool("Normal page markdown content"))

    def test_calculate_uncompressed_chars_with_summary(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        contexts = [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                    {"id": "call_2", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                    {"id": "call_3", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}},
                    {"id": "call_4", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "pw_read", "content": "A" * 1000},
            {"role": "tool", "tool_call_id": "call_2", "name": "pw_read", "content": "[历史浏览摘要]:\n" + "S" * 200},
            {"role": "tool", "tool_call_id": "call_3", "name": "pw_page", "content": "[该历史工具调用结果已按策略清理]"},
            {"role": "tool", "tool_call_id": "call_4", "name": "pw_page", "content": "[已并入本轮浏览摘要]"},
        ]
        summary_len = len("[历史浏览摘要]:\n" + "S" * 200)

        cleaner_default = HistoryCleaner(self.context, {"history_cleanup": {"include_compressed_in_watermark": False}})
        self.assertEqual(cleaner_default.calculate_uncompressed_chars(contexts), 1000)
        self.assertEqual(cleaner_default.calculate_watermark_chars(contexts), 1000)

        cleaner_include = HistoryCleaner(self.context, {"history_cleanup": {"include_compressed_in_watermark": True}})
        self.assertEqual(cleaner_include.calculate_uncompressed_chars(contexts), 1000 + summary_len)
        self.assertEqual(cleaner_include.calculate_watermark_chars(contexts), 1000 + summary_len)

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
        self.assertEqual(res, "Line 1\n\nLine 2")

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

    async def test_compress_audit_and_logging_success(self):
        from astrbot.api import logger
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner

        mock_audit = MagicMock()
        mock_audit.log_action = AsyncMock()
        mock_audit.log_lifecycle = AsyncMock()

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
        cleaner = HistoryCleaner(self.context, cfg, audit_logger=mock_audit)

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
        mock_event = MagicMock()
        mock_event.get_session_id.return_value = "sess_100"
        mock_event.get_sender_id.return_value = "user_200"
        mock_event.get_sender_name.return_value = "Alice"
        mock_event.get_session_name.return_value = "GroupA"
        mock_event.get_context_key.return_value = "ctx_100"

        logger.info.reset_mock()
        changed = await cleaner.process_contexts(mock_event, req)
        self.assertTrue(changed)

        # 1. 验证运行日志输出
        info_logs = [call.args[0] for call in logger.info.call_args_list if call.args]
        self.assertTrue(any("[HistoryCleaner] 检测到未压缩历史字符数" in msg and "超过高水位" in msg for msg in info_logs))
        self.assertTrue(any("[HistoryCleaner] 正在调用副 AI 对历史工具调用" in msg and "进行批量聚合压缩" in msg for msg in info_logs))
        self.assertTrue(any("[HistoryCleaner] 历史记录副 AI 批量压缩成功" in msg and "节省" in msg for msg in info_logs))
        self.assertTrue(any("[HistoryCleaner] 上下文历史清理完成" in msg for msg in info_logs))

        # 2. 验证 tool_audit_logs 记录
        mock_audit.log_action.assert_awaited_once()
        action_kwargs = mock_audit.log_action.await_args.kwargs
        self.assertEqual(action_kwargs["session_id"], "sess_100")
        self.assertEqual(action_kwargs["session_name"], "GroupA")
        self.assertEqual(action_kwargs["context_key"], "ctx_100")
        self.assertEqual(action_kwargs["sender_id"], "user_200")
        self.assertEqual(action_kwargs["sender_name"], "Alice")
        self.assertEqual(action_kwargs["tool_name"], "pw_history:compress")
        self.assertEqual(action_kwargs["output_result"], "这是副AI总结的网页摘要")
        self.assertTrue(action_kwargs["is_permitted"])
        self.assertFalse(action_kwargs["is_error"])
        input_args = action_kwargs["input_args"]
        self.assertEqual(input_args["batch_size"], 2)
        self.assertEqual(input_args["group_size"], 2)
        self.assertEqual(input_args["tools"], ["pw_page", "pw_read"])
        self.assertEqual(input_args["original_chars"], len("Opened page") + 6000)
        self.assertIn("preview", input_args)

        # 3. 验证 context_lifecycle_logs 记录
        mock_audit.log_lifecycle.assert_awaited_once()
        life_kwargs = mock_audit.log_lifecycle.await_args.kwargs
        self.assertEqual(life_kwargs["session_id"], "sess_100")
        self.assertEqual(life_kwargs["session_name"], "GroupA")
        self.assertEqual(life_kwargs["context_key"], "ctx_100")
        self.assertEqual(life_kwargs["owner_id"], "user_200")
        self.assertEqual(life_kwargs["owner_name"], "Alice")
        self.assertEqual(life_kwargs["operator_id"], "system")
        self.assertEqual(life_kwargs["operator_name"], "副AI压缩器")
        self.assertEqual(life_kwargs["event_type"], "history_compress")
        self.assertIsInstance(life_kwargs["details"], dict)
        self.assertEqual(life_kwargs["details"]["batch_size"], 2)
        self.assertEqual(life_kwargs["details"]["processed_groups"], 1)
        self.assertTrue(life_kwargs["details"]["reduced_chars"] > 0)

    async def test_compress_audit_fallback_on_error(self):
        from astrbot.api import logger
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner

        mock_audit = MagicMock()
        mock_audit.log_action = AsyncMock()
        mock_audit.log_lifecycle = AsyncMock()

        mock_provider = MagicMock()
        mock_provider.text_chat = AsyncMock(side_effect=RuntimeError("Sub-AI Provider Timeout"))
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
        cleaner = HistoryCleaner(self.context, cfg, audit_logger=mock_audit)

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
        mock_event = MagicMock()
        mock_event.get_session_id.return_value = "sess_100"
        mock_event.get_sender_id.return_value = "user_200"

        logger.warning.reset_mock()
        changed = await cleaner.process_contexts(mock_event, req)
        self.assertTrue(changed)

        # 1. 验证警告日志输出
        warn_logs = [call.args[0] for call in logger.warning.call_args_list if call.args]
        self.assertTrue(any("历史记录副 AI 批量压缩失败，自动降级为直接删除策略" in msg for msg in warn_logs))

        # 2. 验证工具审计记录两次：一次压缩失败，一次直接删除
        self.assertEqual(mock_audit.log_action.await_count, 2)
        call1 = mock_audit.log_action.await_args_list[0].kwargs
        self.assertEqual(call1["tool_name"], "pw_history:compress")
        self.assertTrue(call1["is_error"])
        self.assertIn("Sub-AI Provider Timeout", call1["error_message"])
        self.assertEqual(call1["input_args"]["batch_size"], 2)

        call2 = mock_audit.log_action.await_args_list[1].kwargs
        self.assertEqual(call2["tool_name"], "pw_history:delete")
        self.assertFalse(call2["is_error"])
        self.assertEqual(call2["output_result"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(call2["input_args"]["batch_size"], 2)

        # 3. 验证生命周期审计记录为 history_cleanup
        mock_audit.log_lifecycle.assert_awaited_once()
        life_kwargs = mock_audit.log_lifecycle.await_args.kwargs
        self.assertEqual(life_kwargs["event_type"], "history_cleanup")
        self.assertEqual(life_kwargs["operator_name"], "历史清理器")
        self.assertEqual(life_kwargs["details"]["batch_size"], 2)

    async def test_delete_strategy_audit_and_logging(self):
        from astrbot.api import logger
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner

        mock_audit = MagicMock()
        mock_audit.log_action = AsyncMock()
        mock_audit.log_lifecycle = AsyncMock()

        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 2000,
                "cleanup_strategy": "delete",
            }
        }
        cleaner = HistoryCleaner(self.context, cfg, audit_logger=mock_audit)

        contexts = [
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "A" * 6000},
            {"role": "assistant", "content": "ans 1"},
        ]
        req = MagicMock()
        req.contexts = contexts
        mock_event = MagicMock()
        mock_event.get_session_id.return_value = "sess_del"
        mock_event.get_sender_id.return_value = "user_del"

        logger.info.reset_mock()
        changed = await cleaner.process_contexts(mock_event, req)
        self.assertTrue(changed)

        # 1. 验证日志输出
        info_logs = [call.args[0] for call in logger.info.call_args_list if call.args]
        self.assertTrue(any("已按直接删除策略清理" in msg and "释放 6000 字符" in msg for msg in info_logs))
        self.assertTrue(any("上下文历史清理完成" in msg for msg in info_logs))

        # 2. 验证工具审计
        mock_audit.log_action.assert_awaited_once()
        call_kwargs = mock_audit.log_action.await_args.kwargs
        self.assertEqual(call_kwargs["tool_name"], "pw_history:delete")
        self.assertEqual(call_kwargs["output_result"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(call_kwargs["input_args"]["freed_chars"], 6000)
        self.assertEqual(call_kwargs["input_args"]["batch_size"], 1)
        self.assertEqual(call_kwargs["input_args"]["group_size"], 1)

        # 3. 验证生命周期审计
        mock_audit.log_lifecycle.assert_awaited_once()
        life_kwargs = mock_audit.log_lifecycle.await_args.kwargs
        self.assertEqual(life_kwargs["event_type"], "history_cleanup")
        self.assertEqual(life_kwargs["operator_name"], "历史清理器")
        self.assertEqual(life_kwargs["details"]["reduced_chars"], 6000)
        self.assertEqual(life_kwargs["details"]["batch_size"], 1)

    async def test_audit_logger_exception_isolation(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner

        mock_audit = MagicMock()
        mock_audit.log_action = AsyncMock(side_effect=RuntimeError("Database write error"))
        mock_audit.log_lifecycle = AsyncMock(side_effect=RuntimeError("Lifecycle write error"))

        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 2000,
                "cleanup_strategy": "delete",
            }
        }
        cleaner = HistoryCleaner(self.context, cfg, audit_logger=mock_audit)

        contexts = [
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "A" * 6000},
            {"role": "assistant", "content": "ans 1"},
        ]
        req = MagicMock()
        req.contexts = contexts
        mock_event = MagicMock()

        # Should not raise exception
        changed = await cleaner.process_contexts(mock_event, req)
        self.assertTrue(changed)
        self.assertEqual(contexts[2]["content"], "[该历史工具调用结果已按策略清理]")
        self.assertEqual(cleaner.calculate_uncompressed_chars(contexts), 0)

    async def test_process_contexts_with_direct_list(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)
        messages = [
            Message(role="user", content="hello"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_direct", name="pw_read", args="{}")],
            ),
            Message(role="tool", content="X" * 6000, tool_call_id="call_direct"),
            Message(role="assistant", content="answer"),
        ]
        mock_event = MagicMock()
        changed = await cleaner.process_contexts(mock_event, messages)
        self.assertTrue(changed)
        self.assertEqual(messages[2].content, "[该历史工具调用结果已按策略清理]")

    async def test_process_contexts_with_run_context(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)
        messages = [
            Message(role="user", content="hello"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_rc", name="pw_page", args="{}")],
            ),
            Message(role="tool", content="Y" * 7000, tool_call_id="call_rc"),
            Message(role="assistant", content="done"),
        ]
        run_context = MagicMock(spec=["messages"])
        run_context.messages = messages
        mock_event = MagicMock()
        changed = await cleaner.process_contexts(mock_event, run_context)
        self.assertTrue(changed)
        self.assertEqual(messages[2].content, "[该历史工具调用结果已按策略清理]")

    def test_get_content_with_content_parts(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        cleaner = HistoryCleaner(self.context, self.config)
        class DummyPart:
            def __init__(self, text):
                self.text = text
        msg = MagicMock(spec=["content"])
        msg.content = [DummyPart("Part 1: Hello. "), DummyPart("Part 2: World!")]
        content = cleaner._get_content(msg)
        self.assertEqual(content, "Part 1: Hello. Part 2: World!")

    async def test_single_pass_batch_compression_multiple_turns(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        mock_provider = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "5轮跨轮次全局结构化摘要"
        mock_provider.text_chat = AsyncMock(return_value=mock_resp)
        self.context.get_provider_by_id.return_value = mock_provider

        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 1000,
                "cleanup_strategy": "compress",
                "compress_provider_id": "mock_p",
            }
        }
        cleaner = HistoryCleaner(self.context, cfg)

        contexts = [
            {"role": "user", "content": "turn 1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "pw_read", "content": "Tool 1 content: " + "A" * 1500},
            {"role": "assistant", "content": "thought 1"},
            {"role": "user", "content": "turn 2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c2", "name": "pw_page", "content": "Tool 2 content: " + "B" * 1500},
            {"role": "assistant", "content": "thought 2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c3", "type": "function", "function": {"name": "pw_interact", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c3", "name": "pw_interact", "content": "Tool 3 content: " + "C" * 1500},
            {"role": "user", "content": "turn 3"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c4", "type": "function", "function": {"name": "pw_media", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c4", "name": "pw_media", "content": "Tool 4 content: " + "D" * 1500},
            {"role": "assistant", "content": "thought 3"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c5", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c5", "name": "pw_read", "content": "Tool 5 content: " + "E" * 1500},
            {"role": "assistant", "content": "final answer"},
        ]
        req = MagicMock()
        req.contexts = contexts
        event = MagicMock()

        changed = await cleaner.process_contexts(event, req)
        self.assertTrue(changed)

        # Assert mock_provider.text_chat is called EXACTLY ONCE
        mock_provider.text_chat.assert_awaited_once()

        # Older items (indices 2, 6, 9, 12) have MERGE_PLACEHOLDER
        self.assertEqual(contexts[2]["content"], "[已并入本轮浏览摘要]")
        self.assertEqual(contexts[6]["content"], "[已并入本轮浏览摘要]")
        self.assertEqual(contexts[9]["content"], "[已并入本轮浏览摘要]")
        self.assertEqual(contexts[12]["content"], "[已并入本轮浏览摘要]")

        # Last item (index 15) has [历史浏览摘要]:\n{summary}
        self.assertEqual(contexts[15]["content"], "[历史浏览摘要]:\n5轮跨轮次全局结构化摘要")

    async def test_batch_compression_with_existing_summary_rollup(self):
        from astrbot_plugin_playwright_tools.core.history_cleaner import HistoryCleaner
        mock_provider = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "滚动重压缩聚合摘要"
        mock_provider.text_chat = AsyncMock(return_value=mock_resp)
        self.context.get_provider_by_id.return_value = mock_provider

        cfg = {
            "history_cleanup": {
                "enable_cleanup": True,
                "high_watermark": 5000,
                "low_watermark": 1000,
                "cleanup_strategy": "compress",
                "compress_provider_id": "mock_p",
                "include_compressed_in_watermark": True,
            }
        }
        cleaner = HistoryCleaner(self.context, cfg)

        contexts = [
            {"role": "user", "content": "turn 1"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "pw_page", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "pw_page", "content": "[历史浏览摘要]:\n前序轮次已提炼摘要内容：访问了主页并搜索关键词"},
            {"role": "assistant", "content": "turn 2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c2", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c2", "name": "pw_read", "content": "新页面正文数据: " + "X" * 3000},
            {"role": "assistant", "content": "turn 3"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c3", "type": "function", "function": {"name": "pw_read", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c3", "name": "pw_read", "content": "详情页内容: " + "Y" * 3000},
            {"role": "assistant", "content": "final answer"},
        ]

        req = MagicMock()
        req.contexts = contexts
        event = MagicMock()

        changed = await cleaner.process_contexts(event, req)
        self.assertTrue(changed)

        mock_provider.text_chat.assert_awaited_once()
        call_kwargs = mock_provider.text_chat.await_args.kwargs
        prompt = call_kwargs["prompt"]

        # Assert prompt contains 【前序历史摘要】 and 【工具: pw_read】
        self.assertIn("【前序历史摘要】", prompt)
        self.assertIn("前序轮次已提炼摘要内容：访问了主页并搜索关键词", prompt)
        self.assertIn("【工具: pw_read】", prompt)

        # Existing summary (idx 2) replaced with MERGE_PLACEHOLDER
        self.assertEqual(contexts[2]["content"], "[已并入本轮浏览摘要]")
        # Second tool (idx 5) replaced with MERGE_PLACEHOLDER
        self.assertEqual(contexts[5]["content"], "[已并入本轮浏览摘要]")
        # Final item (idx 8) has new summary
        self.assertEqual(contexts[8]["content"], "[历史浏览摘要]:\n滚动重压缩聚合摘要")


if __name__ == "__main__":
    unittest.main()
