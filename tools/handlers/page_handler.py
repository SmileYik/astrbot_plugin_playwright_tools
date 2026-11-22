import inspect
import time
from typing import TYPE_CHECKING, Any

from ...core.context_manager import ContextManager, BrowserSessionContext
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger
from ...core.readers.base import BasePageReader
from .base_handler import BaseActionHandler

if TYPE_CHECKING:
    from playwright.async_api import Page
else:
    Page = Any

from astrbot.api import logger


class PageHandler(BaseActionHandler):
    """页面导航、内容读取、快速检索与标签页/弹窗管理。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        reader: BasePageReader | None = None,
        enable_close_tool: bool = True,
        mask_password_inputs: bool = True,
        **kwargs,
    ):
        super().__init__(
            context_mgr,
            security_mgr,
            audit_logger,
            mask_password_inputs=mask_password_inputs,
        )
        self.reader = reader
        self.enable_close_tool = enable_close_tool

    def _setup_page_listeners(self, context: BrowserSessionContext, page: Page) -> None:
        """为页面附加原生弹窗自动应答监听器。"""
        if getattr(page, "_has_dialog_listener", False):
            return

        async def on_dialog(dialog):
            msg = dialog.message
            context.last_dialog_message = msg
            action = "accept"
            prompt_text = None
            if context.dialog_action:
                action = context.dialog_action.get("action", "accept")
                prompt_text = context.dialog_action.get("prompt_text")
                context.dialog_action = None

            if action == "accept":
                await dialog.accept(prompt_text=prompt_text)
            else:
                await dialog.dismiss()

        if hasattr(page, "on"):
            try:
                page.on("dialog", on_dialog)
                page._has_dialog_listener = True
            except Exception as e:
                logger.debug(f"[PageHandler] 注册弹窗监听异常: {e}")

    async def open_url(
        self,
        session_id: str,
        sender_id: str,
        url: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """打开目标网页。"""

        async def _open(ctx: BrowserSessionContext, page: Page) -> str:
            self._setup_page_listeners(ctx, page)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            title = ""
            try:
                if hasattr(page, "title") and callable(page.title):
                    t_val = page.title()
                    if inspect.isawaitable(t_val):
                        title = await t_val
                    else:
                        title = str(t_val)
                else:
                    title = str(getattr(page, "title", ""))
            except Exception as e:
                logger.debug(f"[PageHandler] 打开页面后提取标题异常: {e}")
                title = ""

            ctx.current_snapshot = None
            ctx.is_snapshot_dirty = True
            ctx.ref_map = {}

            return f"已成功打开网页: {url} (标题: {title})。\n[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="open_url",
            target_resource=url,
            action_coro_fn=_open,
            input_args={"url": url},
            required_permission="navigate",
            session_name=session_name,
            sender_name=sender_name,
            wait_stabilize=True,
            action_desc="打开",
        )

    async def read_page(
        self,
        session_id: str,
        sender_id: str,
        page: int = 1,
        keyword: str = "",
        refresh: bool = False,
        session_name: str = "",
        sender_name: str = "",
        **kwargs,
    ) -> str:
        """读取当前页面的内容与可交互操作元素（支持懒加载快照缓存、四重失效判定与关键词定位）。"""

        async def _read(ctx: BrowserSessionContext, cur_page: Page) -> str:
            current_url = getattr(cur_page, "url", "")
            await self.wait_page_stable(cur_page)

            snapshot_ts = getattr(ctx.current_snapshot, "timestamp", 0) or 0
            snapshot_url = getattr(ctx.current_snapshot, "url", "") or ""
            is_expired = (time.time() - snapshot_ts) > 60
            url_changed = current_url != snapshot_url

            if (
                ctx.current_snapshot is None
                or ctx.is_snapshot_dirty
                or url_changed
                or is_expired
                or refresh
            ):
                ref_lock = getattr(ctx, "ref_lock", None)
                if ref_lock is None:
                    ref_lock = asyncio.Lock()
                    ctx.ref_lock = ref_lock

                async with ref_lock:
                    start_ref = getattr(ctx, "next_ref_id", 1) or 1
                    try:
                        snapshot = await self.reader.extract_snapshot(cur_page, current_url, start_ref=start_ref)
                    except TypeError:
                        try:
                            snapshot = await self.reader.extract_snapshot(cur_page, current_url)
                        except TypeError:
                            snapshot = await self.reader.extract_snapshot(cur_page)

                    ctx.current_snapshot = snapshot
                    ctx.ref_map = getattr(snapshot, "ref_map", {})
                    ctx.is_snapshot_dirty = False
                    allocated = getattr(snapshot, "allocated_count", 0) or 0
                    next_ref = (start_ref + allocated) % 1_000_000
                    if next_ref == 0:
                        next_ref = 1
                    ctx.next_ref_id = next_ref

            if keyword and str(keyword).strip():
                return self.reader.search(ctx.current_snapshot, str(keyword).strip())
            else:
                return self.reader.format_chunk(ctx.current_snapshot, page)

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="read_page",
            target_resource="",
            action_coro_fn=_read,
            input_args={"page": page, "keyword": keyword, "refresh": refresh},
            required_permission="read",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="读取",
        )

    async def switch_tab(
        self,
        session_id: str,
        sender_id: str,
        tab_index: int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """切换当前控制的浏览器标签页。"""

        async def _switch(ctx: BrowserSessionContext, page: Page) -> str:
            pages = getattr(ctx.browser_context, "pages", None) or getattr(ctx, "pages", [])
            if tab_index < 1 or tab_index > len(pages):
                return f"切换失败: 标签页索引 {tab_index} 超出范围 (当前共有 {len(pages)} 个标签页)"

            ctx.current_page = pages[tab_index - 1]
            ctx.pages = pages
            ctx.ref_map = {}
            ctx.current_snapshot = None
            ctx.is_snapshot_dirty = True
            return f"已成功切换至标签页 {tab_index} (URL: {ctx.current_page.url})。\n[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="switch_tab",
            target_resource="",
            action_coro_fn=_switch,
            input_args={"tab_index": tab_index},
            session_name=session_name,
            sender_name=sender_name,
            action_desc="切换",
        )

    async def handle_dialog(
        self,
        session_id: str,
        sender_id: str,
        action: str = "accept",
        prompt_text: str | None = None,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """预先配置下一次触发的浏览器原生弹窗 (alert/confirm/prompt) 响应策略。"""

        async def _dialog(ctx: BrowserSessionContext, page: Page) -> str:
            ctx.dialog_action = {
                "action": action.lower(),
                "prompt_text": prompt_text,
            }
            return f"已预设下一次弹窗处理策略: 动作={action}" + (
                f", 输入='{prompt_text}'" if prompt_text else ""
            )

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="handle_dialog",
            target_resource="",
            action_coro_fn=_dialog,
            input_args={"action": action, "prompt_text": prompt_text},
            session_name=session_name,
            sender_name=sender_name,
            action_desc="配置",
        )

    async def close_browser(
        self,
        session_id: str,
        sender_id: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """关闭并释放当前浏览器上下文。"""
        if not self.enable_close_tool:
            return "管理员未启用 AI 主动关闭浏览器的功能。"

        async def _close(ctx: BrowserSessionContext, page: Page) -> str:
            ok, msg = await self.context_mgr.close_user_context(session_id, sender_id)
            return msg

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="close_browser",
            target_resource="",
            action_coro_fn=_close,
            session_name=session_name,
            sender_name=sender_name,
            action_desc="关闭",
        )
