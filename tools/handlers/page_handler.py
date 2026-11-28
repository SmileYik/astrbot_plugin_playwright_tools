import asyncio
import inspect
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING, Any
import uuid

from ...core.context_manager import ContextManager, BrowserSessionContext
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger
from ...core.readers.base import BasePageReader
from ...core.readers.plain_text_reader import PlainTextReader
from .base_handler import BaseActionHandler, CallToolResult, build_image_tool_result

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
        allow_image_to_ai: bool = False,
        audit_save_screenshots: bool = True,
        audit_screenshots_dir: str = "data/plugin_data/astrbot_plugin_playwright_tools/audit_screenshots",
        commit_timeout_ms: int = 20000,
        plain_text_reader: PlainTextReader | None = None,
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
        self.allow_image_to_ai = allow_image_to_ai
        self.audit_save_screenshots = audit_save_screenshots
        self.audit_screenshots_dir = audit_screenshots_dir
        self.commit_timeout_ms = max(5000, int(commit_timeout_ms or 20000))
        chunk_limit = getattr(reader, "chunk_char_limit", 4000) if reader else 4000
        self.plain_text_reader = plain_text_reader or PlainTextReader(
            chunk_char_limit=int(chunk_limit or 4000),
            mask_passwords=mask_password_inputs,
        )

    @staticmethod
    def _parse_content_type(headers: Any) -> tuple[str, str]:
        """从响应头解析主 MIME 类型与字符集。"""
        if not isinstance(headers, dict):
            return "", ""
        raw_ct = ""
        for k, v in headers.items():
            if isinstance(k, str) and k.lower() == "content-type" and isinstance(v, str):
                raw_ct = v
                break
        if not raw_ct:
            return "", ""
        parts = [p.strip() for p in raw_ct.split(";") if p.strip()]
        mime = parts[0].lower() if parts else ""
        charset = ""
        for param in parts[1:]:
            m = re.match(r"charset\s*=\s*['\"]?([^'\";\s]+)", param, flags=re.IGNORECASE)
            if m:
                charset = m.group(1).strip()
                break
        return mime, charset

    @staticmethod
    def _is_text_mime(mime: str) -> bool:
        """判断 MIME 是否属于非 HTML 纯文本类型。"""
        if not mime:
            return False
        if mime in ("text/html", "application/xhtml+xml"):
            return False
        if mime.startswith("text/"):
            return True
        if mime in (
            "application/json",
            "application/xml",
            "application/javascript",
            "application/ecmascript",
            "application/x-javascript",
            "application/x-yaml",
            "application/yaml",
            "application/x-ndjson",
            "image/svg+xml",
        ):
            return True
        return mime.endswith("+json") or mime.endswith("+xml")

    @staticmethod
    def _decode_text_body(body: bytes, charset: str = "") -> str:
        """按响应头字符集解码字节流，失败时依次回退 utf-8 与 gb18030。"""
        candidates = []
        if charset:
            candidates.append(charset)
        for enc in ("utf-8", "gb18030"):
            if enc not in [c.lower() for c in candidates]:
                candidates.append(enc)
        for enc in candidates:
            try:
                return body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return body.decode("utf-8", errors="replace")

    def _save_audit_image(self, image_bytes: bytes, mime_type: str) -> str:
        """将图片响应字节保存至审计截图目录并返回相对/规范路径。"""
        if not self.audit_save_screenshots or not image_bytes:
            return ""
        try:
            audit_dir = Path(self.audit_screenshots_dir)
            audit_dir.mkdir(parents=True, exist_ok=True)
            ext = ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".png"
            if "webp" in mime_type:
                ext = ".webp"
            elif "gif" in mime_type:
                ext = ".gif"
            shot_name = f"img_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{ext}"
            shot_file = audit_dir / shot_name
            with open(shot_file, "wb") as f:
                f.write(image_bytes)
            return str(Path(self.audit_screenshots_dir) / shot_name).replace("\\", "/")
        except Exception as e:
            logger.warning(f"[PageHandler] 保存图片审计文件失败: {e}")
            return ""

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
    ) -> str | CallToolResult:
        """打开目标网页或直链资源（基于 commit 与 Content-Type 分流处理）。"""

        async def _open(ctx: BrowserSessionContext, page: Page):
            self._setup_page_listeners(ctx, page)
            try:
                response = await page.goto(url, wait_until="commit", timeout=self.commit_timeout_ms)
            except Exception as nav_err:
                if "download is starting" in str(nav_err).lower():
                    ctx.clear_page_state(page, reset_snapshot=True)
                    return (
                        f"目标链接触发了文件下载: {url}\n"
                        f"[提示: 该链接为直接下载资源，未在标签页渲染；如需获取文件请通过其他下载方式或在页面点击触发 pw_media(action='download')]"
                    )
                raise

            headers = getattr(response, "headers", None) if response is not None else None
            mime, charset = self._parse_content_type(headers)

            alive_pages = self._get_alive_pages(ctx)
            total_tabs = len(alive_pages)
            tab_pos = (alive_pages.index(page) + 1) if page in alive_pages else 1

            # 1. 图片直链分支（SVG 按文本处理，避免多模态模型无法解析）
            if mime.startswith("image/") and mime != "image/svg+xml":
                ctx.clear_page_state(page, reset_snapshot=True)
                image_bytes = b""
                if response is not None and hasattr(response, "body"):
                    try:
                        raw_body = response.body()
                        image_bytes = await raw_body if inspect.isawaitable(raw_body) else raw_body
                    except Exception as body_err:
                        logger.debug(f"[PageHandler] 读取图片响应体失败，尝试降级截图: {body_err}")
                if not image_bytes and hasattr(page, "screenshot"):
                    try:
                        if hasattr(page, "wait_for_load_state"):
                            try:
                                load_ret = page.wait_for_load_state("load", timeout=5000)
                                if inspect.isawaitable(load_ret):
                                    await load_ret
                            except Exception as load_err:
                                logger.debug(f"[PageHandler] 图片降级前等待 load 跳过: {load_err}")
                        shot = page.screenshot(full_page=False)
                        image_bytes = await shot if inspect.isawaitable(shot) else shot
                        mime = "image/png"
                    except Exception as shot_err:
                        logger.debug(f"[PageHandler] 图片降级截图失败: {shot_err}")

                screenshot_path = self._save_audit_image(image_bytes, mime) if image_bytes else ""
                size_info = f"{len(image_bytes)} 字节" if image_bytes else "未知大小"
                if self.allow_image_to_ai:
                    if image_bytes:
                        desc = (
                            f"已打开图片资源: {url} (类型: {mime}, 大小: {size_info})。"
                            f"当前位于第 {tab_pos}/{total_tabs} 个标签页，请直接分析下方图片内容。"
                        )
                        return build_image_tool_result(desc, image_bytes, mime), {"screenshot_path": screenshot_path}
                    return (
                        f"已打开图片资源: {url} (类型: {mime})，但未能获取图片内容。当前位于第 {tab_pos}/{total_tabs} 个标签页。\n"
                        f"[推荐操作: 可稍后调用 pw_media(action='screenshot_viewport', target='ai') 尝试重新捕获页面图像]"
                    ), {"screenshot_path": screenshot_path}

                return (
                    f"已打开图片资源: {url} (类型: {mime}, 大小: {size_info})。当前位于第 {tab_pos}/{total_tabs} 个标签页。\n"
                    f"[提示: 当前未开启“允许 AI 直接查看图片”选项，无法直接将图片发送给 AI 分析；如需发给用户请调用 pw_media(action='screenshot_viewport', target='chat')]"
                ), {"screenshot_path": screenshot_path}

            # 2. 非 HTML 纯文本分支
            if self._is_text_mime(mime):
                text_content = ""
                if response is not None and hasattr(response, "body"):
                    try:
                        raw_body = response.body()
                        body_bytes = await raw_body if inspect.isawaitable(raw_body) else raw_body
                        if isinstance(body_bytes, (bytes, bytearray)):
                            text_content = self._decode_text_body(bytes(body_bytes), charset)
                        else:
                            text_content = str(body_bytes or "")
                    except Exception as body_err:
                        logger.debug(f"[PageHandler] 读取文本响应体失败: {body_err}")
                if not text_content and response is not None and hasattr(response, "text"):
                    try:
                        raw_txt = response.text()
                        text_content = await raw_txt if inspect.isawaitable(raw_txt) else str(raw_txt or "")
                    except Exception as txt_err:
                        logger.debug(f"[PageHandler] response.text() 降级失败: {txt_err}")

                page_url = getattr(page, "url", "") or url
                snapshot = self.plain_text_reader.build_snapshot(
                    text=text_content,
                    url=page_url,
                    mime_type=mime,
                )
                page_state = ctx.get_page_state(page)
                page_state.current_snapshot = snapshot
                page_state.ref_map = {}
                page_state.is_snapshot_dirty = False
                return self.plain_text_reader.format_chunk(snapshot, 1)

            # 3. HTML 或无响应头（如前端路由/about:blank）分支
            if not mime or mime in ("text/html", "application/xhtml+xml"):
                if hasattr(page, "wait_for_load_state"):
                    try:
                        ret = page.wait_for_load_state("domcontentloaded", timeout=10000)
                        if inspect.isawaitable(ret):
                            await ret
                    except Exception as dom_err:
                        logger.debug(f"[PageHandler] open_url 等待 domcontentloaded 跳过/超时: {dom_err}")

                title = ""
                try:
                    if hasattr(page, "title") and callable(page.title):
                        t_val = page.title()
                        title = await t_val if inspect.isawaitable(t_val) else str(t_val)
                    else:
                        title = str(getattr(page, "title", ""))
                except Exception as e:
                    logger.debug(f"[PageHandler] 打开页面后提取标题异常: {e}")
                    title = ""

                ctx.clear_page_state(page, reset_snapshot=True)
                return (
                    f"已成功打开网页: {url} (标题: {title})。当前位于第 {tab_pos}/{total_tabs} 个标签页。\n"
                    f"[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]"
                )

            # 4. 其他非网页二进制资源（PDF、压缩包、音视频等）
            ctx.clear_page_state(page, reset_snapshot=True)
            content_length = ""
            if isinstance(headers, dict):
                for k, v in headers.items():
                    if isinstance(k, str) and k.lower() == "content-length" and v:
                        content_length = f", 大小: {v} 字节"
                        break
            return (
                f"已访问非网页二进制资源: {url} (类型: {mime}{content_length})。当前位于第 {tab_pos}/{total_tabs} 个标签页。\n"
                f"[提示: 该资源不是 HTML 网页或纯文本，不建议调用 pw_read()]"
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
            is_plain_text_snap = getattr(page_state.current_snapshot, "reader_mode", "") == "plain_text"
            active_reader = self.plain_text_reader if is_plain_text_snap else self.reader
            snapshot_ts = getattr(page_state.current_snapshot, "timestamp", 0) or 0
            snapshot_url = getattr(page_state.current_snapshot, "url", "") or ""
            is_expired = False if is_plain_text_snap else (time.time() - snapshot_ts) > 60
            url_changed = current_url != snapshot_url

            if (
                page_state.current_snapshot is None
                or page_state.is_snapshot_dirty
                or url_changed
                or is_expired
                or refresh
            ):
                if url_changed:
                    active_reader = self.reader
                ref_lock = getattr(ctx, "ref_lock", None)
                if ref_lock is None:
                    ref_lock = asyncio.Lock()
                    ctx.ref_lock = ref_lock

                async with ref_lock:
                    start_ref = getattr(ctx, "next_ref_id", 1) or 1
                    try:
                        snapshot = await active_reader.extract_snapshot(cur_page, current_url, start_ref=start_ref)
                    except TypeError:
                        try:
                            snapshot = await active_reader.extract_snapshot(cur_page, current_url)
                        except TypeError:
                            snapshot = await active_reader.extract_snapshot(cur_page)

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
                return active_reader.search(page_state.current_snapshot, str(keyword).strip())
            else:
                return active_reader.format_chunk(page_state.current_snapshot, page)

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
