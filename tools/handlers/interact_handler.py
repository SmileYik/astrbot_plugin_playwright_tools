import traceback
from ...core.context_manager import ContextManager
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

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

        page = ctx.current_page
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
            return f"点击失败: 无效的元素引用 [{ref}]。页面可能已刷新，请先调用 pw_page(action='read') 查看最新元素。"

        el_info = ctx.ref_map[ref]
        tag = el_info.get("tag", "")
        text = el_info.get("text", "")

        try:
            script = """
            (ref) => {
                const target = document.querySelector(`[data-astr-ref="${ref}"]`);
                if (target) {
                    target.scrollIntoView({behavior: 'smooth', block: 'center'});
                    target.click();
                    return true;
                }
                return false;
            }
            """
            clicked = await page.evaluate(script, ref)
            if not clicked:
                return f"点击失败: 未能定位元素 [{ref}]"

            dialog_info = ""
            if ctx.last_dialog_message:
                dialog_info = f" (触发浏览器弹窗: '{ctx.last_dialog_message}'，已自动处理)"
                ctx.last_dialog_message = None

            res_msg = f"{hint}\n已成功点击 [{ref}] <{tag}> {text}{dialog_info}".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            logger.error(f"[PlaywrightTool] click 异常: {e}\n{traceback.format_exc()}")
            err_msg = f"点击异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e),
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

        page = ctx.current_page
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
            script = """
            ([ref, val]) => {
                const target = document.querySelector(`[data-astr-ref="${ref}"]`);
                if (target) {
                    target.value = val;
                    target.dispatchEvent(new Event('input', { bubbles: true }));
                    target.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """
            filled = await page.evaluate(script, [ref, text])
            if not filled:
                return f"填写失败: 未能定位元素 [{ref}]"

            res_msg = f"{hint}\n已成功在输入框 [{ref}] 填入内容。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            logger.error(f"[PlaywrightTool] fill_form 异常: {e}\n{traceback.format_exc()}")
            err_msg = f"填写异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e),
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

        page = ctx.current_page
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
            script = """
            ([ref, val]) => {
                const target = document.querySelector(`[data-astr-ref="${ref}"]`);
                if (!target || target.tagName.toLowerCase() !== 'select') return false;
                let found = false;
                for (let opt of target.options) {
                    if (opt.value === val || opt.text === val) {
                        target.value = opt.value;
                        found = true;
                        break;
                    }
                }
                if (found) {
                    target.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """
            selected = await page.evaluate(script, [ref, value])
            if not selected:
                return f"选择失败: 下拉框 [{ref}] 中未找到匹配的选项 '{value}'"

            res_msg = f"{hint}\n已在下拉框 [{ref}] 成功选取 '{value}'。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "select_option", url, {"ref": ref, "value": value}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            logger.error(f"[PlaywrightTool] select_option 异常: {e}\n{traceback.format_exc()}")
            return f"选择异常: {str(e)}"

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

        page = ctx.current_page
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
            script = """
            (ref) => {
                const target = document.querySelector(`[data-astr-ref="${ref}"]`);
                if (target) {
                    target.scrollIntoView({behavior: 'smooth', block: 'center'});
                    target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                    target.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """
            hovered = await page.evaluate(script, ref)
            if not hovered:
                return f"悬停失败: 未能定位元素 [{ref}]"

            res_msg = f"{hint}\n已成功悬停在元素 [{ref}] 上。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "hover", url, {"ref": ref}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            logger.error(f"[PlaywrightTool] hover 异常: {e}\n{traceback.format_exc()}")
            return f"悬停异常: {str(e)}"

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

        page = ctx.current_page
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
            script = """
            (ref) => {
                const target = document.querySelector(`[data-astr-ref="${ref}"]`);
                if (target) { target.focus(); return true; }
                return false;
            }
            """
            ok = await page.evaluate(script, ref)
            if not ok:
                return f"聚焦失败: 未能定位元素 [{ref}]"
            res = f"{hint}\n已聚焦到元素 [{ref}]。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "focus", url, {"ref": ref}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            logger.error(f"[PlaywrightTool] focus 异常: {e}\n{traceback.format_exc()}")
            return f"聚焦异常: {str(e)}"

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

        page = ctx.current_page
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
            script = """
            (ref) => {
                const target = document.querySelector(`[data-astr-ref="${ref}"]`);
                if (target) { target.blur(); return true; }
                return false;
            }
            """
            ok = await page.evaluate(script, ref)
            if not ok:
                return f"失焦失败: 未能定位元素 [{ref}]"
            res = f"{hint}\n元素 [{ref}] 已失焦。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "blur", url, {"ref": ref}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            logger.error(f"[PlaywrightTool] blur 异常: {e}\n{traceback.format_exc()}")
            return f"失焦异常: {str(e)}"

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

        page = ctx.current_page
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
            script = """
            ([srcRef, dstRef]) => {
                const src = document.querySelector(`[data-astr-ref="${srcRef}"]`);
                const dst = document.querySelector(`[data-astr-ref="${dstRef}"]`);
                if (!src || !dst) return false;

                const dataTransfer = new DataTransfer();
                src.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer }));
                dst.dispatchEvent(new DragEvent('dragover', { bubbles: true, dataTransfer }));
                dst.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer }));
                src.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer }));
                return true;
            }
            """
            dragged = await page.evaluate(script, [ref, target_ref])
            if not dragged:
                return "拖拽失败: 无法在 DOM 中定位源或目标元素"

            res_msg = f"{hint}\n已成功将元素 [{ref}] 拖拽至 [{target_ref}] 位置。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "drag", url, {"ref": ref, "target_ref": target_ref}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            logger.error(f"[PlaywrightTool] drag 异常: {e}\n{traceback.format_exc()}")
            return f"拖拽异常: {str(e)}"

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

        page = ctx.current_page
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
            if hasattr(page, "keyboard") and hasattr(page.keyboard, "press"):
                await page.keyboard.press(key_name)
            else:
                await page.evaluate(
                    "(k) => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }))",
                    key_name
                )

            res_msg = f"{hint}\n已成功向页面发送按键 '{key_name}'。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "press_key", url, {"key": key_name}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            logger.error(f"[PlaywrightTool] press_key 异常: {e}\n{traceback.format_exc()}")
            return f"按键异常: {str(e)}"

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

        page = ctx.current_page
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
            await page.evaluate("(d) => window.scrollBy(0, d)", delta)
            res_msg = f"{hint}\n页面已向{direction}滚动 {amount} 像素。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "scroll", url, {"direction": direction, "amount": amount}, res_msg, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res_msg
        except Exception as e:
            logger.error(f"[PlaywrightTool] scroll 异常: {e}\n{traceback.format_exc()}")
            return f"滚动异常: {str(e)}"
