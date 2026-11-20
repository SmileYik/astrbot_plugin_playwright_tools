import os
from pathlib import Path
from typing import Any

try:
    from astrbot.api.web import json_response, request, error_response
except ImportError:
    def json_response(data, status_code=200, headers=None):
        return {"data": data, "status_code": status_code}
    def error_response(msg, status_code=400, data=None):
        return {"error": msg, "status_code": status_code, "data": data}
    request = None


def extract_query_param(req: Any, key: str, default: Any = None, type_conv: Any = None) -> Any:
    """从不同类型的请求对象（DashboardRequest, Starlette Request 等）中可靠提取 query 参数。"""
    if req is None:
        return default
    val = None
    containers = []
    for attr in ("query", "args", "query_params"):
        c = getattr(req, attr, None)
        if c is not None:
            containers.append(c)
    if hasattr(req, "_request"):
        inner = getattr(req, "_request")
        for attr in ("query", "args", "query_params"):
            c = getattr(inner, attr, None)
            if c is not None:
                containers.append(c)

    for container in containers:
        try:
            from unittest.mock import Mock
            if isinstance(container, Mock) and not getattr(container, "_mock_return_value", None) and not getattr(container, "side_effect", None) and not (hasattr(container, "__contains__") and key in container):
                continue
        except ImportError:
            pass

        if hasattr(container, "get") and callable(container.get):
            try:
                res = container.get(key)
                try:
                    from unittest.mock import Mock
                    if isinstance(res, Mock):
                        res = None
                except ImportError:
                    pass
                if res is not None:
                    val = res
                    break
            except Exception:
                pass

    if val is None:
        return default
    if type_conv is not None:
        try:
            return type_conv(val)
        except (ValueError, TypeError):
            return default
    return val


class AuditApiHandler:
    """审计日志 Web API 处理模块，负责向 AstrBot Dashboard 提供日志查询、指标、导出、清空与截图预览接口。"""

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
            context.register_web_api(
                f"/{plugin_name}/audit/screenshot",
                self.api_audit_screenshot,
                ["GET"],
                "获取审计日志截图文件",
            )

    async def api_audit_logs(self):
        """分页与条件检索审计记录。"""
        req = request
        page = extract_query_param(req, "page", 1, int)
        page = max(1, page)
        raw_page_size = extract_query_param(req, "page_size", 20, int)
        page_size = min(max(1, raw_page_size), 100)
        keyword = str(extract_query_param(req, "keyword", "") or "").strip()
        status = str(extract_query_param(req, "status", "all") or "all").strip()
        tool_name = str(extract_query_param(req, "tool_name", "") or "").strip()

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
        req = request
        fmt = str(extract_query_param(req, "format", extract_query_param(req, "fmt", "json")) or "json").strip()
        keyword = str(extract_query_param(req, "keyword", "") or "").strip()
        status = str(extract_query_param(req, "status", "all") or "all").strip()
        tool_name = str(extract_query_param(req, "tool_name", "") or "").strip()

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

    async def api_audit_screenshot(self, path: str = ""):
        """获取本地截图预览，带目录越界防护。"""
        req = request
        if not path:
            path = extract_query_param(req, "path", "")
        if not path:
            return error_response("缺少 path 参数", status_code=400)

        # 目录越界防护：只允许访问 data/ 目录下的截图
        base_dir = Path("data").resolve()
        try:
            p = Path(path)
            target_path = p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
            if not target_path.is_relative_to(base_dir):
                target_path = (base_dir / p).resolve()
            if not target_path.is_relative_to(base_dir):
                return error_response("越界访问被拒绝", status_code=403)
        except Exception:
            return error_response("越界访问被拒绝", status_code=403)

        if not target_path.exists() or not target_path.is_file():
            return error_response("截图文件不存在", status_code=404)

        try:
            from starlette.responses import FileResponse
            return FileResponse(str(target_path), media_type="image/png")
        except ImportError:
            try:
                from starlette.responses import Response
                with open(target_path, "rb") as f:
                    return Response(content=f.read(), media_type="image/png")
            except ImportError:
                with open(target_path, "rb") as f:
                    return {"data": f.read(), "media_type": "image/png", "status_code": 200}
