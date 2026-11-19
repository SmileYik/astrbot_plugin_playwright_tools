import unittest
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.audit_logger import AuditLogger

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
            is_permitted=True
        ))
        count = run_coro(self.logger.get_count())
        self.assertEqual(count, 1)

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

if __name__ == "__main__":
    unittest.main()
