import json
import asyncio
from typing import Any
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

try:
    from astrbot.api.web import json_response, request, error_response
except ImportError:
    def json_response(data, status_code=200, headers=None):
        return {"data": data, "status_code": status_code}
    def error_response(msg, status_code=400, data=None):
        return {"error": msg, "status_code": status_code, "data": data}
    request = None

PLUGIN_NAME = "astrbot_plugin_playwright_tools"

from core.audit_logger import AuditLogger
from core.security_manager import SecurityManager
from core.page_extractor import PageExtractor
from core.context_manager import ContextManager
from adapts.camoufox_adapter import CamoufoxAdapter

from tools.handlers.page_handler import PageHandler
from tools.handlers.interact_handler import InteractHandler
from tools.handlers.media_handler import MediaHandler
from tools.tools import PwPageTool, PwInteractTool, PwMediaTool

@register(
    "PlaywrightTool",
    "SmileYik",
    "基于 Playwright 的大模型网页自动化工具插件，支持多租户隔离与权限白名单。",
    "v2.1.0"
)
class PlaywrightToolPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}

        # 1. 解析配置
        admin_only = bool(self.config.get("admin_only", False))
        extra_admins_raw = str(self.config.get("extra_admin_uids", ""))
        extra_admins = [u.strip() for u in extra_admins_raw.split(",") if u.strip()]

        raw_rules = self.config.get("whitelist_rules", "[]")
        if isinstance(raw_rules, str):
            try:
                whitelist_rules = json.loads(raw_rules)
            except Exception:
                whitelist_rules = []
        else:
            whitelist_rules = list(raw_rules)

        allow_screenshot_to_ai = bool(self.config.get("allow_screenshot_to_ai", False))
        enable_close_tool = bool(self.config.get("enable_close_tool", True))
        context_mode = str(self.config.get("context_mode", "personal"))
        idle_timeout = int(self.config.get("idle_timeout_minutes", 10))
        storage_state_path = str(self.config.get("storage_state_path", ""))
        retention_days = int(self.config.get("audit_retention_days", 30))

        tool_timeout = int(self.config.get("tool_execution_timeout_seconds", 30))
        screenshot_max_height = int(self.config.get("screenshot_max_height_px", 8000))
        screenshot_timeout = int(self.config.get("screenshot_timeout_seconds", 15))
        self.system_prompt_injection = str(self.config.get("system_prompt_injection", "")).strip()

        # 2. 初始化核心服务
        audit_db_path = str(self.config.get("audit_db_path", "data/audit.db"))
        self.audit_logger = AuditLogger(audit_db_path)
        self.security_manager = SecurityManager(
            admin_only=admin_only,
            admin_uids=extra_admins,
            whitelist_rules=whitelist_rules,
            admin_bypass=True,
        )
        self.page_extractor = PageExtractor(max_page_char_length=2500)
        self.adapter = CamoufoxAdapter(headless=True)
        self.context_manager = ContextManager(
            adapter=self.adapter,
            security=self.security_manager,
            mode=context_mode,
            idle_timeout_minutes=idle_timeout,
            storage_state_path=storage_state_path,
        )

        # 3. 初始化模块化 Handlers 与复合 FunctionTool
        self.page_handler = PageHandler(
            self.context_manager,
            self.security_manager,
            self.audit_logger,
            self.page_extractor,
            enable_close_tool=enable_close_tool,
        )
        self.interact_handler = InteractHandler(
            self.context_manager, self.security_manager, self.audit_logger
        )
        self.media_handler = MediaHandler(
            self.context_manager,
            self.security_manager,
            self.audit_logger,
            allow_screenshot_to_ai=allow_screenshot_to_ai,
            download_dir="data/downloads",
        )

        self.pw_page_tool = PwPageTool(page_handler=self.page_handler, timeout_seconds=tool_timeout)
        self.pw_interact_tool = PwInteractTool(interact_handler=self.interact_handler, timeout_seconds=tool_timeout)
        self.pw_media_tool = PwMediaTool(
            media_handler=self.media_handler,
            timeout_seconds=tool_timeout,
            screenshot_max_height_px=screenshot_max_height,
            screenshot_timeout_seconds=screenshot_timeout,
        )

        # 4. 面向对象注册 FunctionTool
        if hasattr(self.context, "add_llm_tools"):
            self.context.add_llm_tools(self.pw_page_tool, self.pw_interact_tool, self.pw_media_tool)

        # 5. 注册 Web API 路由
        if hasattr(self.context, "register_web_api"):
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/audit/logs",
                self.api_audit_logs,
                ["GET"],
                "获取审计日志列表",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/audit/stats",
                self.api_audit_stats,
                ["GET"],
                "获取审计日志统计数据",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/audit/export",
                self.api_audit_export,
                ["GET"],
                "导出审计日志数据",
            )
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/audit/clear",
                self.api_audit_clear,
                ["POST"],
                "清空审计日志数据",
            )

        self._retention_days = retention_days
        self._cleanup_task: asyncio.Task | None = None

    def _sync_event_admin(self, event: AstrMessageEvent) -> None:
        """从当前消息事件中提取并动态同步全局管理员标识。"""
        try:
            sender_id = str(event.get_sender_id())
            is_admin = False
            if hasattr(event, "is_admin") and callable(event.is_admin):
                is_admin = bool(event.is_admin())
            elif hasattr(event, "role") and str(event.role).lower() in ("admin", "owner"):
                is_admin = True

            if is_admin:
                self.security_manager.admin_uids.add(sender_id)
        except Exception:
            pass

    async def initialize(self):
        """插件初始化，启动过期审计数据清理与空闲定时回收任务。"""
        try:
            cleaned = await self.audit_logger.cleanup_expired(self._retention_days)
            if cleaned > 0:
                logger.info(f"[PlaywrightTool] 已清理 {cleaned} 条过期审计日志")
        except Exception as e:
            logger.warning(f"[PlaywrightTool] 审计日志清理失败: {e}")

        self._cleanup_task = asyncio.create_task(self._periodic_cleanup_loop())

    async def _periodic_cleanup_loop(self):
        """每隔 5 分钟轮询清理空闲超时上下文与超期审计记录。"""
        while True:
            try:
                await asyncio.sleep(300)
                closed = await self.context_manager.cleanup_idle_contexts()
                cleaned = await self.audit_logger.cleanup_expired(self._retention_days)
                if closed > 0 or cleaned > 0:
                    logger.info(f"[PlaywrightTool] 周期清理: 释放 {closed} 个空闲上下文，清理 {cleaned} 条过期日志")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[PlaywrightTool] 周期清理轮询异常: {e}")

    # ==================== 用户管理指令 ====================

    @filter.command("browser")
    async def browser_cmd(self, event: AstrMessageEvent, sub_cmd: str = "", arg: str = ""):
        """浏览器插件指令管理。用法: /browser <invite|use|close|status> [参数]"""
        self._sync_event_admin(event)
        session_id = event.session_id
        sender_id = str(event.get_sender_id())
        sub_cmd = sub_cmd.strip().lower()

        if sub_cmd == "invite":
            target_uid = arg.replace("@", "").strip()
            if not target_uid:
                yield event.plain_result("请提供被邀请用户的 UID 或 @用户，例如: /browser invite 123456")
                return
            ok, msg = self.context_manager.invite_user(session_id, sender_id, target_uid)
            yield event.plain_result(msg)

        elif sub_cmd == "use":
            target_owner = arg.replace("@", "").strip()
            if not target_owner:
                yield event.plain_result("请指定目标所有者的 UID 或 @用户，例如: /browser use 123456")
                return
            ok, msg = self.context_manager.switch_user_context(session_id, sender_id, target_owner)
            yield event.plain_result(msg)

        elif sub_cmd == "close":
            ok, msg = await self.context_manager.close_user_context(session_id, sender_id)
            yield event.plain_result(msg)

        elif sub_cmd == "status":
            ctx, hint = await self.context_manager.resolve_context(session_id, sender_id, peek=True)
            if ctx:
                pages_cnt = len(ctx.browser_context.pages)
                cur_url = getattr(ctx.current_page, "url", "空白页")
                yield event.plain_result(
                    f"【当前浏览器上下文状态】\n"
                    f"所有者: {ctx.owner_id}\n"
                    f"协作者: {', '.join(ctx.allowed_users)}\n"
                    f"当前网页: {cur_url}\n"
                    f"标签页数: {pages_cnt}\n"
                    f"提示: {hint or '当前操作本人的浏览器'}"
                )
            else:
                yield event.plain_result("当前未创建活跃的浏览器上下文。如需开启，请让大模型执行浏览操作。")
        else:
            yield event.plain_result(
                "浏览器指令帮助:\n"
                "- /browser invite <UID/@用户> : 邀请用户协作当前浏览器\n"
                "- /browser use <UID/@用户> : 切换当前操作的浏览器目标\n"
                "- /browser close : 关闭释放自己开启的浏览器\n"
                "- /browser status : 查看当前浏览器状态"
            )

    # ==================== 大模型请求系统提示词注入 ====================

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: Any):
        """在向大模型发起请求前同步管理员标识，并在配置了系统提示词时进行动态追加注入。"""
        self._sync_event_admin(event)
        if not self.system_prompt_injection:
            return
        if hasattr(req, "system_prompt"):
            if req.system_prompt:
                req.system_prompt = f"{req.system_prompt}\n\n{self.system_prompt_injection}"
            else:
                req.system_prompt = self.system_prompt_injection

    # ==================== 后端 Web API ====================

    async def api_audit_logs(self):
        """分页与条件检索审计记录。"""
        page = 1
        page_size = 20
        keyword = ""
        status = "all"
        tool_name = ""

        if request and hasattr(request, "query"):
            try:
                page = int(request.query.get("page", 1))
            except (ValueError, TypeError):
                page = 1
            try:
                page_size = int(request.query.get("page_size", 20))
            except (ValueError, TypeError):
                page_size = 20
            keyword = str(request.query.get("keyword", "") or "").strip()
            status = str(request.query.get("status", "all") or "all").strip()
            tool_name = str(request.query.get("tool_name", "") or "").strip()

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

        if request and hasattr(request, "query"):
            fmt = str(request.query.get("format", request.query.get("fmt", "json")) or "json").strip()
            keyword = str(request.query.get("keyword", "") or "").strip()
            status = str(request.query.get("status", "all") or "all").strip()
            tool_name = str(request.query.get("tool_name", "") or "").strip()

        content = await self.audit_logger.export_logs(
            fmt=fmt, keyword=keyword, status=status, tool_name=tool_name
        )
        return json_response({"code": 0, "data": content, "format": fmt})

    async def api_audit_clear(self):
        """清空历史审计记录。"""
        confirm = False
        if request and hasattr(request, "json") and callable(request.json):
            try:
                payload = await request.json(default={})
                if isinstance(payload, dict):
                    confirm = bool(payload.get("confirm", False))
            except Exception:
                confirm = False

        if not confirm:
            return json_response({"code": -1, "message": "清空操作需要确认参数 confirm=true"}, status_code=400)

        cleared = await self.audit_logger.clear_logs()
        return json_response({"code": 0, "data": {"cleared": cleared}})

    async def terminate(self):
        """插件销毁释放所有浏览器资源及取消轮询清理任务。"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        try:
            for ctx in list(self.context_manager.contexts.values()):
                try:
                    await ctx.browser_context.close()
                except Exception:
                    pass
            await self.adapter.stop()
            logger.info("[PlaywrightTool] 已完全释放所有浏览器资源")
        except Exception as e:
            logger.error(f"[PlaywrightTool] 终止释放异常: {e}")
