import inspect
import re
from typing import TYPE_CHECKING, Any

from ...core.context_manager import ContextManager, BrowserSessionContext
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger
from .base_handler import BaseActionHandler, clean_playwright_error

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator
else:
    Page = Any
    Locator = Any

from astrbot.api import logger


class InteractHandler(BaseActionHandler):
    """页面动作交互处理器 (点击、输入、选择、悬停、聚焦/失焦、拖拽、按键、滚动)。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        mask_password_inputs: bool = True,
        **kwargs,
    ):
        super().__init__(
            context_mgr,
            security_mgr,
            audit_logger,
            mask_password_inputs=mask_password_inputs,
        )

    @staticmethod
    def _get_locator(page: Page, ref: str | int) -> Locator:
        """根据 Ref ID 自动选择定位策略：以 'e' 开头或 '(f\\d+)?e\\d+' 采用 'aria-ref=' 原生定位，其余采用 '[data-astr-ref=]'。"""
        ref_str = str(ref).strip()
        if ref_str.startswith("e") or re.match(r"^(f\d+)?e\d+$", ref_str):
            return page.locator(f"aria-ref={ref_str}")
        return page.locator(f'[data-astr-ref="{ref_str}"]')

    async def click(
        self,
        session_id: str,
        sender_id: str,
        ref: str | int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """点击目标元素。"""

        async def _click(ctx: BrowserSessionContext, page: Page) -> str:
            ref_str = str(ref).strip()
            if ref not in ctx.ref_map and ref_str not in ctx.ref_map:
                return f"点击失败: 无效的元素引用 [{ref}]。页面可能已刷新，请先调用 pw_read() 查看最新元素。"

            el_info = ctx.ref_map.get(ref) or ctx.ref_map.get(ref_str) or {}
            tag = el_info.get("tag", "") if isinstance(el_info, dict) else ""
            text = el_info.get("text", "") if isinstance(el_info, dict) else ""

            locator = self._get_locator(page, ref)
            await locator.click(timeout=10000)
            ctx.is_snapshot_dirty = True

            dialog_info = ""
            if ctx.last_dialog_message:
                dialog_info = f" (触发浏览器弹窗: '{ctx.last_dialog_message}'，已自动处理)"
                ctx.last_dialog_message = None

            tag_part = f" <{tag}>" if tag else ""
            text_part = f" {text}" if text else ""
            return (
                f"已成功点击 [{ref}]{tag_part}{text_part}{dialog_info}\n"
                f"[推荐操作: 若点击引发了页面跳转或内容更新，建议调用 pw_read() 查看最新页面]"
            )

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="click",
            target_resource="",
            action_coro_fn=_click,
            input_args={"ref": str(ref)},
            required_permission="click",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="点击",
        )

    async def fill_form(
        self,
        session_id: str,
        sender_id: str,
        ref: str | int,
        text: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """在表单输入框中填入指定内容。"""

        async def _fill(ctx: BrowserSessionContext, page: Page) -> str:
            ref_str = str(ref).strip()
            if ref not in ctx.ref_map and ref_str not in ctx.ref_map:
                return f"填写失败: 无效的元素引用 [{ref}]"

            el_info = ctx.ref_map.get(ref) or ctx.ref_map.get(ref_str) or {}
            is_pwd = False
            if isinstance(el_info, dict) and el_info.get("type") == "password":
                is_pwd = True

            locator = self._get_locator(page, ref)
            if not is_pwd and hasattr(locator, "get_attribute"):
                try:
                    attr_val = locator.get_attribute("type")
                    if inspect.isawaitable(attr_val):
                        attr_val = await attr_val
                    if attr_val == "password":
                        is_pwd = True
                except Exception:
                    pass

            await locator.fill(str(text), timeout=10000)
            ctx.is_snapshot_dirty = True

            box_type = "密码输入框" if is_pwd else "输入框"
            return (
                f"已成功在{box_type} [{ref}] 填入内容。\n"
                f"[推荐操作: 表单输入完成，可查阅对应提交按钮 Ref 并调用 pw_interact(action='click') 进行提交]"
            )

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="fill_form",
            target_resource="",
            action_coro_fn=_fill,
            input_args={"ref": str(ref), "text": text},
            required_permission="fill",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="填写",
        )

    async def select_option(
        self,
        session_id: str,
        sender_id: str,
        ref: str | int,
        value: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """在下拉选择框中选取指定的值。"""

        async def _select(ctx: BrowserSessionContext, page: Page) -> str:
            ref_str = str(ref).strip()
            if ref not in ctx.ref_map and ref_str not in ctx.ref_map:
                return f"选择失败: 无效的元素引用 [{ref}]"

            locator = self._get_locator(page, ref)
            try:
                await locator.select_option(value=value, timeout=5000)
            except Exception:
                await locator.select_option(label=value, timeout=5000)
            ctx.is_snapshot_dirty = True

            return f"已在下拉框 [{ref}] 成功选取 '{value}'。"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="select_option",
            target_resource="",
            action_coro_fn=_select,
            input_args={"ref": str(ref), "value": value},
            required_permission="select",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="选择",
        )

    async def hover(
        self,
        session_id: str,
        sender_id: str,
        ref: str | int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """将鼠标悬停在目标元素上。"""

        async def _hover(ctx: BrowserSessionContext, page: Page) -> str:
            ref_str = str(ref).strip()
            if ref not in ctx.ref_map and ref_str not in ctx.ref_map:
                return f"悬停失败: 无效的元素引用 [{ref}]"

            locator = self._get_locator(page, ref)
            await locator.hover(timeout=10000)
            return f"已成功悬停在元素 [{ref}] 上。"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="hover",
            target_resource="",
            action_coro_fn=_hover,
            input_args={"ref": str(ref)},
            required_permission="hover",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="悬停",
        )

    async def focus(
        self,
        session_id: str,
        sender_id: str,
        ref: str | int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """将焦点聚集到目标元素。"""

        async def _focus(ctx: BrowserSessionContext, page: Page) -> str:
            ref_str = str(ref).strip()
            if ref not in ctx.ref_map and ref_str not in ctx.ref_map:
                return f"聚焦失败: 无效的元素引用 [{ref}]"

            locator = self._get_locator(page, ref)
            await locator.focus(timeout=10000)
            return f"已聚焦到元素 [{ref}]。"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="focus",
            target_resource="",
            action_coro_fn=_focus,
            input_args={"ref": str(ref)},
            required_permission="focus",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="聚焦",
        )

    async def blur(
        self,
        session_id: str,
        sender_id: str,
        ref: str | int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """使目标元素失去焦点。"""

        async def _blur(ctx: BrowserSessionContext, page: Page) -> str:
            ref_str = str(ref).strip()
            if ref not in ctx.ref_map and ref_str not in ctx.ref_map:
                return f"失焦失败: 无效的元素引用 [{ref}]"

            locator = self._get_locator(page, ref)
            await locator.evaluate("el => el.blur()")
            return f"元素 [{ref}] 已失焦。"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="blur",
            target_resource="",
            action_coro_fn=_blur,
            input_args={"ref": str(ref)},
            required_permission="focus",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="失焦",
        )

    async def drag(
        self,
        session_id: str,
        sender_id: str,
        ref: str | int,
        target_ref: str | int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """将源元素拖拽至目标元素位置。"""

        async def _drag(ctx: BrowserSessionContext, page: Page) -> str:
            ref_str = str(ref).strip()
            target_ref_str = str(target_ref).strip()
            if ref not in ctx.ref_map and ref_str not in ctx.ref_map:
                return f"拖拽失败: 无效的源元素引用 [{ref}]"
            if target_ref not in ctx.ref_map and target_ref_str not in ctx.ref_map:
                return f"拖拽失败: 无效的拖拽目标元素引用 [{target_ref}]"

            source = self._get_locator(page, ref)
            target = self._get_locator(page, target_ref)
            await source.drag_to(target, timeout=10000)
            ctx.is_snapshot_dirty = True

            return f"已成功将元素 [{ref}] 拖拽至 [{target_ref}] 位置。"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="drag",
            target_resource="",
            action_coro_fn=_drag,
            input_args={"ref": str(ref), "target_ref": str(target_ref)},
            required_permission="drag",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="拖拽",
        )

    async def press_key(
        self,
        session_id: str,
        sender_id: str,
        key: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """向当前页面或已聚焦元素发送键盘按键。"""
        key_name = (key or "").strip()
        if not key_name:
            return "按键失败: 请提供有效的按键名称"

        async def _press(ctx: BrowserSessionContext, page: Page) -> str:
            await page.keyboard.press(key_name)
            ctx.is_snapshot_dirty = True
            return f"已成功向页面发送按键 '{key_name}'。"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="press_key",
            target_resource="",
            action_coro_fn=_press,
            input_args={"key": key_name},
            required_permission="press_key",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="按键",
        )

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

        async def _scroll(ctx: BrowserSessionContext, page: Page) -> str:
            delta = amount if direction.lower() == "down" else -amount
            if hasattr(page, "mouse") and hasattr(page.mouse, "wheel"):
                await page.mouse.wheel(0, delta)
            else:
                await page.evaluate("(d) => window.scrollBy(0, d)", delta)

            dir_name = (
                "下"
                if direction.lower() == "down"
                else ("上" if direction.lower() == "up" else direction)
            )
            return f"页面已向{dir_name}滚动 {amount} 像素。"

        return await self.execute_action(
            session_id=session_id,
            sender_id=sender_id,
            action_name="scroll",
            target_resource="",
            action_coro_fn=_scroll,
            input_args={"direction": direction, "amount": amount},
            required_permission="scroll",
            session_name=session_name,
            sender_name=sender_name,
            action_desc="滚动",
        )
