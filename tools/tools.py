import asyncio
import os
import inspect
import traceback
from dataclasses import dataclass, field
from typing import Any

from astrbot.api import logger

try:
    from astrbot.api.all import FunctionTool, AstrAgentContext
    if not isinstance(FunctionTool, type):
        raise ImportError()
except (ImportError, AttributeError):
    try:
        from astrbot.api import FunctionTool
        if not isinstance(FunctionTool, type):
            raise ImportError()
        from astrbot.api.event import AstrMessageEvent as AstrAgentContext
    except (ImportError, AttributeError):
        class FunctionTool:
            def __class_getitem__(cls, item):
                return cls
        class AstrAgentContext:
            pass

from .schemas import PW_PAGE_SCHEMA, PW_READ_SCHEMA, PW_INTERACT_SCHEMA, PW_MEDIA_SCHEMA
from .handlers.base_handler import CallToolResult
from .handlers.page_handler import PageHandler
from .handlers.interact_handler import InteractHandler
from .handlers.media_handler import MediaHandler

ToolExecResult = str | CallToolResult


def _extract_event_and_metadata(context: Any) -> tuple[Any, str, str, str, str]:
    if hasattr(context, "context") and not hasattr(context, "event"):
        agent_ctx = context.context
    else:
        agent_ctx = context

    if hasattr(agent_ctx, "event"):
        event = agent_ctx.event
    elif hasattr(context, "event"):
        event = context.event
    else:
        event = agent_ctx

    session_id = str(getattr(event, "session_id", "default_session"))
    if hasattr(event, "get_sender_id") and callable(event.get_sender_id):
        sender_id = str(event.get_sender_id())
    else:
        sender_id = str(getattr(event, "sender_id", getattr(context, "sender_id", "default_user")))

    sender_name = ""
    if hasattr(event, "get_sender_name") and callable(event.get_sender_name):
        try:
            val = event.get_sender_name()
            if isinstance(val, str) and val.strip():
                sender_name = val.strip()
        except Exception as e:
            logger.debug(f"[PwTools] 获取发送者名称降级: {e}")
    if not sender_name:
        try:
            val = getattr(getattr(getattr(event, "message_obj", None), "sender", None), "nickname", None)
            if isinstance(val, str) and val.strip():
                sender_name = val.strip()
        except Exception as e:
            logger.debug(f"[PwTools] 获取发送者昵称降级: {e}")
    if not sender_name:
        sender_name = sender_id

    session_name = ""
    try:
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj is not None:
            group = getattr(msg_obj, "group", None)
            if group is not None:
                g_name = getattr(group, "group_name", None)
                if isinstance(g_name, str) and g_name.strip():
                    session_name = g_name.strip()
                else:
                    g_id = getattr(group, "group_id", None)
                    if isinstance(g_id, (str, int)) and str(g_id).strip():
                        session_name = f"群聊: {g_id}"
            else:
                session_name = f"私聊: {sender_name}"
    except Exception as e:
        logger.debug(f"[PwTools] 提取 session_name 降级: {e}")

    if not session_name:
        if sender_name and sender_name != sender_id:
            session_name = f"私聊: {sender_name}"
        else:
            session_name = session_id

    return event, session_id, sender_id, session_name, sender_name


def _extract_event_and_ids(context: Any) -> tuple[Any, str, str]:
    ev, s_id, u_id, _, _ = _extract_event_and_metadata(context)
    return ev, s_id, u_id


async def _execute_history_cleaner(cleaner: Any, context: Any, tool_name: str) -> None:
    """在工具执行前执行历史上下文消减检测与副 AI 压缩。无论主代理还是子代理运行均能可靠生效。"""
    
    if not cleaner:
        return
    messages = getattr(context, "messages", None)
    if messages is None:
        inner = getattr(context, "context", None)
        if inner:
            messages = getattr(inner, "messages", None)
    if messages is not None and isinstance(messages, list):
        try:
            ev, _, _, _, _ = _extract_event_and_metadata(context)
            logger.debug(f"[PlaywrightTool] [{tool_name}] 工具执行前检查历史消减 (当前上下文消息数: {len(messages)})")
            await cleaner.process_contexts(ev, messages)
        except Exception as e:
            logger.warning(f"[PlaywrightTool] [{tool_name}] 工具执行前历史消减异常: {e}")


async def _invoke_handler(fn, *args, **kwargs):
    """自适应调用 handler，若其签名不支持部分扩展 kwargs 则自动过滤。"""
    try:
        sig = inspect.signature(fn)
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if not has_varkw:
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
            return await fn(*args, **filtered_kwargs)
    except Exception as e:
        logger.debug(f"[PwTools] 自适应签名反射失败，直接调用: {e}")
    return await fn(*args, **kwargs)


