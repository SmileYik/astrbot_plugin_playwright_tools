import os
import time
import uuid
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

from astrbot.api import logger

from .audit_api import extract_query_param


async def _extract_request_payload(req: Any) -> dict:
    """从 Web 请求对象中安全异步提取 JSON 或 Form 表单负载。"""
    payload: dict = {}
    if req is None:
        return payload

    if hasattr(req, "json") and callable(req.json):
        try:
            res = req.json()
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, dict):
                payload.update(res)
        except Exception as e:
            logger.debug(f"[LifecycleApi] 异步提取请求 JSON 负载异常: {e}")

    if hasattr(req, "form") and callable(req.form):
        try:
            res = req.form()
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, dict):
                payload.update(res)
        except Exception as e:
            logger.debug(f"[LifecycleApi] 异步提取请求 Form 负载异常: {e}")

    return payload


class LifecycleApiHandler:
    """会话生命周期 Web API 处理模块，负责向前端提供活跃会话查询、生命周期日志检索、手动截图与强制销毁接口。"""

    def __init__(self, context_mgr: Any, audit_logger: Any, media_handler: Any = None):
        self.context_mgr = context_mgr
        self.audit_logger = audit_logger
        self.media_handler = media_handler

    def register_routes(self, context: Any, plugin_name: str) -> None:
        """向 AstrBot 上下文注册生命周期 Web API 路由。"""
        if hasattr(context, "register_web_api") and callable(context.register_web_api):
            context.register_web_api(
                f"/{plugin_name}/lifecycle/active",
                self.api_active_contexts,
                ["GET"],
                "获取活跃浏览器上下文及标签页明细",
            )
            context.register_web_api(
                f"/{plugin_name}/lifecycle/logs",
                self.api_lifecycle_logs,
                ["GET"],
                "获取浏览器生命周期审计日志",
            )
            context.register_web_api(
                f"/{plugin_name}/lifecycle/screenshot",
                self.api_manual_screenshot,
                ["POST"],
                "对指定上下文标签页执行手动截图",
            )
            context.register_web_api(
                f"/{plugin_name}/lifecycle/kill",
                self.api_force_kill,
                ["POST"],
                "强制销毁指定浏览器上下文",
            )

    async def api_active_contexts(self):
        """获取所有当前活跃的会话及其标签页明细。"""
        active_items = []
        if hasattr(self.context_mgr, "get_active_contexts_detail"):
            res = self.context_mgr.get_active_contexts_detail()
            if hasattr(res, "__await__"):
                active_items = await res
            elif isinstance(res, list):
                active_items = res

        return json_response({
            "items": active_items,
            "total": len(active_items),
        })

    async def api_lifecycle_logs(
        self,
        page: int = 1,
        page_size: int = 20,
        session_id: str = "",
        event_type: str = "",
        keyword: str = "",
    ):
        """分页与多条件查询生命周期审计记录。"""
        req = request
        if req is not None:
            page = extract_query_param(req, "page", page, int)
            page_size = extract_query_param(req, "page_size", page_size, int)
            session_id = str(extract_query_param(req, "session_id", session_id) or "")
            event_type = str(extract_query_param(req, "event_type", event_type) or "")
            keyword = str(extract_query_param(req, "keyword", keyword) or "")

        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        session_id = session_id.strip()
        event_type = event_type.strip()
        keyword = keyword.strip()

        logs, total = [], 0
        if self.audit_logger and hasattr(self.audit_logger, "query_lifecycle_logs"):
            res = self.audit_logger.query_lifecycle_logs(
                page=page,
                page_size=page_size,
                session_id=session_id,
                event_type=event_type,
                keyword=keyword,
            )
            if hasattr(res, "__await__"):
                logs, total = await res
            elif isinstance(res, tuple) and len(res) == 2:
                logs, total = res

        return json_response({
            "items": logs,
            "total": total,
            "page": page,
            "page_size": page_size,
        })

    async def api_manual_screenshot(self, context_key: str = "", tab_index: int | None = None):
        """对指定上下文的指定标签页手动截图并落盘、记录审计日志。"""
        req = request
        payload = await _extract_request_payload(req)

        key = payload.get("context_key") or extract_query_param(req, "context_key", "") or context_key
        if not key:
            return error_response("缺少 context_key 参数", status_code=400)

        tab_idx_val = payload.get("tab_index", extract_query_param(req, "tab_index", tab_index))
        tab_idx = None
        if tab_idx_val is not None:
            try:
                tab_idx = int(tab_idx_val)
            except (ValueError, TypeError):
                tab_idx = None

        target_ctx = None
        target_fmt_key = str(key)
        contexts = getattr(self.context_mgr, "contexts", {})
        for k, ctx in list(contexts.items()):
            fmt = self.context_mgr._format_context_key(k) if hasattr(self.context_mgr, "_format_context_key") else str(k)
            if k == key or fmt == key or str(k) == str(key):
                target_ctx = ctx
                target_fmt_key = fmt
                break

        if target_ctx is None:
            return error_response(f"未找到上下文: {key}", status_code=404)

        pages = []
        if hasattr(target_ctx, "browser_context") and getattr(target_ctx.browser_context, "pages", None) is not None:
            bc_pages = target_ctx.browser_context.pages
            if isinstance(bc_pages, list):
                pages = bc_pages
        if not pages and hasattr(target_ctx, "pages") and isinstance(target_ctx.pages, list):
            pages = target_ctx.pages

        target_page = None
        if tab_idx is not None and 0 <= tab_idx < len(pages):
            target_page = pages[tab_idx]
        else:
            target_page = getattr(target_ctx, "current_page", None) or (pages[0] if pages else None)

        if not target_page:
            return error_response("目标上下文中无可用页面", status_code=404)

        shot_opts = {}
        if self.media_handler and hasattr(self.media_handler, "_get_screenshot_options"):
            shot_opts = self.media_handler._get_screenshot_options()
        elif self.media_handler and getattr(self.media_handler, "screenshot_format", "") in ("jpeg", "jpg"):
            shot_opts = {"type": "jpeg", "quality": getattr(self.media_handler, "screenshot_quality", 80)}
        else:
            shot_opts = {"type": "png"}

        screenshot_dir = getattr(self.media_handler, "screenshot_dir", "data/screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        ext = ".jpg" if shot_opts.get("type") in ("jpeg", "jpg") else ".png"
        file_name = f"manual_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{ext}"
        save_path = os.path.join(screenshot_dir, file_name).replace("\\", "/")

        try:
            shot_res = target_page.screenshot(path=save_path, full_page=False, **shot_opts)
            if hasattr(shot_res, "__await__"):
                image_bytes = await shot_res
            else:
                image_bytes = shot_res

            if isinstance(image_bytes, bytes):
                with open(save_path, "wb") as f:
                    f.write(image_bytes)
            elif not os.path.exists(save_path):
                with open(save_path, "wb") as f:
                    f.write(b"")
        except Exception as e:
            return error_response(f"手动截图执行失败: {e}", status_code=500)

        if self.audit_logger and hasattr(self.audit_logger, "log_action"):
            url = getattr(target_page, "url", "")
            if callable(url):
                url = url()
            url = str(url) if url else ""

            session_id = getattr(target_ctx, "session_id", "")
            owner_id = getattr(target_ctx, "owner_id", "")
            log_res = self.audit_logger.log_action(
                session_id=session_id,
                context_key=target_fmt_key,
                sender_id=owner_id or "web_admin",
                tool_name="manual_screenshot",
                url=url,
                input_args={"tab_index": tab_idx, "context_key": key},
                output_result=f"[IMAGE_PATH:{save_path}]",
                is_permitted=True,
                screenshot_path=save_path,
            )
            if hasattr(log_res, "__await__"):
                await log_res

        return json_response({"code": 0, "data": {"screenshot_path": save_path}})

    async def api_force_kill(self, context_key: str = "", operator_id: str = "web_admin"):
        """强制销毁指定浏览器上下文并释放底层资源。"""
        req = request
        payload = await _extract_request_payload(req)

        key = payload.get("context_key") or extract_query_param(req, "context_key", "") or context_key
        if not key:
            return error_response("缺少 context_key 参数", status_code=400)

        op_id = payload.get("operator_id") or extract_query_param(req, "operator_id", "") or operator_id or "web_admin"

        if not hasattr(self.context_mgr, "force_kill_context"):
            return error_response("ContextManager 不支持 force_kill_context", status_code=500)

        res = self.context_mgr.force_kill_context(key, op_id)
        if hasattr(res, "__await__"):
            ok, msg = await res
        else:
            ok, msg = res

        if ok:
            return json_response({"code": 0, "data": {"message": msg}})
        else:
            return error_response(msg, status_code=400)
