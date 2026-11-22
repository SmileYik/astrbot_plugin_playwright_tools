import inspect
import re
import traceback
from typing import TYPE_CHECKING, Any, Callable, Awaitable

from ...core.context_manager import ContextManager, BrowserSessionContext
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator
else:
    Page = Any
    Locator = Any

from astrbot.api import logger


ACTION_DESC_MAP = {
    "click": "点击",
    "fill": "填写",
    "fill_form": "填写",
    "select": "选择",
    "select_option": "选择",
    "hover": "悬停",
    "focus": "聚焦",
    "blur": "失焦",
    "drag": "拖拽",
    "press_key": "按键",
    "scroll": "滚动",
    "open_url": "打开",
    "read_page": "读取",
    "switch_tab": "切换",
    "handle_dialog": "配置",
    "close_browser": "关闭",
    "screenshot_viewport": "截图",
    "screenshot_full": "截图",
    "download_file": "下载",
}


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
    if ("Timeout" in raw or "timeout" in raw) and "waiting for locator" in raw:
        return (
            "操作超时 (10秒): 未能定位到目标元素或元素不可见/不可点击。\n"
            "[推荐操作: 页面可能已动态更新，请先调用 pw_read() 获取最新可用元素]"
        )

    # 检查通用超时
    if "Timeout" in raw or "timeout" in raw or isinstance(e, TimeoutError):
        return "操作超时 (10秒): 执行未在规定时间内完成。\n[推荐操作: 可检查网络或页面加载状态后重试]"

    # 剥离 Call log
    if "Call log:" in raw:
        clean_first_line = raw.split("Call log:")[0].strip()
        return f"操作异常: {clean_first_line}\n[推荐操作: 检查参数与页面状态后重试]"

    first_line = raw.splitlines()[0] if raw.splitlines() else str(raw)
    return f"操作异常: {first_line}\n[推荐操作: 检查参数与页面状态后重试]"


