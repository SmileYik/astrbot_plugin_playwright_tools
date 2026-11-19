from typing import Any
from core.context_manager import ContextManager
from core.security_manager import SecurityManager
from core.audit_logger import AuditLogger
from core.page_extractor import PageExtractor

class BrowseTools:
    """页面导航与标签页管理工具集。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        page_extractor: PageExtractor,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger
        self.page_extractor = page_extractor

    def _setup_page_listeners(self, context, page):
        """为页面附加弹窗与新标签监听器。"""
        async def on_dialog(dialog):
            msg = dialog.message
            context.last_dialog_message = msg
            action = "accept"
            prompt_text = None
            if context.dialog_action:
                action = context.dialog_action.get("action", "accept")
                prompt_text = context.dialog_action.get("prompt_text")
                context.dialog_action = None  # 仅消费一次

            if action == "accept":
                await dialog.accept(prompt_text=prompt_text)
            else:
                await dialog.dismiss()

        page.on("dialog", on_dialog)

    async def open_url(self, session_id: str, sender_id: str, url: str) -> str:
        """打开目标网页并返回第一页的元素快照。

        Args:
            url(string): 目标网页地址 (需包含 http:// 或 https://)
        """
        allowed, reason = self.security_mgr.is_url_allowed_navigation(sender_id, url)
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{sender_id}", sender_id,
                "open_url", url, {"url": url}, reason, is_permitted=False, deny_reason=reason
            )
            return f"打开失败: {reason}"

        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "打开失败: 无法获取浏览器上下文"

        page = ctx.current_page
        self._setup_page_listeners(ctx, page)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            data = await page.evaluate(self.page_extractor.get_js_extractor_script())
            snapshot_text, ref_map = self.page_extractor.extract_snapshot(
                data.get("title", ""), data.get("url", url),
                data.get("elements", []), data.get("text_blocks", [])
            )
            ctx.ref_map = ref_map
            chunk_output = self.page_extractor.format_page_chunk(snapshot_text, page_index=1)

            res = f"{hint}\n{chunk_output}".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "open_url", url, {"url": url}, "页面打开成功", is_permitted=True
            )
            return res
        except Exception as e:
            err_msg = f"页面打开异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "open_url", url, {"url": url}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e)
            )
            return err_msg

    async def read_page(self, session_id: str, sender_id: str, page: int = 1) -> str:
        """读取当前页面的内容（支持指定分页）。

        Args:
            page(number): 分页页码 (从 1 开始)
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "读取失败: 无法获取浏览器上下文"

        current_url = getattr(ctx.current_page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, current_url, "read")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page}, reason, is_permitted=False, deny_reason=reason
            )
            return f"读取失败: {reason}"

        try:
            data = await ctx.current_page.evaluate(self.page_extractor.get_js_extractor_script())
            snapshot_text, ref_map = self.page_extractor.extract_snapshot(
                data.get("title", ""), data.get("url", current_url),
                data.get("elements", []), data.get("text_blocks", [])
            )
            ctx.ref_map = ref_map
            chunk_output = self.page_extractor.format_page_chunk(snapshot_text, page_index=page)

            res = f"{hint}\n{chunk_output}".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page}, f"读取第 {page} 页成功", is_permitted=True
            )
            return res
        except Exception as e:
            err_msg = f"读取页面异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e)
            )
            return err_msg

    async def switch_tab(self, session_id: str, sender_id: str, tab_index: int) -> str:
        """切换当前控制的浏览器标签页。

        Args:
            tab_index(number): 目标标签页索引 (从 1 开始)
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "切换失败: 无法获取浏览器上下文"

        pages = ctx.browser_context.pages
        if tab_index < 1 or tab_index > len(pages):
            return f"切换失败: 标签页索引 {tab_index} 超出范围 (当前共有 {len(pages)} 个标签页)"

        ctx.current_page = pages[tab_index - 1]
        ctx.pages = pages
        # 切换标签页后刷新 Ref ID
        ctx.ref_map = {}
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "switch_tab", ctx.current_page.url, {"tab_index": tab_index},
            f"已切换至标签页 {tab_index}", is_permitted=True
        )
        return f"{hint}\n已成功切换至标签页 {tab_index} (URL: {ctx.current_page.url})。建议调用 read_page() 查看页面元素。".strip()

    async def close_browser(self, session_id: str, sender_id: str) -> str:
        """关闭并释放当前浏览器上下文。"""
        ok, msg = await self.context_mgr.close_user_context(session_id, sender_id)
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{sender_id}", sender_id,
            "close_browser", "", {}, msg, is_permitted=True
        )
        return msg
