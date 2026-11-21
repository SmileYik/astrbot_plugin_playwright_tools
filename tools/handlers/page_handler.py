import traceback
import inspect
from typing import Any
from ...core.context_manager import ContextManager
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger
from ...core.readers.base import BasePageReader
from ...core.page_extractor import PageExtractor

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class PageHandler:
    """页面导航、内容读取、快速检索与标签页/弹窗管理。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        reader: BasePageReader | None = None,
        page_extractor: PageExtractor | None = None,
        enable_close_tool: bool = True,
        **kwargs,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger
        actual_reader = reader if reader is not None else page_extractor
        if actual_reader is None and "page_extractor" in kwargs:
            actual_reader = kwargs["page_extractor"]
        self.reader = actual_reader
        self.page_extractor = page_extractor or actual_reader
        self.enable_close_tool = enable_close_tool

    def _setup_page_listeners(self, context, page):
        """为页面附加原生弹窗自动应答监听器。"""
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
            except Exception:
                pass

    async def open_url(
        self,
        session_id: str,
        sender_id: str,
        url: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """打开目标网页。"""
        allowed, reason = self.security_mgr.is_url_allowed_navigation(sender_id, url)
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{sender_id}", sender_id,
                "open_url", url, {"url": url}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"打开失败: {reason}"

        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "打开失败: 无法获取浏览器上下文"

        page = ctx.current_page
        self._setup_page_listeners(ctx, page)

        try:
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
            except Exception:
                title = ""

            ctx.current_snapshot = None
            ctx.is_snapshot_dirty = True
            ctx.ref_map = {}

            res = f"{hint}\n已成功打开网页: {url} (标题: {title})。\n[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "open_url", url, {"url": url}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] open_url 异常: {e}\n{tb_str}")
            err_msg = f"页面打开异常: {str(e)}"
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "open_url", url, {"url": url}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

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
        """读取当前页面的内容与可交互操作元素（支持懒加载快照缓存、脏标记失效与关键词定位）。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "读取失败: 无法获取浏览器上下文"

        current_url = getattr(ctx.current_page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, current_url, "read")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page, "keyword": keyword, "refresh": refresh}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"读取失败: {reason}"

        try:
            if ctx.current_snapshot is None or ctx.is_snapshot_dirty or refresh:
                try:
                    snapshot = await self.reader.extract_snapshot(ctx.current_page, current_url)
                except TypeError:
                    snapshot = await self.reader.extract_snapshot(ctx.current_page)
                ctx.current_snapshot = snapshot
                ctx.ref_map = getattr(snapshot, "ref_map", {})
                ctx.is_snapshot_dirty = False

            if keyword and str(keyword).strip():
                content = self.reader.search(ctx.current_snapshot, str(keyword).strip())
            else:
                content = self.reader.format_chunk(ctx.current_snapshot, page)

            res = f"{hint}\n{content}".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page, "keyword": keyword, "refresh": refresh}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] read_page 异常: {e}\n{tb_str}")
            err_msg = f"读取页面异常: {str(e)}"
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page, "keyword": keyword, "refresh": refresh}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def search_page(
        self,
        session_id: str,
        sender_id: str,
        keyword: str,
        target: str = "all",
        session_name: str = "",
        sender_name: str = "",
        **kwargs,
    ) -> str:
        """在当前页面中快速定位并检索包含关键词的内容（向后兼容）。"""
        return await self.read_page(
            session_id=session_id,
            sender_id=sender_id,
            page=1,
            keyword=keyword,
            refresh=False,
            session_name=session_name,
            sender_name=sender_name,
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
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "切换失败: 无法获取浏览器上下文"

        pages = getattr(ctx.browser_context, "pages", None) or getattr(ctx, "pages", [])
        if tab_index < 1 or tab_index > len(pages):
            return f"切换失败: 标签页索引 {tab_index} 超出范围 (当前共有 {len(pages)} 个标签页)"

        ctx.current_page = pages[tab_index - 1]
        ctx.pages = pages
        ctx.ref_map = {}
        ctx.current_snapshot = None
        ctx.is_snapshot_dirty = True
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "switch_tab", ctx.current_page.url, {"tab_index": tab_index},
            f"已切换至标签页 {tab_index}", is_permitted=True,
            session_name=session_name, sender_name=sender_name
        )
        return f"{hint}\n已成功切换至标签页 {tab_index} (URL: {ctx.current_page.url})。\n[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]".strip()

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
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "配置失败: 无法获取浏览器上下文"

        ctx.dialog_action = {
            "action": action.lower(),
            "prompt_text": prompt_text,
        }
        res = f"{hint}\n已预设下一次弹窗处理策略: 动作={action}" + (f", 输入='{prompt_text}'" if prompt_text else "")
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "handle_dialog", "", {"action": action, "prompt_text": prompt_text},
            res, is_permitted=True,
            session_name=session_name, sender_name=sender_name
        )
        return res.strip()

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
        ok, msg = await self.context_mgr.close_user_context(session_id, sender_id)
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{sender_id}", sender_id,
            "close_browser", "", {}, msg, is_permitted=True,
            session_name=session_name, sender_name=sender_name
        )
        return msg
