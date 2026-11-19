import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class AuditLogger:
    """SQLite 审计记录器，负责记录所有大模型工具调用并在启动或定时任务中清理过期数据。"""

    def __init__(self, db_path: str = "data/audit.db"):
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self) -> None:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tool_audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        context_key TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        url TEXT,
                        input_args TEXT,
                        output_result TEXT,
                        is_permitted INTEGER NOT NULL,
                        deny_reason TEXT,
                        is_error INTEGER NOT NULL,
                        error_message TEXT
                    )
                """)
        finally:
            conn.close()

    async def log_action(
        self,
        session_id: str,
        context_key: str,
        sender_id: str,
        tool_name: str,
        url: str = "",
        input_args: dict | None = None,
        output_result: str = "",
        is_permitted: bool = True,
        deny_reason: str = "",
        is_error: bool = False,
        error_message: str = "",
        custom_timestamp: str | None = None,
    ) -> None:
        """记录单条工具审计记录。"""
        ts = custom_timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        args_json = json.dumps(input_args or {}, ensure_ascii=False)

        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO tool_audit_logs (
                        timestamp, session_id, context_key, sender_id, tool_name,
                        url, input_args, output_result, is_permitted, deny_reason,
                        is_error, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts, session_id, context_key, sender_id, tool_name,
                        url, args_json, output_result, 1 if is_permitted else 0,
                        deny_reason, 1 if is_error else 0, error_message
                    )
                )
        finally:
            conn.close()

    async def get_count(self) -> int:
        """获取总记录条数，便于测试与健康检查。"""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM tool_audit_logs")
            row = cur.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    async def cleanup_expired(self, retention_days: int) -> int:
        """清理超过保留天数的历史审计记录，返回删除条数。"""
        if retention_days <= 0:
            return 0

        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "DELETE FROM tool_audit_logs WHERE datetime(timestamp) < datetime('now', ?)",
                    (f"-{retention_days} days",)
                )
                return cur.rowcount
        finally:
            conn.close()
