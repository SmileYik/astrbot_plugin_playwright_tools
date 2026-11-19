from core.context_manager import ContextManager
from core.security_manager import SecurityManager
from core.audit_logger import AuditLogger
from core.page_extractor import PageExtractor

class PageHandler:
    """页面导航、内容读取、快速检索与标签页/弹窗管理。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        page_extractor: PageExtractor,
        enable_close_tool: bool = True,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger
        self.page_extractor = page_extractor
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
        """打开目标网页并返回第一页元素快照。"""
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
                "open_url", url, {"url": url}, "页面打开成功", is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            err_msg = f"页面打开异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "open_url", url, {"url": url}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e),
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def read_page(
        self,
        session_id: str,
        sender_id: str,
        page: int = 1,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """读取当前页面的内容（支持分页）。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "读取失败: 无法获取浏览器上下文"

        current_url = getattr(ctx.current_page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, current_url, "read")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
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
                "read_page", current_url, {"page": page}, f"读取第 {page} 页成功", is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            err_msg = f"读取页面异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e),
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def search_page(
        self,
        session_id: str,
        sender_id: str,
        keyword: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """在当前页面中快速定位并检索包含关键词的内容与操作元素。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "检索失败: 无法获取浏览器上下文"

        current_url = getattr(ctx.current_page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, current_url, "read")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "search_page", current_url, {"keyword": keyword}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"检索失败: {reason}"

        try:
            data = await ctx.current_page.evaluate(self.page_extractor.get_js_extractor_script())
            snapshot_text, ref_map = self.page_extractor.extract_snapshot(
                data.get("title", ""), data.get("url", current_url),
                data.get("elements", []), data.get("text_blocks", [])
            )
            ctx.ref_map = ref_map
            search_output = self.page_extractor.search_snapshot(snapshot_text, keyword)

            res = f"{hint}\n{search_output}".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "search_page", current_url, {"keyword": keyword}, f"检索关键词 '{keyword}' 成功", is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            err_msg = f"检索页面异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "search_page", current_url, {"keyword": keyword}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e),
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

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

        pages = ctx.browser_context.pages
        if tab_index < 1 or tab_index > len(pages):
            return f"切换失败: 标签页索引 {tab_index} 超出范围 (当前共有 {len(pages)} 个标签页)"

        ctx.current_page = pages[tab_index - 1]
        ctx.pages = pages
        ctx.ref_map = {}
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "switch_tab", ctx.current_page.url, {"tab_index": tab_index},
            f"已切换至标签页 {tab_index}", is_permitted=True,
            session_name=session_name, sender_name=sender_name
        )
        return f"{hint}\n已成功切换至标签页 {tab_index} (URL: {ctx.current_page.url})。建议调用 read 查看页面元素。".strip()

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
