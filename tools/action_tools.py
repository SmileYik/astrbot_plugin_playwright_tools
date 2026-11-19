from ..core.context_manager import ContextManager
from ..core.security_manager import SecurityManager
from ..core.audit_logger import AuditLogger

class ActionTools:
    """页面动作交互工具集 (点击、输入、选择、滚动)。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger

    async def click(self, session_id: str, sender_id: str, ref: int) -> str:
        """点击页面中的目标元素。

        Args:
            ref(number): 页面快照中分配的元素编号 Ref ID
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "click")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, reason, is_permitted=False, deny_reason=reason
            )
            return f"点击失败: {reason}"

        if ref not in ctx.ref_map:
            return f"点击失败: 无效的元素引用 [{ref}]。页面可能已发生刷新或跳转，请先调用 read_page() 获取最新元素。"

        el_info = ctx.ref_map[ref]
        tag = el_info.get("tag", "")
        text = el_info.get("text", "")

        try:
            # 严格依据 data-astr-ref 属性精确定位并触发原生点击
            script = f"""
            (() => {{
                const target = document.querySelector('[data-astr-ref="{ref}"]');
                if (target) {{
                    target.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                    target.click();
                    return true;
                }}
                return false;
            }})()
            """
            clicked = await page.evaluate(script)
            if not clicked:
                return f"点击失败: 未能正确定位元素 [{ref}]"

            dialog_info = ""
            if ctx.last_dialog_message:
                dialog_info = f" (触发浏览器弹窗: '{ctx.last_dialog_message}'，已自动处理)"
                ctx.last_dialog_message = None

            res_msg = f"{hint}\n已成功点击 [{ref}] <{tag}> {text}{dialog_info}".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, res_msg, is_permitted=True
            )
            return res_msg
        except Exception as e:
            err_msg = f"点击操作异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "click", url, {"ref": ref}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e)
            )
            return err_msg

    async def fill_form(self, session_id: str, sender_id: str, ref: int, text: str) -> str:
        """在表单输入框中填入指定内容。

        Args:
            ref(number): 页面快照中的输入框编号 Ref ID
            text(string): 需要填入的文本内容
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "fill")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, reason, is_permitted=False, deny_reason=reason
            )
            return f"填写失败: {reason}"

        if ref not in ctx.ref_map:
            return f"填写失败: 无效的元素引用 [{ref}]，请先调用 read_page() 获取最新元素。"

        try:
            script = f"""
            (() => {{
                const target = document.querySelector('[data-astr-ref="{ref}"]');
                if (target) {{
                    target.value = {repr(text)};
                    target.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    target.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}
                return false;
            }})()
            """
            filled = await page.evaluate(script)
            if not filled:
                return f"填写失败: 未能定位输入框 [{ref}]"

            res_msg = f"{hint}\n已成功在输入框 [{ref}] 填入内容。".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, res_msg, is_permitted=True
            )
            return res_msg
        except Exception as e:
            err_msg = f"填写表单异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "fill_form", url, {"ref": ref, "text": text}, err_msg, is_permitted=True,
                is_error=True, error_message=str(e)
            )
            return err_msg

    async def select_option(self, session_id: str, sender_id: str, ref: int, value: str) -> str:
        """选择下拉框中的选项。

        Args:
            ref(number): 下拉框编号 Ref ID
            value(string): 需要选中的选项值或显示文本
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "fill")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "select_option", url, {"ref": ref, "value": value}, reason, is_permitted=False, deny_reason=reason
            )
            return f"选择失败: {reason}"

        if ref not in ctx.ref_map:
            return f"选择失败: 无效的元素引用 [{ref}]"

        try:
            script = f"""
            (() => {{
                const target = document.querySelector('[data-astr-ref="{ref}"]');
                if (target && target.tagName.toLowerCase() === 'select') {{
                    for (let opt of target.options) {{
                        if (opt.value === {repr(value)} || opt.text === {repr(value)}) {{
                            opt.selected = true;
                            target.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return true;
                        }}
                    }}
                }}
                return false;
            }})()
            """
            selected = await page.evaluate(script)
            if not selected:
                return f"选择失败: 未找到匹配选项 '{value}'"

            res_msg = f"{hint}\n已成功在下拉选择 [{ref}] 选中 '{value}'".strip()
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "select_option", url, {"ref": ref, "value": value}, res_msg, is_permitted=True
            )
            return res_msg
        except Exception as e:
            err_msg = f"选择异常: {str(e)}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "select_option", url, {"ref": ref, "value": value}, err_msg,
                is_permitted=True, is_error=True, error_message=str(e)
            )
            return err_msg

    async def scroll(self, session_id: str, sender_id: str, direction: str = "down", amount: int = 500) -> str:
        """滚动当前页面。

        Args:
            direction(string): 滚动方向 (down, up)
            amount(number): 滚动距离像素数 (默认 500)
        """
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
                is_permitted=False, deny_reason=reason
            )
            return f"滚动失败: {reason}"

        delta = amount if direction.lower() == "down" else -amount
        await page.evaluate(f"window.scrollBy(0, {delta})")
        res_msg = f"{hint}\n页面已向{direction}滚动 {amount} 像素。".strip()
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "scroll", url, {"direction": direction, "amount": amount}, res_msg, is_permitted=True
        )
        return res_msg
