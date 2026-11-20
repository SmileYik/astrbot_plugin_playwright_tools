import unittest
import os
import sys
import tempfile
import json
import csv
import io
from pathlib import Path

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
try:
    from core.audit_logger import AuditLogger
except ImportError:
    from astrbot_plugin_playwright_tools.core.audit_logger import AuditLogger

TEMP_DIR = Path(tempfile.gettempdir()) / "astrbot_test_audit"

def run_coro(coro):
    """在无网络沙箱环境下无开销执行普通协程，规避 socket.socketpair 挂起问题。"""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestAuditLogger(unittest.TestCase):
    def setUp(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = str(TEMP_DIR / "test_audit.db")
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.logger = AuditLogger(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_log_action_and_query(self):
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="click", url="https://example.com",
            input_args={"ref": 1}, output_result="ok",
            is_permitted=True, session_name="群聊A", sender_name="用户甲"
        ))
        count = run_coro(self.logger.get_count())
        self.assertEqual(count, 1)

        items, total = run_coro(self.logger.query_logs(page=1, page_size=10))
        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["session_name"], "群聊A")
        self.assertEqual(items[0]["sender_name"], "用户甲")
        self.assertEqual(items[0]["tool_name"], "click")

    def test_query_logs_pagination_and_filters(self):
        # 插入 4 条不同状态与字段的测试数据
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="pw_page:open_url", url="https://github.com",
            input_args={"url": "https://github.com"}, output_result="ok",
            is_permitted=True, is_error=False,
            session_name="开发群", sender_name="Alice"
        ))
        run_coro(self.logger.log_action(
            session_id="s2", context_key="c2", sender_id="u2",
            tool_name="pw_interact:click", url="https://example.com",
            input_args={"ref": 42}, output_result="",
            is_permitted=False, deny_reason="Domain blocked",
            session_name="私聊: Bob", sender_name="Bob"
        ))
        run_coro(self.logger.log_action(
            session_id="s3", context_key="c3", sender_id="u3",
            tool_name="pw_page:open_url", url="https://bad-site.org",
            input_args={}, output_result="",
            is_permitted=True, is_error=True, error_message="NetError: timed out",
            session_name="测试群", sender_name="Charlie"
        ))
        run_coro(self.logger.log_action(
            session_id="s4", context_key="c4", sender_id="u4",
            tool_name="pw_media:screenshot", url="https://github.com/profile",
            input_args={"target": "chat"}, output_result="screenshot_bytes",
            is_permitted=True, is_error=False,
            session_name="开发群", sender_name="Dave"
        ))

        # 1. 验证分页与总数
        items, total = run_coro(self.logger.query_logs(page=1, page_size=2))
        self.assertEqual(total, 4)
        self.assertEqual(len(items), 2)

        items_p2, total_p2 = run_coro(self.logger.query_logs(page=2, page_size=2))
        self.assertEqual(total_p2, 4)
        self.assertEqual(len(items_p2), 2)
        self.assertNotEqual(items[0]["id"], items_p2[0]["id"])

        # 2. 状态筛选: allowed (permitted & not error)
        allowed_items, allowed_total = run_coro(self.logger.query_logs(status="allowed"))
        self.assertEqual(allowed_total, 2)
        for it in allowed_items:
            self.assertTrue(it["is_permitted"])
            self.assertFalse(it["is_error"])

        # 状态筛选: denied
        denied_items, denied_total = run_coro(self.logger.query_logs(status="denied"))
        self.assertEqual(denied_total, 1)
        self.assertEqual(denied_items[0]["sender_name"], "Bob")

        # 状态筛选: error
        error_items, error_total = run_coro(self.logger.query_logs(status="error"))
        self.assertEqual(error_total, 1)
        self.assertEqual(error_items[0]["sender_name"], "Charlie")

        # 3. 工具名筛选与工具分组匹配
        # 3.1 兼容前缀匹配
        page_items, page_total = run_coro(self.logger.query_logs(tool_name="pw_page:open_url"))
        self.assertEqual(page_total, 2)

        # 3.2 记录一条原生原子动作 open_url 与 click
        run_coro(self.logger.log_action(
            session_id="s5", context_key="c5", sender_id="u5",
            tool_name="open_url", url="https://example.com/atomic",
            is_permitted=True, session_name="群5", sender_name="Eva"
        ))
        run_coro(self.logger.log_action(
            session_id="s6", context_key="c6", sender_id="u6",
            tool_name="click", url="https://example.com/atomic",
            is_permitted=True, session_name="群6", sender_name="Frank"
        ))

        # 通过 pw_page 组名检索，应匹配 pw_page:open_url 及 open_url
        group_items, group_total = run_coro(self.logger.query_logs(tool_name="pw_page"))
        self.assertEqual(group_total, 3)

        # 通过 pw_interact 组名检索，应匹配 pw_interact:click 及 click
        interact_items, interact_total = run_coro(self.logger.query_logs(tool_name="pw_interact"))
        self.assertEqual(interact_total, 2)

        # 验证 page_size 上限保护
        items_large, _ = run_coro(self.logger.query_logs(page_size=500))
        self.assertLessEqual(len(items_large), 100)

        # 4. 关键词搜索: url 模糊匹配
        kw_items, kw_total = run_coro(self.logger.query_logs(keyword="github"))
        self.assertEqual(kw_total, 2)

        # 关键词搜索: session_name
        kw_s_items, kw_s_total = run_coro(self.logger.query_logs(keyword="私聊"))
        self.assertEqual(kw_s_total, 1)
        self.assertEqual(kw_s_items[0]["session_id"], "s2")

        # 关键词搜索: error_message
        kw_e_items, kw_e_total = run_coro(self.logger.query_logs(keyword="timed out"))
        self.assertEqual(kw_e_total, 1)

    def test_get_stats(self):
        # 插入 1 条历史数据与 2 条今日数据
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="click", url="https://example.com",
            is_permitted=True, is_error=False,
            custom_timestamp="2020-01-01 12:00:00"
        ))
        run_coro(self.logger.log_action(
            session_id="s2", context_key="c2", sender_id="u2",
            tool_name="click", url="https://example.com",
            is_permitted=False, deny_reason="blocked",
            # 今日默认时间戳
        ))
        run_coro(self.logger.log_action(
            session_id="s3", context_key="c3", sender_id="u3",
            tool_name="click", url="https://example.com",
            is_permitted=True, is_error=True, error_message="fail",
            # 今日默认时间戳
        ))

        stats = run_coro(self.logger.get_stats())
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["allowed"], 1)
        self.assertEqual(stats["denied"], 1)
        self.assertEqual(stats["error"], 1)
        self.assertEqual(stats["today_count"], 2)

    def test_export_logs_json_and_csv(self):
        # 包含换行、双引号与逗号的文本测试 RFC 4180 CSV 转义，以及敏感符号测试公式注入防御
        special_output = 'Line 1, "quoted text"\nLine 2 with comma, and end.'
        formula_text = "=cmd|' /C calc'!A0"
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="pw_page:open_url", url="https://example.com",
            input_args={"cmd": 'echo "hello, world"'},
            output_result=special_output,
            is_permitted=True, session_name="群聊,带逗号", sender_name=formula_text
        ))

        # 1. 导出 JSON
        json_str = run_coro(self.logger.export_logs(fmt="json"))
        data = json.loads(json_str)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["output_result"], special_output)

        # 2. 导出 CSV
        csv_str = run_coro(self.logger.export_logs(fmt="csv"))
        reader = csv.reader(io.StringIO(csv_str))
        rows = list(reader)
        # 第一行为 header
        self.assertGreaterEqual(len(rows), 2)
        header = rows[0]
        self.assertIn("session_name", header)
        self.assertIn("sender_name", header)
        self.assertIn("output_result", header)

        # 验证包含换行和特殊字符的数据正确解析回原始字符串
        out_idx = header.index("output_result")
        session_idx = header.index("session_name")
        sender_idx = header.index("sender_name")
        self.assertEqual(rows[1][out_idx], special_output)
        self.assertEqual(rows[1][session_idx], "群聊,带逗号")
        # 验证公式注入前缀防御转义为 '=cmd...
        self.assertTrue(rows[1][sender_idx].startswith("'="))

    def test_clear_logs(self):
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="click", is_permitted=True
        ))
        run_coro(self.logger.log_action(
            session_id="s2", context_key="c2", sender_id="u2",
            tool_name="click", is_permitted=True
        ))
        self.assertEqual(run_coro(self.logger.get_count()), 2)

        cleared = run_coro(self.logger.clear_logs())
        self.assertEqual(cleared, 2)
        self.assertEqual(run_coro(self.logger.get_count()), 0)

    def test_cleanup_expired(self):
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="read", url="https://example.com",
            input_args={}, output_result="ok", is_permitted=True,
            custom_timestamp="2020-01-01 00:00:00"
        ))
        cleaned = run_coro(self.logger.cleanup_expired(retention_days=30))
        self.assertEqual(cleaned, 1)
        count = run_coro(self.logger.get_count())
        self.assertEqual(count, 0)

    def test_audit_records_real_output_and_truncates_when_limit_set(self):
        self.logger.max_output_chars = 20
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="pw_page:read", url="https://example.com",
            output_result="12345678901234567890EXTRA_TEXT"
        ))
        items, _ = run_coro(self.logger.query_logs(page=1, page_size=1))
        self.assertTrue(items[0]["output_result"].startswith("12345678901234567890"))
        self.assertIn("[审计日志已截断", items[0]["output_result"])

    def test_audit_records_screenshot_path(self):
        run_coro(self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="pw_media:screenshot_viewport", url="https://example.com",
            output_result="截图成功", screenshot_path="data/audit_screenshots/shot_123.png"
        ))
        items, _ = run_coro(self.logger.query_logs(page=1, page_size=1))
        self.assertEqual(items[0]["screenshot_path"], "data/audit_screenshots/shot_123.png")

    def test_lifecycle_logs_crud(self):
        # 记录生命周期事件
        run_coro(self.logger.log_lifecycle(
            session_id="sess_100",
            context_key="sess_100:user_1",
            owner_id="user_1",
            event_type="create",
            operator_id="user_1",
            session_name="测试群",
            details={"adapter": "camoufox", "tab_count": 1}
        ))
        run_coro(self.logger.log_lifecycle(
            session_id="sess_101",
            context_key="sess_101:user_2",
            owner_id="user_2",
            event_type="close",
            operator_id="user_2",
            session_name="开发群",
            details=None
        ))
        run_coro(self.logger.log_lifecycle(
            session_id="sess_100",
            context_key="sess_100:user_1",
            owner_id="user_1",
            event_type="timeout",
            operator_id="system",
            session_name="测试群",
            details="timed out after 300s"
        ))

        # 1. 过滤 event_type
        items, total = run_coro(self.logger.query_lifecycle_logs(page=1, page_size=10, event_type="create"))
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["event_type"], "create")
        self.assertEqual(items[0]["owner_id"], "user_1")
        self.assertIn("camoufox", items[0]["details"])

        # 2. 过滤 session_id
        items_sess, total_sess = run_coro(self.logger.query_lifecycle_logs(session_id="sess_100"))
        self.assertEqual(total_sess, 2)
        self.assertEqual(len(items_sess), 2)

        # 3. 关键词过滤
        items_kw, total_kw = run_coro(self.logger.query_lifecycle_logs(keyword="开发群"))
        self.assertEqual(total_kw, 1)
        self.assertEqual(items_kw[0]["session_name"], "开发群")
        self.assertEqual(items_kw[0]["details"], "{}")

        # 4. 分页
        items_p1, total_p = run_coro(self.logger.query_lifecycle_logs(page=1, page_size=2))
        self.assertEqual(total_p, 3)
        self.assertEqual(len(items_p1), 2)
        items_p2, _ = run_coro(self.logger.query_lifecycle_logs(page=2, page_size=2))
        self.assertEqual(len(items_p2), 1)
        self.assertNotEqual(items_p1[0]["id"], items_p2[0]["id"])

try:
    import pytest
except ImportError:
    pytest = None

if pytest is not None:
    @pytest.mark.asyncio
    async def test_lifecycle_logs_crud(tmp_path):
        db_file = str(tmp_path / "test_lifecycle.db")
        logger = AuditLogger(db_path=db_file)
        await logger.log_lifecycle(
            session_id="sess_100",
            context_key="sess_100:user_1",
            owner_id="user_1",
            event_type="create",
            operator_id="user_1",
            session_name="测试群",
            details={"adapter": "camoufox", "tab_count": 1}
        )
        items, total = await logger.query_lifecycle_logs(page=1, page_size=10, event_type="create")
        assert total == 1
        assert items[0]["event_type"] == "create"
        assert items[0]["owner_id"] == "user_1"
        assert "camoufox" in items[0]["details"]

if __name__ == "__main__":
    unittest.main()

