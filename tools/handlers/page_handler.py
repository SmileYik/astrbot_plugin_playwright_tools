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

            ctx.clear_page_state(page, reset_snapshot=True)

            alive_pages = self._get_alive_pages(ctx)
            total_tabs = len(alive_pages)
            tab_pos = (alive_pages.index(page) + 1) if page in alive_pages else 1
            return (
                f"已成功打开网页: {url} (标题: {title})。当前位于第 {tab_pos}/{total_tabs} 个标签页。\n"
                f"[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]"
            )

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
        ref: str = "",
        session_name: str = "",
        sender_name: str = "",
        **kwargs,
    ) -> str:
        """读取当前页面的内容与可交互操作元素（支持懒加载快照缓存、四重失效判定、关键词定位与 Ref 详情查询）。"""
        clean_ref = str(ref or kwargs.get("ref") or "").strip()

        async def _read(ctx: BrowserSessionContext, cur_page: Page) -> str:
            current_url = getattr(cur_page, "url", "")
            await self.wait_page_stable(cur_page)

            page_state = ctx.get_page_state(cur_page)
            snapshot_ts = getattr(page_state.current_snapshot, "timestamp", 0) or 0
            snapshot_url = getattr(page_state.current_snapshot, "url", "") or ""
            is_expired = (time.time() - snapshot_ts) > 60
            url_changed = current_url != snapshot_url

            if (
                page_state.current_snapshot is None
                or page_state.is_snapshot_dirty
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

                    page_state.current_snapshot = snapshot
                    page_state.ref_map = getattr(snapshot, "ref_map", {})
                    page_state.is_snapshot_dirty = False
                    allocated = getattr(snapshot, "allocated_count", 0) or 0
                    next_ref = (start_ref + allocated) % 1_000_000
                    if next_ref == 0:
                        next_ref = 1
                    ctx.next_ref_id = next_ref

            clean_ref = str(ref or kwargs.get("ref") or "").strip()
            if clean_ref:
                ref_map = page_state.ref_map or getattr(page_state.current_snapshot, "ref_map", {}) or {}
                el = ref_map.get(clean_ref)
                if not el:
                    return f"未在当前快照中找到 Ref ID 为 '{clean_ref}' 的元素。请确认编号是否正确，或调用 pw_read(refresh=True) 刷新快照。"

                tag = (el.get("tag") or "").lower()
                role = (el.get("role") or "").lower()
                href = (el.get("href") or "").strip()
                src = (el.get("src") or "").strip()
                text = (el.get("text") or "").strip()
                alt = (el.get("alt") or "").strip()

                lines = [f"=== Ref 元素详情查询: [{clean_ref}] ==="]
                if href and src:
                    lines.append("- 元素类型: 超链接 (含图片)")
                    if text:
                        lines.append(f"- 链接文本: {text}")
                    if alt and alt != text:
                        lines.append(f"- 图片描述: {alt}")
                    lines.append(f"- 目标地址: {href}")
                    lines.append(f"- 图片地址: {src}")
                elif href:
                    lines.append("- 元素类型: 超链接")
                    if text:
                        lines.append(f"- 链接文本: {text}")
                    lines.append(f"- 目标地址: {href}")
                elif src or tag == "img":
                    lines.append("- 元素类型: 图片")
                    desc = alt or text
                    if desc:
                        lines.append(f"- 图片描述: {desc}")
                    if src:
                        lines.append(f"- 图片地址: {src}")
                    else:
                        lines.append("- 图片地址: (未获取到有效图片地址)")
                else:
                    type_label = "控件"
                    if tag == "button" or role == "button":
                        type_label = "按钮"
                    elif tag == "input":
                        inp_type = el.get("type", "text")
                        type_label = f"输入框 ({inp_type})" if inp_type else "输入框"
                    elif tag == "select":
                        type_label = "选择框"
                    elif tag == "textarea":
                        type_label = "文本域"
                    elif role:
                        type_label = role

                    lines.append(f"- 元素类型: {type_label}")
                    if text:
                        lines.append(f"- 元素描述: {text}")
                    lines.append(f"- 提示: 该元素不包含可跳转的超链接或图片 URL。如需操作请调用 pw_interact(action='click', ref='{clean_ref}')。")

                return "\n".join(lines)

            if keyword and str(keyword).strip():
                return self.reader.search(page_state.current_snapshot, str(keyword).strip())
            else:
                return self.reader.format_chunk(page_state.current_snapshot, page)

        read_input_args = {
            "page": page,
            "keyword": keyword,
            "refresh": refresh,
        }
        if clean_ref:
            read_input_args["ref"] = clean_ref

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="read_page",
            target_resource="",
            action_coro_fn=_read,
            input_args=read_input_args,
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
            pages = self._get_alive_pages(ctx)
            if tab_index < 1 or tab_index > len(pages):
                return f"切换失败: 标签页索引 {tab_index} 超出范围 (当前共有 {len(pages)} 个标签页，可调用 pw_page(action='list_tabs') 查看全部标签页)"

            target_page = pages[tab_index - 1]
            await ctx.activate_page(target_page)
            return f"已成功切换至标签页 {tab_index}/{len(pages)} (URL: {ctx.current_page.url})。\n[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]"

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

    async def list_tabs(
        self,
        session_id: str,
        sender_id: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """列出当前上下文所有已打开的标签页及当前活动标签页。"""

        async def _list(ctx: BrowserSessionContext, page: Page) -> str:
            pages = self._get_alive_pages(ctx)
            if not pages:
                return "当前浏览器上下文没有已打开的标签页。"

            active_page = getattr(ctx, "current_page", None)
            active_idx = (pages.index(active_page) + 1) if active_page in pages else 0
            lines = [f"当前共 {len(pages)} 个标签页（当前活动: 第 {active_idx} 个）："]
            for i, p in enumerate(pages, start=1):
                marker = "[当前活动]" if p is active_page else "[ ]"
                title = await self._safe_page_title(p) or "(无标题)"
                url = str(getattr(p, "url", "") or "").strip() or "(空白页)"
                lines.append(f"{i}. {marker} {title} - {url}")
            lines.append("[推荐操作: 如需切换请调用 pw_page(action='switch_tab', tab_index=序号)，或直接操作已有标签页的 Ref ID]")
            return "\n".join(lines)

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="list_tabs",
            target_resource="",
            action_coro_fn=_list,
            input_args={},
            session_name=session_name,
            sender_name=sender_name,
            action_desc="查看",
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
