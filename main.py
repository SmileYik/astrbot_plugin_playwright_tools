import json
import asyncio
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

from core.audit_logger import AuditLogger
from core.security_manager import SecurityManager
from core.page_extractor import PageExtractor
from core.context_manager import ContextManager
from adapts.camoufox_adapter import CamoufoxAdapter
from tools.browse_tools import BrowseTools
from tools.action_tools import ActionTools
from tools.media_tools import MediaTools
from tools.dialog_tools import DialogTools

@register(
    "PlaywrightTool",
    "SmileYik",
    "基于 Playwright 的大模型网页自动化工具插件，支持多租户隔离与权限白名单。",
    "v1.0.0"
)
class PlaywrightToolPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
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
        context_mode = str(self.config.get("context_mode", "personal"))
        idle_timeout = int(self.config.get("idle_timeout_minutes", 10))
        storage_state_path = str(self.config.get("storage_state_path", ""))
        retention_days = int(self.config.get("audit_retention_days", 30))

        # 2. 初始化核心服务
        self.audit_logger = AuditLogger("data/audit.db")
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

        # 3. 初始化工具集
        self.browse_tools = BrowseTools(
            self.context_manager, self.security_manager, self.audit_logger, self.page_extractor
        )
        self.action_tools = ActionTools(
            self.context_manager, self.security_manager, self.audit_logger
        )
        self.media_tools = MediaTools(
            self.context_manager, self.security_manager, self.audit_logger,
            allow_screenshot_to_ai=allow_screenshot_to_ai, download_dir="data/downloads"
        )
        self.dialog_tools = DialogTools(
            self.context_manager, self.security_manager, self.audit_logger
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

        # 启动周期性空闲资源与过期日志清理后台任务
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

    # ==================== 用户指令 ====================

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

    # ==================== 大模型工具 (LLM Tools) ====================

    @filter.llm_tool(name="open_url")
    async def open_url(self, event: AstrMessageEvent, url: str) -> MessageEventResult:
        """打开目标网页并返回提取后的页面元素快照与 Ref ID 编号。

        Args:
            url(string): 目标网页 URL (包含 http:// 或 https://)
        """
        self._sync_event_admin(event)
        res = await self.browse_tools.open_url(event.session_id, str(event.get_sender_id()), url)
        yield event.plain_result(res)

    @filter.llm_tool(name="read_page")
    async def read_page(self, event: AstrMessageEvent, page: int = 1) -> MessageEventResult:
        """读取当前页面的内容快照，支持指定分页查看长页面后续内容。

        Args:
            page(number): 页码编号 (从 1 开始)
        """
        self._sync_event_admin(event)
        res = await self.browse_tools.read_page(event.session_id, str(event.get_sender_id()), int(page))
        yield event.plain_result(res)

    @filter.llm_tool(name="click")
    async def click(self, event: AstrMessageEvent, ref: int) -> MessageEventResult:
        """点击页面快照中带 Ref ID 编号的交互元素。

        Args:
            ref(number): 目标元素编号 Ref ID (如 1, 2)
        """
        self._sync_event_admin(event)
        res = await self.action_tools.click(event.session_id, str(event.get_sender_id()), int(ref))
        yield event.plain_result(res)

    @filter.llm_tool(name="fill_form")
    async def fill_form(self, event: AstrMessageEvent, ref: int, text: str) -> MessageEventResult:
        """在页面快照中的输入框填入文本内容。

        Args:
            ref(number): 输入框编号 Ref ID
            text(string): 需要输入的文本内容
        """
        self._sync_event_admin(event)
        res = await self.action_tools.fill_form(event.session_id, str(event.get_sender_id()), int(ref), str(text))
        yield event.plain_result(res)

    @filter.llm_tool(name="select_option")
    async def select_option(self, event: AstrMessageEvent, ref: int, value: str) -> MessageEventResult:
        """在下拉选择框中选取指定的值。

        Args:
            ref(number): 下拉框编号 Ref ID
            value(string): 需要选取的选项值或选项文本
        """
        self._sync_event_admin(event)
        res = await self.action_tools.select_option(event.session_id, str(event.get_sender_id()), int(ref), str(value))
        yield event.plain_result(res)

    @filter.llm_tool(name="scroll")
    async def scroll(self, event: AstrMessageEvent, direction: str = "down", amount: int = 500) -> MessageEventResult:
        """垂直滚动当前页面。

        Args:
            direction(string): 滚动方向 ('down' 向下, 'up' 向上)
            amount(number): 滚动像素距离 (默认 500)
        """
        self._sync_event_admin(event)
        res = await self.action_tools.scroll(event.session_id, str(event.get_sender_id()), str(direction), int(amount))
        yield event.plain_result(res)

    @filter.llm_tool(name="switch_tab")
    async def switch_tab(self, event: AstrMessageEvent, tab_index: int) -> MessageEventResult:
        """切换至指定的浏览器标签页。

        Args:
            tab_index(number): 标签页序号 (从 1 开始)
        """
        self._sync_event_admin(event)
        res = await self.browse_tools.switch_tab(event.session_id, str(event.get_sender_id()), int(tab_index))
        yield event.plain_result(res)

    @filter.llm_tool(name="take_screenshot")
    async def take_screenshot(self, event: AstrMessageEvent, target: str = "chat") -> MessageEventResult:
        """截取当前网页屏幕。

        Args:
            target(string): 交付目标 ('chat' 发送到聊天会话，'ai' 返回 base64 给模型分析)
        """
        self._sync_event_admin(event)
        res = await self.media_tools.take_screenshot(event.session_id, str(event.get_sender_id()), str(target))
        if res.startswith("[IMAGE_PATH:") and res.endswith("]"):
            path = res[len("[IMAGE_PATH:"):-1]
            try:
                from astrbot.api.message_components import Image
                yield event.chain_result([Image.fromFileSystem(path)])
                return
            except Exception:
                yield event.plain_result(f"截图保存成功: {path}")
                return
        yield event.plain_result(res)

    @filter.llm_tool(name="download_file")
    async def download_file(self, event: AstrMessageEvent, ref: int) -> MessageEventResult:
        """点击指定下载链接下载文件。

        Args:
            ref(number): 下载链接或按钮编号 Ref ID
        """
        self._sync_event_admin(event)
        res = await self.media_tools.download_file(event.session_id, str(event.get_sender_id()), int(ref))
        if res.startswith("[FILE_PATH:") and "\n" in res:
            parts = res.split("\n", 1)
            fpath = parts[0][len("[FILE_PATH:"):-1]
            try:
                from astrbot.api.message_components import File
                yield event.chain_result([File.fromFileSystem(fpath)])
                return
            except Exception:
                yield event.plain_result(res)
                return
        yield event.plain_result(res)

    @filter.llm_tool(name="handle_dialog")
    async def handle_dialog(self, event: AstrMessageEvent, action: str = "accept", prompt_text: str = "") -> MessageEventResult:
        """预设下一次浏览器原生弹窗 (alert/confirm/prompt) 的应答策略。

        Args:
            action(string): 响应策略 ('accept' 确认, 'dismiss' 取消)
            prompt_text(string): 若为 prompt 弹窗，需要输入的字符串 (可选)
        """
        self._sync_event_admin(event)
        p_text = prompt_text if prompt_text else None
        res = await self.dialog_tools.handle_dialog(event.session_id, str(event.get_sender_id()), str(action), p_text)
        yield event.plain_result(res)

    @filter.llm_tool(name="close_browser")
    async def close_browser(self, event: AstrMessageEvent) -> MessageEventResult:
        """主动关闭并释放当前浏览器上下文以释放系统资源。"""
        self._sync_event_admin(event)
        if not self.config.get("enable_close_tool", True):
            yield event.plain_result("管理员未启用 AI 主动关闭浏览器的功能。")
            return
        res = await self.browse_tools.close_browser(event.session_id, str(event.get_sender_id()))
        yield event.plain_result(res)

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