class BaseActionHandler:
    """通用动作处理器基类，提供统一的执行切面、鉴权、审计、稳定等待及密码脱敏。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        mask_password_inputs: bool = True,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger
        self.mask_password_inputs = mask_password_inputs

    @staticmethod
    def _is_timeout_error(e: Exception) -> bool:
        if isinstance(e, TimeoutError):
            return True
        name = type(e).__name__.lower()
        if "timeout" in name:
            return True
        msg = str(e).lower()
        return "timeout" in msg

    async def wait_page_stable(self, page: Page, timeout: float = 1.5) -> None:
        """等待页面达到稳定状态：domcontentloaded (10s) + networkidle (熔断超时)。"""
        if page is None or not hasattr(page, "wait_for_load_state"):
            return

        timeout_ms = int(timeout * 1000)
        try:
            ret = page.wait_for_load_state("domcontentloaded", timeout=10000)
            if inspect.isawaitable(ret):
                await ret
        except Exception as e:
            if not self._is_timeout_error(e):
                logger.warning(f"[PlaywrightTool] wait_page_stable domcontentloaded 异常: {e}")

        try:
            ret = page.wait_for_load_state("networkidle", timeout=timeout_ms)
            if inspect.isawaitable(ret):
                await ret
        except Exception as e:
            if not self._is_timeout_error(e):
                logger.warning(f"[PlaywrightTool] wait_page_stable networkidle 异常: {e}")

    async def _resolve_context(
        self,
        session_id: str,
        sender_id: str,
        session_name: str = "",
        sender_name: str = "",
    ) -> tuple[BrowserSessionContext | None, str]:
        """统一上下文寻址助手。"""
        try:
            res = self.context_mgr.resolve_context(
                session_id, sender_id, session_name=session_name, sender_name=sender_name
            )
            if inspect.isawaitable(res):
                res = await res
        except TypeError:
            res = self.context_mgr.resolve_context(session_id, sender_id)
            if inspect.isawaitable(res):
                res = await res

        if isinstance(res, tuple):
            return res
        return res, ""

    async def _log_audit(self, **kwargs) -> None:
        """安全调用 AuditLogger.log_action。"""
        if hasattr(self.audit_logger, "log_action"):
            ret = self.audit_logger.log_action(**kwargs)
            if inspect.isawaitable(ret):
                await ret

    async def execute_action(
        self,
        session_id: str,
        sender_id: str,
        action_name: str,
        target_resource: str,
        action_coro_fn: Callable[[BrowserSessionContext, Page], Awaitable[str]],
        input_args: dict[str, Any] | None = None,
        required_permission: str = "",
        session_name: str = "",
        sender_name: str = "",
        wait_stabilize: bool = False,
        action_desc: str = "",
    ) -> str:
        """统一切面执行模板方法：鉴权、上下文校验、稳定等待、密码脱敏、执行调度与审计。"""
        ctx, hint = await self._resolve_context(
            session_id, sender_id, session_name=session_name, sender_name=sender_name
        )
        if ctx is None:
            return "操作失败: 无法获取浏览器上下文"

        page = getattr(ctx, "current_page", None)
        page_url = getattr(page, "url", "") if page else ""
        current_url = target_resource or page_url

        if not action_desc:
            action_desc = ACTION_DESC_MAP.get(action_name, action_name or "操作")

        input_args = dict(input_args or {})
        audit_input_args = dict(input_args)

        # 密码类型探测
        is_password = False
        ref = input_args.get("ref")
        if ref is not None:
            ref_map = getattr(ctx, "ref_map", {}) or {}
            el_info = ref_map.get(ref) or ref_map.get(str(ref))
            if isinstance(el_info, dict) and el_info.get("type") == "password":
                is_password = True
            elif page is not None and hasattr(page, "locator"):
                try:
                    ref_str = str(ref)
                    if ref_str.startswith("e") or (ref_str.startswith("f") and "e" in ref_str):
                        loc = page.locator(f"aria-ref={ref_str}")
                    else:
                        loc = page.locator(f'[data-astr-ref="{ref_str}"]')
                    if hasattr(loc, "get_attribute"):
                        attr_val = loc.get_attribute("type")
                        if inspect.isawaitable(attr_val):
                            attr_val = await attr_val
                        if attr_val == "password":
                            is_password = True
                except Exception:
                    pass

        if (
            input_args.get("is_password")
            or input_args.get("type") == "password"
            or "password" in action_name.lower()
        ):
            is_password = True

        secret_text = None
        if is_password and self.mask_password_inputs:
            for key in ("text", "value", "password"):
                if key in audit_input_args:
                    val = str(audit_input_args[key])
                    if val:
                        secret_text = val
                    audit_input_args[key] = "******"

        # 确定鉴权主体
        is_session_mode = getattr(self.context_mgr, "mode", "personal") == "session"
        if is_session_mode:
            auth_user_id = sender_id
            ctx.current_operator_id = sender_id
        else:
            allowed_users = getattr(ctx, "allowed_users", set()) or set()
            if sender_id in allowed_users and sender_id != getattr(ctx, "owner_id", ""):
                auth_user_id = ctx.owner_id
                ctx.current_operator_id = ctx.owner_id
            else:
                auth_user_id = sender_id
                ctx.current_operator_id = sender_id

        # 鉴权检查
        if required_permission:
            if (
                required_permission == "navigate" or action_name == "open_url"
            ) and hasattr(self.security_mgr, "is_url_allowed_navigation"):
                allowed, reason = self.security_mgr.is_url_allowed_navigation(
                    auth_user_id, current_url
                )
            else:
                allowed, reason = self.security_mgr.check_permission(
                    auth_user_id, current_url, required_permission
                )
            if not allowed:
                await self._log_audit(
                    session_id=session_id,
                    context_key=f"{session_id}:{ctx.owner_id}",
                    sender_id=sender_id,
                    tool_name=action_name,
                    url=current_url,
                    input_args=audit_input_args,
                    output_result=reason,
                    is_permitted=False,
                    deny_reason=reason,
                    session_name=session_name,
                    sender_name=sender_name,
                )
                return f"{action_desc}失败: {reason}"

        # 页面稳定等待
        if wait_stabilize and page is not None:
            await self.wait_page_stable(page)

        # 业务调度执行
        try:
            try:
                coro = action_coro_fn(ctx, page)
            except TypeError:
                try:
                    coro = action_coro_fn(ctx)
                except TypeError:
                    coro = action_coro_fn()

            res = await coro if inspect.isawaitable(coro) else coro
            extra_audit = {}
            if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict):
                res, extra_audit = res
            res = str(res)

            if hint and hint not in res:
                res = f"{hint}\n{res}".strip()

            if is_password and self.mask_password_inputs and secret_text:
                res = res.replace(secret_text, "******")

            await self._log_audit(
                session_id=session_id,
                context_key=f"{session_id}:{ctx.owner_id}",
                sender_id=sender_id,
                tool_name=action_name,
                url=current_url,
                input_args=audit_input_args,
                output_result=res,
                is_permitted=True,
                session_name=session_name,
                sender_name=sender_name,
                **extra_audit,
            )
            return res
        except Exception as e:
            tb_str = traceback.format_exc()
            err_str = str(e)
            clean_err = clean_playwright_error(e)

            if is_password and self.mask_password_inputs and secret_text:
                tb_str = tb_str.replace(secret_text, "******")
                err_str = err_str.replace(secret_text, "******")
                clean_err = clean_err.replace(secret_text, "******")

            logger.error(f"[PlaywrightTool] {action_name} 异常: {err_str}\n{tb_str}")
            full_error = f"{type(e).__name__}: {err_str}\n\n{tb_str}" if tb_str else err_str
            await self._log_audit(
                session_id=session_id,
                context_key=f"{session_id}:{ctx.owner_id}",
                sender_id=sender_id,
                tool_name=action_name,
                url=current_url,
                input_args=audit_input_args,
                output_result=clean_err,
                is_permitted=True,
                is_error=True,
                error_message=full_error,
                session_name=session_name,
                sender_name=sender_name,
            )
            return clean_err
