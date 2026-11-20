from typing import Any

try:
    from astrbot.api.web import json_response, request, error_response
except ImportError:
    def json_response(data, status_code=200, headers=None):
        return {"data": data, "status_code": status_code}
    def error_response(msg, status_code=400, data=None):
        return {"error": msg, "status_code": status_code, "data": data}
    request = None


class AuditApiHandler:
    """审计日志 Web API 处理模块，负责向 AstrBot Dashboard 提供日志查询、指标、导出与清空接口。"""

    def __init__(self, audit_logger: Any):
        self.audit_logger = audit_logger

    def register_routes(self, context: Any, plugin_name: str) -> None:
        """向 AstrBot 上下文注册 Web API 路由。"""
        if hasattr(context, "register_web_api") and callable(context.register_web_api):
            context.register_web_api(
                f"/{plugin_name}/audit/logs",
                self.api_audit_logs,
                ["GET"],
                "获取审计日志列表",
            )
            context.register_web_api(
                f"/{plugin_name}/audit/stats",
                self.api_audit_stats,
                ["GET"],
                "获取审计日志统计数据",
            )
            context.register_web_api(
                f"/{plugin_name}/audit/export",
                self.api_audit_export,
                ["GET"],
                "导出审计日志数据",
            )
            context.register_web_api(
                f"/{plugin_name}/audit/clear",
                self.api_audit_clear,
                ["POST"],
                "清空审计日志数据",
            )

    async def api_audit_logs(self):
        """分页与条件检索审计记录。"""
        page = 1
        page_size = 20
        keyword = ""
        status = "all"
        tool_name = ""

        req = request
        if req and hasattr(req, "query"):
            try:
                page = int(req.query.get("page", 1))
            except (ValueError, TypeError):
                page = 1
            try:
                page_size = min(max(1, int(req.query.get("page_size", 20))), 100)
            except (ValueError, TypeError):
                page_size = 20
            keyword = str(req.query.get("keyword", "") or "").strip()
            status = str(req.query.get("status", "all") or "all").strip()
            tool_name = str(req.query.get("tool_name", "") or "").strip()

        items, total = await self.audit_logger.query_logs(
            page=page, page_size=page_size, keyword=keyword, status=status, tool_name=tool_name
        )
        return json_response({
            "code": 0,
            "data": {
                "total": total,
                "items": items,
                "page": page,
                "page_size": page_size,
            }
        })

    async def api_audit_stats(self):
        """获取审计指标数据。"""
        stats = await self.audit_logger.get_stats()
        return json_response({"code": 0, "data": stats})

    async def api_audit_export(self):
        """导出审计数据为 JSON 或 CSV。"""
        fmt = "json"
        keyword = ""
        status = "all"
        tool_name = ""

        req = request
        if req and hasattr(req, "query"):
            fmt = str(req.query.get("format", req.query.get("fmt", "json")) or "json").strip()
            keyword = str(req.query.get("keyword", "") or "").strip()
            status = str(req.query.get("status", "all") or "all").strip()
            tool_name = str(req.query.get("tool_name", "") or "").strip()

        content = await self.audit_logger.export_logs(
            fmt=fmt, keyword=keyword, status=status, tool_name=tool_name
        )
        return json_response({"code": 0, "data": content, "format": fmt})

    async def api_audit_clear(self):
        """清空历史审计记录。"""
        confirm = False
        req = request
        if req and hasattr(req, "json") and callable(req.json):
            try:
                payload = await req.json(default={})
                if isinstance(payload, dict):
                    confirm = bool(payload.get("confirm", False))
            except Exception:
                confirm = False

        if not confirm:
            return json_response({"code": -1, "message": "清空操作需要确认参数 confirm=true"}, status_code=400)

        cleared = await self.audit_logger.clear_logs()
        return json_response({"code": 0, "data": {"cleared": cleared}})
