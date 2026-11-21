import re
import traceback
from typing import TYPE_CHECKING, Any
from ...core.context_manager import ContextManager
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator
else:
    Page = Any
    Locator = Any

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def clean_playwright_error(e: Exception) -> str:
    """提取 Playwright 异常核心原因，去除冗长的底层 Call log 与调用栈。"""
    raw = str(e)
    # 检查是否为遮挡错误 (intercepts pointer events)
    if "intercepts pointer events" in raw:
        tag_match = re.search(r"<([a-zA-Z0-9\-]+)[^>]*>\s*intercepts pointer events", raw)
        blocked_tag = f"<{tag_match.group(1)}>" if tag_match else "页面弹窗/遮罩"
        return (
            f"操作超时 (10秒): 目标元素被页面弹层遮挡 ({blocked_tag})，无法接收点击事件。\n"
            f"[推荐操作: 请先查阅页面元素列表，点击关闭按钮或关闭遮挡的弹层]"
        )

    # 检查定位超时 (waiting for locator)
    if "Timeout" in raw and "waiting for locator" in raw:
        return (
            "操作超时 (10秒): 未能定位到目标元素或元素不可见/不可点击。\n"
            "[推荐操作: 页面可能已动态更新，请先调用 pw_read() 获取最新可用元素]"
        )

    # 检查通用超时
    if "Timeout" in raw:
        return "操作超时 (10秒): 执行未在规定时间内完成。\n[推荐操作: 可检查网络或页面加载状态后重试]"

    # 剥离 Call log
    if "Call log:" in raw:
        clean_first_line = raw.split("Call log:")[0].strip()
        return f"操作异常: {clean_first_line}\n[推荐操作: 检查参数与页面状态后重试]"

    first_line = raw.splitlines()[0] if raw.splitlines() else str(raw)
    return f"操作异常: {first_line}\n[推荐操作: 检查参数与页面状态后重试]"