async def _execute_with_timeout(coro, timeout_seconds: int) -> ToolExecResult:
    try:
        if timeout_seconds and timeout_seconds > 0:
            return await asyncio.wait_for(coro, timeout=float(timeout_seconds))
        return await coro
    except asyncio.TimeoutError:
        try:
            coro.close()
        except Exception as ce:
            logger.debug(f"[PwTools] 关闭超时协程异常: {ce}")
        return f"操作超时：执行超过 {timeout_seconds} 秒限制，已强制终止。"
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(f"[PlaywrightTool] 工具执行未预期异常: {e}\n{tb_str}")
        try:
            coro.close()
        except Exception as ce:
            logger.debug(f"[PwTools] 关闭未完成协程异常: {ce}")
        return f"工具执行异常: {str(e)}"


@dataclass
class PwPageTool(FunctionTool[AstrAgentContext]):
    page_handler: PageHandler | None = None
    timeout_seconds: int = 30
    handler: Any = None
    name: str = "pw_page"
    description: str = "管理浏览器页面的打开、标签页切换、弹窗响应与关闭。"
    parameters: dict = field(default_factory=lambda: PW_PAGE_SCHEMA)
    history_cleaner: Any = None

    def __post_init__(self):
        if self.page_handler is None:
            raise ValueError("PwPageTool 初始化必须传入 page_handler")
        page_handler = self.page_handler
        history_cleaner = self.history_cleaner
        timeout_seconds = self.timeout_seconds
        try:
            super().__init__(name=self.name, description=self.description, parameters=self.parameters)
        except Exception:
            pass
        object.__setattr__(self, "page_handler", page_handler)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "history_cleaner", history_cleaner)
        self._actions = {
            "open": self._action_open,
            "switch_tab": self._action_switch_tab,
            "list_tabs": self._action_list_tabs,
            "dialog": self._action_dialog,
            "close": self._action_close,
        }

    async def _action_open(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> ToolExecResult:
        url = kwargs.get("url")
        if not url:
            return "参数错误: action='open' 时必须提供 url 参数"
        return await _invoke_handler(
            self.page_handler.open_url,
            session_id, sender_id, url=str(url),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_switch_tab(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        raw_index = kwargs.get("tab_index")
        try:
            tab_index = int(raw_index) if raw_index is not None and str(raw_index).strip() != "" else 1
        except (ValueError, TypeError):
            tab_index = 1
        return await _invoke_handler(
            self.page_handler.switch_tab,
            session_id, sender_id, tab_index=tab_index,
            session_name=session_name, sender_name=sender_name
        )

    async def _action_list_tabs(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        return await _invoke_handler(
            self.page_handler.list_tabs,
            session_id, sender_id,
            session_name=session_name, sender_name=sender_name
        )

    async def _action_dialog(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        dialog_action = kwargs.get("dialog_action", "accept")
        prompt_text = kwargs.get("prompt_text")
        return await _invoke_handler(
            self.page_handler.handle_dialog,
            session_id, sender_id, action=str(dialog_action), prompt_text=prompt_text,
            session_name=session_name, sender_name=sender_name
        )

    async def _action_close(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        return await _invoke_handler(
            self.page_handler.close_browser,
            session_id, sender_id,
            session_name=session_name, sender_name=sender_name
        )

    async def call(self, context: AstrAgentContext, **kwargs) -> ToolExecResult:
        await _execute_history_cleaner(self.history_cleaner, context, self.name)
        event, session_id, sender_id, session_name, sender_name = _extract_event_and_metadata(context)
        action = kwargs.get("action")
        handler = self._actions.get(action)
        if not handler:
            return f"未知的动作: {action}。支持的动作包括: open, switch_tab, list_tabs, dialog, close"

        res = await _execute_with_timeout(
            handler(session_id, sender_id, session_name=session_name, sender_name=sender_name, **kwargs),
            self.timeout_seconds
        )
        return res


@dataclass
class PwReadTool(FunctionTool[AstrAgentContext]):
    page_handler: PageHandler | None = None
    timeout_seconds: int = 30
    handler: Any = None
    name: str = "pw_read"
    description: str = "读取当前网页的内容与可交互操作元素，支持分页与关键词检索定位。"
    parameters: dict = field(default_factory=lambda: PW_READ_SCHEMA)
    history_cleaner: Any = None

    def __post_init__(self):
        if self.page_handler is None:
            raise ValueError("PwReadTool 初始化必须传入 page_handler")
        page_handler = self.page_handler
        history_cleaner = self.history_cleaner
        timeout_seconds = self.timeout_seconds

        # 尝试从 page_handler.reader 动态读取工具描述
        if hasattr(page_handler, "reader") and hasattr(page_handler.reader, "get_tool_metadata"):
            try:
                meta = page_handler.reader.get_tool_metadata()
                if isinstance(meta, dict) and meta.get("description"):
                    self.description = meta["description"]
            except Exception as e:
                logger.debug(f"[PwTools] 读取 reader 工具描述异常: {e}")

        try:
            super().__init__(name=self.name, description=self.description, parameters=self.parameters)
        except Exception:
            pass
        object.__setattr__(self, "page_handler", page_handler)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "history_cleaner", history_cleaner)

    async def call(self, context: AstrAgentContext, **kwargs) -> ToolExecResult:
        await _execute_history_cleaner(self.history_cleaner, context, self.name)
        event, session_id, sender_id, session_name, sender_name = _extract_event_and_metadata(context)
        raw_page = kwargs.get("page", 1)
        try:
            page = int(raw_page) if raw_page is not None and str(raw_page).strip() != "" else 1
        except (ValueError, TypeError):
            page = 1
        keyword = str(kwargs.get("keyword") or "")
        refresh = bool(kwargs.get("refresh", False))
        ref = str(kwargs.get("ref") or "").strip()

        read_kwargs = {
            "page": page,
            "keyword": keyword,
            "refresh": refresh,
            "session_name": session_name,
            "sender_name": sender_name,
        }
        if ref:
            read_kwargs["ref"] = ref

        res = await _execute_with_timeout(
            _invoke_handler(
                self.page_handler.read_page,
                session_id,
                sender_id,
                **read_kwargs,
            ),
            self.timeout_seconds,
        )
        return res


@dataclass
class PwInteractTool(FunctionTool[AstrAgentContext]):
    interact_handler: InteractHandler | None = None
    timeout_seconds: int = 30
    handler: Any = None
    name: str = "pw_interact"
    description: str = "对页面元素进行点击、输入、选择、鼠标悬停、聚焦/失焦、拖拽、按键及滚动。"
    parameters: dict = field(default_factory=lambda: PW_INTERACT_SCHEMA)
    history_cleaner: Any = None

    def __post_init__(self):
        if self.interact_handler is None:
            raise ValueError("PwInteractTool 初始化必须传入 interact_handler")
        interact_handler = self.interact_handler
        history_cleaner = self.history_cleaner
        timeout_seconds = self.timeout_seconds
        try:
            super().__init__(name=self.name, description=self.description, parameters=self.parameters)
        except Exception:
            pass
        object.__setattr__(self, "interact_handler", interact_handler)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "history_cleaner", history_cleaner)
        self._actions = {
            "click": self._action_click,
            "fill": self._action_fill,
            "select": self._action_select,
            "hover": self._action_hover,
            "focus": self._action_focus,
            "blur": self._action_blur,
            "drag": self._action_drag,
            "press_key": self._action_press_key,
            "scroll": self._action_scroll,
        }

    async def _action_click(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='click' 时必须提供 ref 参数"
        return await _invoke_handler(
            self.interact_handler.click,
            session_id, sender_id, ref=str(ref),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_fill(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        text = kwargs.get("text", "")
        if ref is None:
            return "参数错误: action='fill' 时必须提供 ref 参数"
        return await _invoke_handler(
            self.interact_handler.fill_form,
            session_id, sender_id, ref=str(ref), text=str(text),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_select(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        value = kwargs.get("value", "")
        if ref is None:
            return "参数错误: action='select' 时必须提供 ref 参数"
        return await _invoke_handler(
            self.interact_handler.select_option,
            session_id, sender_id, ref=str(ref), value=str(value),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_hover(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='hover' 时必须提供 ref 参数"
        return await _invoke_handler(
            self.interact_handler.hover,
            session_id, sender_id, ref=str(ref),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_focus(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='focus' 时必须提供 ref 参数"
        return await _invoke_handler(
            self.interact_handler.focus,
            session_id, sender_id, ref=str(ref),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_blur(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='blur' 时必须提供 ref 参数"
        return await _invoke_handler(
            self.interact_handler.blur,
            session_id, sender_id, ref=str(ref),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_drag(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        target_ref = kwargs.get("target_ref")
        if ref is None or target_ref is None:
            return "参数错误: action='drag' 时必须提供 ref 与 target_ref 参数"
        return await _invoke_handler(
            self.interact_handler.drag,
            session_id, sender_id, ref=str(ref), target_ref=str(target_ref),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_press_key(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        key = kwargs.get("key")
        if not key:
            return "参数错误: action='press_key' 时必须提供 key 参数"
        return await _invoke_handler(
            self.interact_handler.press_key,
            session_id, sender_id, key=str(key),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_scroll(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        direction = kwargs.get("direction", "down")
        amount = kwargs.get("amount", 500)
        return await _invoke_handler(
            self.interact_handler.scroll,
            session_id, sender_id, direction=str(direction), amount=int(amount or 500),
            session_name=session_name, sender_name=sender_name
        )

    async def call(self, context: AstrAgentContext, **kwargs) -> ToolExecResult:
        await _execute_history_cleaner(self.history_cleaner, context, self.name)
        event, session_id, sender_id, session_name, sender_name = _extract_event_and_metadata(context)
        action = kwargs.get("action")
        handler = self._actions.get(action)
        if not handler:
            return (
                f"未知的动作: {action}。支持的动作包括: click, fill, select, "
                "hover, focus, blur, drag, press_key, scroll"
            )

        res = await _execute_with_timeout(
            handler(session_id, sender_id, session_name=session_name, sender_name=sender_name, **kwargs),
            self.timeout_seconds
        )
        return res


@dataclass
class PwMediaTool(FunctionTool[AstrAgentContext]):
    media_handler: MediaHandler | None = None
    timeout_seconds: int = 30
    screenshot_max_height_px: int = 8000
    screenshot_timeout_seconds: int = 15
    handler: Any = None
    name: str = "pw_media"
    description: str = "执行当前视口截图、全页面长截图或下载指定文件。"
    parameters: dict = field(default_factory=lambda: PW_MEDIA_SCHEMA)
    history_cleaner: Any = None

    def __post_init__(self):
        if self.media_handler is None:
            raise ValueError("PwMediaTool 初始化必须传入 media_handler")
        media_handler = self.media_handler
        history_cleaner = self.history_cleaner
        timeout_seconds = self.timeout_seconds
        screenshot_max_height_px = self.screenshot_max_height_px
        screenshot_timeout_seconds = self.screenshot_timeout_seconds
        try:
            super().__init__(name=self.name, description=self.description, parameters=self.parameters)
        except Exception:
            pass
        object.__setattr__(self, "media_handler", media_handler)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "screenshot_max_height_px", screenshot_max_height_px)
        object.__setattr__(self, "screenshot_timeout_seconds", screenshot_timeout_seconds)
        object.__setattr__(self, "history_cleaner", history_cleaner)
        self._actions = {
            "screenshot_viewport": self._action_screenshot_viewport,
            "screenshot_full": self._action_screenshot_full,
            "download": self._action_download,
        }

    async def _action_screenshot_viewport(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> ToolExecResult:
        target = kwargs.get("target", "chat")
        return await _invoke_handler(
            self.media_handler.screenshot_viewport,
            session_id, sender_id, target=str(target),
            session_name=session_name, sender_name=sender_name
        )

    async def _action_screenshot_full(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> ToolExecResult:
        target = kwargs.get("target", "chat")
        return await _invoke_handler(
            self.media_handler.screenshot_full,
            session_id,
            sender_id,
            target=str(target),
            max_height_px=self.screenshot_max_height_px,
            timeout_sec=self.screenshot_timeout_seconds,
            session_name=session_name,
            sender_name=sender_name,
        )

    async def _action_download(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "", **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='download' 时必须提供 ref 参数"
        return await _invoke_handler(
            self.media_handler.download_file,
            session_id, sender_id, ref=str(ref),
            session_name=session_name, sender_name=sender_name
        )

    async def call(self, context: AstrAgentContext, **kwargs) -> ToolExecResult:
        await _execute_history_cleaner(self.history_cleaner, context, self.name)
        event, session_id, sender_id, session_name, sender_name = _extract_event_and_metadata(context)
        action = kwargs.get("action")
        handler = self._actions.get(action)
        if not handler:
            return f"未知的动作: {action}。支持的动作包括: screenshot_viewport, screenshot_full, download"

        res = await _execute_with_timeout(
            handler(session_id, sender_id, session_name=session_name, sender_name=sender_name, **kwargs),
            self.timeout_seconds
        )

        target = str(kwargs.get("target", "chat")).lower()
        if (
            action in ("screenshot_viewport", "screenshot_full")
            and target == "chat"
            and isinstance(res, str)
            and res.startswith("[IMAGE_PATH:")
        ):
            img_path = res.split("\n", 1)[0].strip()[len("[IMAGE_PATH:"):].rstrip("]")
            try:
                if hasattr(event, "send") and callable(event.send):
                    from astrbot.core.message.message_event_result import MessageChain
                    await event.send(MessageChain().file_image(img_path))
            except Exception as e:
                logger.warning(f"[PwMediaTool] 自动发送截图至聊天窗口失败: {e}")

        return res
