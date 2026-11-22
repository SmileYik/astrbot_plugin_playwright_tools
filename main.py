import json
import asyncio
import time
import atexit
from typing import Any
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

PLUGIN_NAME = "astrbot_plugin_playwright_tools"

from .api.audit_api import AuditApiHandler
from .api.lifecycle_api import LifecycleApiHandler

from .core.audit_logger import AuditLogger
from .core.security_manager import SecurityManager
from .core.readers import InlineMarkdownReader, AriaSnapshotReader
from .core.context_manager import ContextManager
from .core.service_api import PlaywrightServiceAPI
from .adapts.factory import AdapterFactory

from .tools.handlers.page_handler import PageHandler
from .tools.handlers.interact_handler import InteractHandler
from .tools.handlers.media_handler import MediaHandler
from .tools.tools import PwPageTool, PwReadTool, PwInteractTool, PwMediaTool

@register(
    "PlaywrightTool",
    "SmileYik",
    "给大模型用的网页浏览器插件。支持打开网页、阅读文章与点击填表。采用元素编号避免乱点并减少 Token 消耗，同时自带防网站拦截与后台管理控制台。",
    "v1.2.0"
)
class PlaywrightToolPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}

        # 1. 解析业务分组配置（支持原生分组读取及简写平退回退）
        sec_cfg = self.config.get("security", {}) if isinstance(self.config.get("security"), dict) else {}
        rt_cfg = self.config.get("runtime", {}) if isinstance(self.config.get("runtime"), dict) else {}
        med_cfg = self.config.get("media", {}) if isinstance(self.config.get("media"), dict) else {}
        store_cfg = self.config.get("storage_audit", {}) if isinstance(self.config.get("storage_audit"), dict) else {}

        # 安全与权限
        admin_only = bool(sec_cfg.get("admin_only", self.config.get("admin_only", False)))
        extra_admins_raw = sec_cfg.get("extra_admin_uids", self.config.get("extra_admin_uids", []))
        if isinstance(extra_admins_raw, list):
            extra_admins = [str(u).strip() for u in extra_admins_raw if str(u).strip()]
        else:
            extra_admins = [u.strip() for u in str(extra_admins_raw).split(",") if u.strip()]

        raw_rules = sec_cfg.get("whitelist_rules", self.config.get("whitelist_rules", []))
        if isinstance(raw_rules, str):
            try:
                whitelist_rules = json.loads(raw_rules)
            except Exception:
                whitelist_rules = []
        else:
            whitelist_rules = list(raw_rules)

        storage_state_path = str(sec_cfg.get("storage_state_path", self.config.get("storage_state_path", "")))
        self.mask_password_inputs = bool(sec_cfg.get("mask_password_inputs", self.config.get("mask_password_inputs", True)))

        # 会话与运行时
        context_mode = str(rt_cfg.get("context_mode", self.config.get("context_mode", "personal")))
        idle_timeout = int(rt_cfg.get("idle_timeout_minutes", self.config.get("idle_timeout_minutes", 10)))
        browser_idle_timeout = int(rt_cfg.get("browser_idle_timeout_minutes", self.config.get("browser_idle_timeout_minutes", 5)))
        tool_timeout = int(rt_cfg.get("tool_execution_timeout_seconds", self.config.get("tool_execution_timeout_seconds", 30)))
        enable_close_tool = bool(rt_cfg.get("enable_close_tool", self.config.get("enable_close_tool", True)))
        self.system_prompt_injection = str(rt_cfg.get("system_prompt_injection", self.config.get("system_prompt_injection", ""))).strip()
        self.content_extraction_mode = str(rt_cfg.get("content_extraction_mode", self.config.get("content_extraction_mode", "inline_markdown"))).strip().lower()
        self.page_chunk_char_limit = int(rt_cfg.get("page_chunk_char_limit", self.config.get("page_chunk_char_limit", 2000)))

        # 截图与多媒体
        screenshot_format = str(med_cfg.get("screenshot_format", self.config.get("screenshot_format", "png"))).lower()
        screenshot_quality = int(med_cfg.get("screenshot_quality", self.config.get("screenshot_quality", 80)))
        screenshot_max_height = int(med_cfg.get("screenshot_max_height_px", self.config.get("screenshot_max_height_px", 8000)))
        screenshot_timeout = int(med_cfg.get("screenshot_timeout_seconds", self.config.get("screenshot_timeout_seconds", 15)))
        allow_screenshot_to_ai = bool(med_cfg.get("allow_screenshot_to_ai", self.config.get("allow_screenshot_to_ai", False)))
        element_multiline_separator = str(med_cfg.get("element_multiline_separator", self.config.get("element_multiline_separator", " | ")))

        # 存储与审计
        self.download_save_path = str(store_cfg.get("download_save_path", self.config.get("download_save_path", "data/plugin_data/astrbot_plugin_playwright_tools/downloads")))
        self.screenshot_save_path = str(store_cfg.get("screenshot_save_path", self.config.get("screenshot_save_path", "data/plugin_data/astrbot_plugin_playwright_tools/screenshots")))
        file_retention_days = int(store_cfg.get("file_retention_days", self.config.get("file_retention_days", 7)))
        retention_days = int(store_cfg.get("audit_retention_days", self.config.get("audit_retention_days", 30)))
        audit_max_output_chars = int(store_cfg.get("audit_max_output_chars", self.config.get("audit_max_output_chars", 0)))
        audit_save_screenshots = bool(store_cfg.get("audit_save_screenshots", self.config.get("audit_save_screenshots", True)))

        # 2. 初始化核心服务与阅读器
        self.audit_db_path = str(self.config.get("audit_db_path", "data/plugin_data/astrbot_plugin_playwright_tools/audit.db"))
        self.audit_logger = AuditLogger(self.audit_db_path, max_output_chars=audit_max_output_chars)
        self.security_manager = SecurityManager(
            admin_only=admin_only,
            admin_uids=extra_admins,
            whitelist_rules=whitelist_rules,
            admin_bypass=True,
        )
        if self.content_extraction_mode == "aria_snapshot":
            self.reader = AriaSnapshotReader(
                chunk_char_limit=self.page_chunk_char_limit,
                mask_passwords=self.mask_password_inputs,
            )
        else:
            self.reader = InlineMarkdownReader(
                chunk_char_limit=self.page_chunk_char_limit,
                mask_passwords=self.mask_password_inputs,
            )
        self.adapter = AdapterFactory.create(self.config)
        self.context_manager = ContextManager(
            adapter=self.adapter,
            security=self.security_manager,
            mode=context_mode,
            idle_timeout_minutes=idle_timeout,
            storage_state_path=storage_state_path,
            audit_logger=self.audit_logger,
            browser_idle_timeout_minutes=browser_idle_timeout,
        )

        try:
            atexit.register(self._atexit_cleanup)
        except Exception as e:
            logger.debug(f"[PlaywrightTool] 注册 atexit 钩子异常: {e}")

        # 3. 初始化模块化 Handlers 与复合 FunctionTool
        self.page_handler = PageHandler(
            self.context_manager,
            self.security_manager,
            self.audit_logger,
            reader=self.reader,
            enable_close_tool=enable_close_tool,
            mask_password_inputs=self.mask_password_inputs,
        )
        self.interact_handler = InteractHandler(
            self.context_manager,
            self.security_manager,
            self.audit_logger,
            mask_password_inputs=self.mask_password_inputs,
        )
        self.media_handler = MediaHandler(
            self.context_manager,
            self.security_manager,
            self.audit_logger,
            allow_screenshot_to_ai=allow_screenshot_to_ai,
            download_dir=self.download_save_path,
            audit_save_screenshots=audit_save_screenshots,
            screenshot_format=screenshot_format,
            screenshot_quality=screenshot_quality,
            screenshot_dir=self.screenshot_save_path,
            file_retention_days=file_retention_days,
            mask_password_inputs=self.mask_password_inputs,
        )

        self.pw_page_tool = PwPageTool(page_handler=self.page_handler, timeout_seconds=tool_timeout)
        self.pw_read_tool = PwReadTool(page_handler=self.page_handler, timeout_seconds=tool_timeout)
        self.pw_interact_tool = PwInteractTool(interact_handler=self.interact_handler, timeout_seconds=tool_timeout)
        self.pw_media_tool = PwMediaTool(
            media_handler=self.media_handler,
            timeout_seconds=tool_timeout,
            screenshot_max_height_px=screenshot_max_height,
            screenshot_timeout_seconds=screenshot_timeout,
        )

        # 4. 面向对象注册 FunctionTool
        if hasattr(self.context, "add_llm_tools"):
            self.context.add_llm_tools(self.pw_page_tool, self.pw_read_tool, self.pw_interact_tool, self.pw_media_tool)

        # 5. 初始化并注册 Web API 模块
        self.audit_api = AuditApiHandler(self.audit_logger)
        self.audit_api.register_routes(self.context, PLUGIN_NAME)

        self.lifecycle_api = LifecycleApiHandler(
            self.context_manager, self.audit_logger, self.media_handler
        )
        self.lifecycle_api.register_routes(self.context, PLUGIN_NAME)

        # 兼容委托供历史引用使用
        self.api_audit_logs = self.audit_api.api_audit_logs
        self.api_audit_stats = self.audit_api.api_audit_stats
        self.api_audit_export = self.audit_api.api_audit_export
        self.api_audit_clear = self.audit_api.api_audit_clear

        self._retention_days = retention_days
        self._cleanup_task: asyncio.Task | None = None

        # 6. 初始化跨插件浏览器共享服务基座
        self.service = PlaywrightServiceAPI(self, self.context_manager)

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
        except Exception as e:
            logger.debug(f"[PlaywrightTool] 同步事件管理员标识失败: {e}")

    def _atexit_cleanup(self) -> None:
        """解释器退出时的尽力而为兜底钩子。"""
        try:
            if hasattr(self, "adapter") and getattr(self.adapter, "is_running", False):
                logger.warning("[PlaywrightTool] 检测到 Python 解释器退出时底层浏览器仍处于运行状态")
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

        self.service.set_ready()
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup_loop())

    async def _periodic_cleanup_loop(self):
        """每隔 30 秒轮询清理空闲超时上下文、无上下文浏览器进程与超期审计记录。"""
        last_audit_clean_time = 0.0
        while True:
            try:
                await asyncio.sleep(30)
                closed = await self.context_manager.cleanup_idle_contexts()
                browser_stopped = await self.context_manager.check_and_cleanup_idle_browser()
                now = time.time()
                cleaned = 0
                if now - last_audit_clean_time > 3600:
                    cleaned = await self.audit_logger.cleanup_expired(self._retention_days)
                    last_audit_clean_time = now

                if closed > 0 or browser_stopped or cleaned > 0:
                    status_parts = []
                    if closed > 0:
                        status_parts.append(f"释放 {closed} 个空闲上下文")
                    if browser_stopped:
                        status_parts.append("回收底层浏览器进程")
                    if cleaned > 0:
                        status_parts.append(f"清理 {cleaned} 条过期日志")
                    logger.info(f"[PlaywrightTool] 周期清理: {', '.join(status_parts)}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[PlaywrightTool] 周期清理轮询异常: {e}")

    # ==================== 用户管理指令 ====================

    @filter.command("browser")
    async def browser_cmd(self, event: AstrMessageEvent, sub_cmd: str = "", arg: str = ""):
        """浏览器插件指令管理。用法: /browser <invite|use|close|status|list|list-all|kill> [参数]"""
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

        elif sub_cmd == "list":
            contexts = await self.context_manager.get_active_contexts_detail()
            filtered = [c for c in contexts if c.get("session_id") == session_id]
            if not filtered:
                yield event.plain_result("当前会话暂无活跃的浏览器上下文。")
                return
            lines = [f"【当前会话活跃浏览器】\n共 {len(filtered)} 个活跃上下文:"]
            for idx, c in enumerate(filtered, 1):
                key = c.get("context_key", "")
                owner = c.get("owner_id", "")
                allowed = ", ".join(str(u) for u in c.get("allowed_users", []))
                tab_cnt = c.get("tab_count", 0)
                cur_url = c.get("active_tab_url", "") or "空白页"
                lines.append(f"{idx}. Key: {key} | 所有者: {owner} | 协作者: {allowed} | 标签页数: {tab_cnt} | 当前: {cur_url}")
            yield event.plain_result("\n".join(lines))

        elif sub_cmd == "list-all":
            if not self.security_manager.is_admin(sender_id):
                yield event.plain_result("无权限：仅管理员可查看全部会话的活跃上下文。")
                return
            contexts = await self.context_manager.get_active_contexts_detail()
            if not contexts:
                yield event.plain_result("全平台暂无活跃的浏览器上下文。")
                return
            lines = [f"【全平台活跃浏览器】\n共 {len(contexts)} 个活跃上下文:"]
            for idx, c in enumerate(contexts, 1):
                key = c.get("context_key", "")
                sess = c.get("session_id", "")
                owner = c.get("owner_id", "")
                allowed = ", ".join(str(u) for u in c.get("allowed_users", []))
                tab_cnt = c.get("tab_count", 0)
                cur_url = c.get("active_tab_url", "") or "空白页"
                lines.append(f"{idx}. Key: {key} (会话: {sess}) | 所有者: {owner} | 协作者: {allowed} | 标签页数: {tab_cnt} | 当前: {cur_url}")
            yield event.plain_result("\n".join(lines))

        elif sub_cmd == "kill":
            if not self.security_manager.is_admin(sender_id):
                yield event.plain_result("无权限：仅管理员可强行关闭上下文。")
                return
            target_key = arg.strip()
            if not target_key:
                yield event.plain_result("请提供要关闭的 context_key，例如: /browser kill default:123456:admin")
                return
            ok, msg = await self.context_manager.force_kill_context(target_key, operator_id=sender_id)
            yield event.plain_result(msg)

        else:
            yield event.plain_result(
                "浏览器指令帮助:\n"
                "- /browser invite <UID/@用户> : 邀请用户协作当前浏览器\n"
                "- /browser use <UID/@用户> : 切换当前操作的浏览器目标\n"
                "- /browser close : 关闭释放自己开启的浏览器\n"
                "- /browser status : 查看当前浏览器状态\n"
                "- /browser list : 查看当前会话活跃的浏览器列表\n"
                "- /browser list-all : 查看全平台活跃的浏览器列表(仅管理员)\n"
                "- /browser kill <context_key> : 强行关闭指定浏览器上下文(仅管理员)"
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


    async def terminate(self):
        """插件销毁释放所有浏览器资源及取消轮询清理任务。"""
        try:
            import atexit
            atexit.unregister(self._atexit_cleanup)
        except Exception as e:
            logger.debug(f"[PlaywrightTool] 注销 atexit 钩子异常: {e}")

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        try:
            closed_count = await self.context_manager.close_all_contexts(reason="terminate")
            try:
                stop_res = self.adapter.stop()
                if hasattr(stop_res, "__await__"):
                    await asyncio.wait_for(stop_res, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("[PlaywrightTool] 停止浏览器适配器超时(5s)，强制释放句柄")
            logger.info(f"[PlaywrightTool] 插件重载/终止完成，共清理 {closed_count} 个存量上下文并停止浏览器进程")
        except Exception as e:
            logger.error(f"[PlaywrightTool] 终止释放异常: {e}")
