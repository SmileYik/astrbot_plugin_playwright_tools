import sqlite3
import json
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_GROUPS: dict[str, list[str]] = {
    "pw_page": ["open_url", "read_page", "search_page", "switch_tab", "handle_dialog", "close_browser"],
    "pw_interact": ["click", "fill_form", "select_option", "hover", "focus", "blur", "drag", "press_key", "scroll"],
    "pw_media": ["screenshot_viewport", "screenshot_full", "download_file"],
}

class AuditLogger:
    """SQLite 审计记录器，负责记录所有大模型工具调用并在启动或定时任务中清理过期数据。"""

    def __init__(self, db_path: str = "data/audit.db", max_output_chars: int = 0):
        self.db_path = db_path
        self.max_output_chars = max_output_chars
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
                        session_name TEXT DEFAULT '',
                        context_key TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        sender_name TEXT DEFAULT '',
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
        session_name: str = "",
        sender_name: str = "",
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
                        timestamp, session_id, session_name, context_key, sender_id, sender_name,
                        tool_name, url, input_args, output_result, is_permitted, deny_reason,
                        is_error, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts, session_id, session_name, context_key, sender_id, sender_name,
                        tool_name, url, args_json, output_result, 1 if is_permitted else 0,
                        deny_reason, 1 if is_error else 0, error_message
                    )
                )
        finally:
            conn.close()

    def _build_where_clause(
        self,
        keyword: str = "",
        status: str = "all",
        tool_name: str = "",
    ) -> tuple[str, list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if keyword and keyword.strip():
            kw = f"%{keyword.strip()}%"
            conditions.append(
                "(url LIKE ? OR input_args LIKE ? OR output_result LIKE ? OR error_message LIKE ? OR session_name LIKE ? OR sender_name LIKE ?)"
            )
            params.extend([kw] * 6)

        if status == "allowed":
            conditions.append("is_permitted = 1 AND is_error = 0")
        elif status == "denied":
            conditions.append("is_permitted = 0")
        elif status == "error":
            conditions.append("is_error = 1")

        if tool_name and tool_name.strip():
            tn = tool_name.strip()
            if tn in TOOL_GROUPS:
                actions = TOOL_GROUPS[tn]
                placeholders = ", ".join(["?"] * len(actions))
                conditions.append(f"(tool_name = ? OR tool_name LIKE ? OR tool_name IN ({placeholders}))")
                params.extend([tn, f"{tn}:%"] + actions)
            else:
                conditions.append("(tool_name = ? OR tool_name LIKE ?)")
                params.extend([tn, f"{tn}:%"])

        where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return where_sql, params

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["is_permitted"] = bool(item.get("is_permitted", 0))
        item["is_error"] = bool(item.get("is_error", 0))
        return item

    async def query_logs(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
        status: str = "all",
        tool_name: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        """多条件模糊查询与分页获取审计记录。"""
        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        offset = (page - 1) * page_size

        where_sql, params = self._build_where_clause(keyword=keyword, status=status, tool_name=tool_name)

        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM tool_audit_logs {where_sql}", params)
            count_row = cur.fetchone()
            total = count_row[0] if count_row else 0

            cur.execute(
                f"SELECT * FROM tool_audit_logs {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            )
            rows = cur.fetchall()
            items = [self._row_to_dict(r) for r in rows]
            return items, total
        finally:
            conn.close()

    async def get_stats(self) -> dict[str, int]:
        """统计审计指标数据：总数、允许数、拒绝数、错误数、今日调用数。"""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_permitted = 1 AND is_error = 0 THEN 1 ELSE 0 END) as allowed,
                    SUM(CASE WHEN is_permitted = 0 THEN 1 ELSE 0 END) as denied,
                    SUM(CASE WHEN is_error = 1 THEN 1 ELSE 0 END) as error,
                    SUM(CASE WHEN date(timestamp) = date('now') THEN 1 ELSE 0 END) as today_count
                FROM tool_audit_logs
            """)
            row = cur.fetchone()
            if not row:
                return {"total": 0, "allowed": 0, "denied": 0, "error": 0, "today_count": 0}
            return {
                "total": int(row[0] or 0),
                "allowed": int(row[1] or 0),
                "denied": int(row[2] or 0),
                "error": int(row[3] or 0),
                "today_count": int(row[4] or 0),
            }
        finally:
            conn.close()

    async def export_logs(
        self,
        fmt: str = "json",
        keyword: str = "",
        status: str = "all",
        tool_name: str = "",
    ) -> str:
        """导出符合条件的审计记录为 JSON 或标准 CSV 格式。"""
        where_sql, params = self._build_where_clause(keyword=keyword, status=status, tool_name=tool_name)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM tool_audit_logs {where_sql} ORDER BY id DESC", params)
            rows = cur.fetchall()
            items = [self._row_to_dict(r) for r in rows]

            if fmt.lower() == "csv":
                output = io.StringIO()
                fieldnames = [
                    "id", "timestamp", "session_id", "session_name", "context_key",
                    "sender_id", "sender_name", "tool_name", "url", "input_args",
                    "output_result", "is_permitted", "deny_reason", "is_error", "error_message"
                ]
                writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                for item in items:
                    safe_item = {}
                    for k, v in item.items():
                        if isinstance(v, str) and v and v[0] in ("=", "+", "-", "@", "\t", "\r"):
                            safe_item[k] = f"'{v}"
                        else:
                            safe_item[k] = v
                    writer.writerow(safe_item)
                return output.getvalue()

            return json.dumps(items, ensure_ascii=False, indent=2)
        finally:
            conn.close()

    async def clear_logs(self) -> int:
        """清空所有审计记录，返回删除条数。"""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            with conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM tool_audit_logs")
                return cur.rowcount
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