class InteractHandler:
    """页面动作交互处理器 (点击、输入、选择、悬停、聚焦/失焦、拖拽、按键、滚动)。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger

    async def click(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """点击目标元素。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "click")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"点击失败: {reason}"

        if ref not in ctx.ref_map:
            return f"点击失败: 无效的元素引用 [{ref}]。页面可能已刷新，请先调用 pw_read() 查看最新元素。"

        el_info = ctx.ref_map[ref]
        tag = el_info.get("tag", "")
        text = el_info.get("text", "")

        try:
            locator: Locator = page.locator(f'[data-astr-ref="{ref}"]')
            await locator.click(timeout=10000)
            ctx.is_snapshot_dirty = True

            dialog_info = ""
            if ctx.last_dialog_message:
                dialog_info = f" (触发浏览器弹窗: '{ctx.last_dialog_message}'，已自动处理)"
                ctx.last_dialog_message = None

            res_msg = f"{hint}\n已成功点击 [{ref}] <{tag}> {text}{dialog_info}\n[推荐操作: 若点击引发了页面跳转或内容更新，建议调用 pw_read() 查看最新页面]".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] click 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def fill_form(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        text: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """在表单输入框中填入指定内容。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "fill")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"填写失败: {reason}"

        if ref not in ctx.ref_map:
            return f"填写失败: 无效的元素引用 [{ref}]"

        try:
            locator: Locator = page.locator(f'[data-astr-ref="{ref}"]')
            await locator.fill(str(text), timeout=10000)
            ctx.is_snapshot_dirty = True

            res_msg = f"{hint}\n已成功在输入框 [{ref}] 填入内容。\n[推荐操作: 表单输入完成，可查阅对应提交按钮 Ref 并调用 pw_interact(action='click') 进行提交]".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] fill_form 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def select_option(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        value: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """在下拉选择框中选取指定的值。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "click")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "select_option", url, {"ref": ref, "value": value}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"选择失败: {reason}"

        if ref not in ctx.ref_map:
            return f"选择失败: 无效的元素引用 [{ref}]"

        try:
            locator: Locator = page.locator(f'[data-astr-ref="{ref}"]')
            # 优先按 value 匹配，若失败则尝试按 label 匹配
            try:
                await locator.select_option(value=value, timeout=5000)
            except Exception:
                await locator.select_option(label=value, timeout=5000)
            ctx.is_snapshot_dirty = True

            res_msg = f"{hint}\n已在下拉框 [{ref}] 成功选取 '{value}'。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "select_option", url, {"ref": ref, "value": value}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] select_option 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "select_option", url, {"ref": ref, "value": value}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def hover(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """将鼠标悬停在目标元素上。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "click")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "hover", url, {"ref": ref}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"悬停失败: {reason}"

        if ref not in ctx.ref_map:
            return f"悬停失败: 无效的元素引用 [{ref}]"

        try:
            locator: Locator = page.locator(f'[data-astr-ref="{ref}"]')
            await locator.hover(timeout=10000)

            res_msg = f"{hint}\n已成功悬停在元素 [{ref}] 上。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "hover", url, {"ref": ref}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] hover 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "hover", url, {"ref": ref}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def focus(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """将焦点聚集到目标元素。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "click")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "focus", url, {"ref": ref}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"聚焦失败: {reason}"

        if ref not in ctx.ref_map:
            return f"聚焦失败: 无效的元素引用 [{ref}]"

        try:
            locator: Locator = page.locator(f'[data-astr-ref="{ref}"]')
            await locator.focus(timeout=10000)
            res = f"{hint}\n已聚焦到元素 [{ref}]。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "focus", url, {"ref": ref}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] focus 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "focus", url, {"ref": ref}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def blur(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """使目标元素失去焦点。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "click")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "blur", url, {"ref": ref}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"失焦失败: {reason}"

        if ref not in ctx.ref_map:
            return f"失焦失败: 无效的元素引用 [{ref}]"

        try:
            locator: Locator = page.locator(f'[data-astr-ref="{ref}"]')
            await locator.evaluate("el => el.blur()")
            res = f"{hint}\n元素 [{ref}] 已失焦。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "blur", url, {"ref": ref}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] blur 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "blur", url, {"ref": ref}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def drag(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        target_ref: int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """将源元素拖拽至目标元素位置。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "click")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "drag", url, {"ref": ref, "target_ref": target_ref}, reason,
                is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"拖拽失败: {reason}"

        if ref not in ctx.ref_map:
            return f"拖拽失败: 无效的源元素引用 [{ref}]"
        if target_ref not in ctx.ref_map:
            return f"拖拽失败: 无效的拖拽目标元素引用 [{target_ref}]"

        try:
            source: Locator = page.locator(f'[data-astr-ref="{ref}"]')
            target: Locator = page.locator(f'[data-astr-ref="{target_ref}"]')
            await source.drag_to(target, timeout=10000)
            ctx.is_snapshot_dirty = True

            res_msg = f"{hint}\n已成功将元素 [{ref}] 拖拽至 [{target_ref}] 位置。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "drag", url, {"ref": ref, "target_ref": target_ref}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] drag 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "drag", url, {"ref": ref, "target_ref": target_ref}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def press_key(
        self,
        session_id: str,
        sender_id: str,
        key: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """向当前页面或已聚焦元素发送键盘按键。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "fill")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "press_key", url, {"key": key}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"按键失败: {reason}"

        key_name = key.strip()
        if not key_name:
            return "按键失败: 请提供有效的按键名称"

        try:
            await page.keyboard.press(key_name)
            ctx.is_snapshot_dirty = True

            res_msg = f"{hint}\n已成功向页面发送按键 '{key_name}'。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "press_key", url, {"key": key_name}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] press_key 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "press_key", url, {"key": key_name}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

    async def scroll(
        self,
        session_id: str,
        sender_id: str,
        direction: str = "down",
        amount: int = 500,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """垂直滚动当前页面。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "滚动失败: 无法获取浏览器上下文"

        page: Page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "scroll")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "scroll", url, {"direction": direction, "amount": amount}, reason,
                is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"滚动失败: {reason}"

        try:
            delta = amount if direction.lower() == "down" else -amount
            if hasattr(page, "mouse") and hasattr(page.mouse, "wheel"):
                await page.mouse.wheel(0, delta)
            else:
                await page.evaluate("(d) => window.scrollBy(0, d)", delta)

            dir_name = "下" if direction.lower() == "down" else ("上" if direction.lower() == "up" else direction)
            res_msg = f"{hint}\n页面已向{dir_name}滚动 {amount} 像素。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "scroll", url, {"direction": direction, "amount": amount}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] scroll 异常: {e}\n{tb_str}")
            err_msg = clean_playwright_error(e)
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "scroll", url, {"direction": direction, "amount": amount}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg
