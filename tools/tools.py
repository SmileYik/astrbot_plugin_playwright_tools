import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

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

from tools.schemas import PW_PAGE_SCHEMA, PW_INTERACT_SCHEMA, PW_MEDIA_SCHEMA
from tools.handlers.page_handler import PageHandler
from tools.handlers.interact_handler import InteractHandler
from tools.handlers.media_handler import MediaHandler


def _extract_event_and_ids(context: Any) -> tuple[Any, str, str]:
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

    session_id = getattr(event, "session_id", "default_session")
    if hasattr(event, "get_sender_id") and callable(event.get_sender_id):
        sender_id = str(event.get_sender_id())
    else:
        sender_id = str(getattr(event, "sender_id", getattr(context, "sender_id", "default_user")))
    return event, session_id, sender_id


async def _execute_with_timeout(coro, timeout_seconds: int) -> str:
    try:
        if timeout_seconds and timeout_seconds > 0:
            return await asyncio.wait_for(coro, timeout=float(timeout_seconds))
        return await coro
    except asyncio.TimeoutError:
        try:
            coro.close()
        except Exception:
            pass
        return f"操作超时：执行超过 {timeout_seconds} 秒限制，已强制终止。"
    except Exception as e:
        try:
            coro.close()
        except Exception:
            pass
        return f"工具执行异常: {str(e)}"


@dataclass
class PwPageTool(FunctionTool[AstrAgentContext]):
    page_handler: PageHandler
    timeout_seconds: int = 30
    handler: Any = None
    name: str = "pw_page"
    description: str = "管理浏览器页面的打开、内容读取、关键字搜索、标签页切换、弹窗响应与关闭。"
    parameters: dict = field(default_factory=lambda: PW_PAGE_SCHEMA)

    def __post_init__(self):
        try:
            super().__init__(name=self.name, description=self.description, parameters=self.parameters)
        except Exception:
            pass
        self._actions = {
            "open": self._action_open,
            "read": self._action_read,
            "search": self._action_search,
            "switch_tab": self._action_switch_tab,
            "dialog": self._action_dialog,
            "close": self._action_close,
        }

    async def _action_open(self, session_id: str, sender_id: str, **kwargs) -> str:
        url = kwargs.get("url")
        if not url:
            return "参数错误: action='open' 时必须提供 url 参数"
        return await self.page_handler.open_url(session_id, sender_id, url=str(url))

    async def _action_read(self, session_id: str, sender_id: str, **kwargs) -> str:
        page = kwargs.get("page", 1)
        return await self.page_handler.read_page(session_id, sender_id, page=int(page or 1))

    async def _action_search(self, session_id: str, sender_id: str, **kwargs) -> str:
        keyword = kwargs.get("keyword")
        if not keyword:
            return "参数错误: action='search' 时必须提供 keyword 参数"
        return await self.page_handler.search_page(session_id, sender_id, keyword=str(keyword))

    async def _action_switch_tab(self, session_id: str, sender_id: str, **kwargs) -> str:
        tab_index = kwargs.get("tab_index", 0)
        return await self.page_handler.switch_tab(session_id, sender_id, tab_index=int(tab_index or 0))

    async def _action_dialog(self, session_id: str, sender_id: str, **kwargs) -> str:
        dialog_action = kwargs.get("dialog_action", "accept")
        prompt_text = kwargs.get("prompt_text")
        return await self.page_handler.handle_dialog(
            session_id, sender_id, action=str(dialog_action), prompt_text=prompt_text
        )

    async def _action_close(self, session_id: str, sender_id: str, **kwargs) -> str:
        return await self.page_handler.close_browser(session_id, sender_id)

    async def call(self, context: AstrAgentContext, **kwargs):
        event, session_id, sender_id = _extract_event_and_ids(context)
        action = kwargs.get("action")
        handler = self._actions.get(action)
        if not handler:
            yield f"未知的动作: {action}。支持的动作包括: open, read, search, switch_tab, dialog, close"
            return

        res = await _execute_with_timeout(handler(session_id, sender_id, **kwargs), self.timeout_seconds)
        yield res


@dataclass
class PwInteractTool(FunctionTool[AstrAgentContext]):
    interact_handler: InteractHandler
    timeout_seconds: int = 30
    handler: Any = None
    name: str = "pw_interact"
    description: str = "对页面元素进行点击、输入、选择、鼠标悬停、聚焦/失焦、拖拽、按键及滚动。"
    parameters: dict = field(default_factory=lambda: PW_INTERACT_SCHEMA)

    def __post_init__(self):
        try:
            super().__init__(name=self.name, description=self.description, parameters=self.parameters)
        except Exception:
            pass
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

    async def _action_click(self, session_id: str, sender_id: str, **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='click' 时必须提供 ref 参数"
        return await self.interact_handler.click(session_id, sender_id, ref=int(ref))

    async def _action_fill(self, session_id: str, sender_id: str, **kwargs) -> str:
        ref = kwargs.get("ref")
        text = kwargs.get("text", "")
        if ref is None:
            return "参数错误: action='fill' 时必须提供 ref 参数"
        return await self.interact_handler.fill_form(session_id, sender_id, ref=int(ref), text=str(text))

    async def _action_select(self, session_id: str, sender_id: str, **kwargs) -> str:
        ref = kwargs.get("ref")
        value = kwargs.get("value", "")
        if ref is None:
            return "参数错误: action='select' 时必须提供 ref 参数"
        return await self.interact_handler.select_option(session_id, sender_id, ref=int(ref), value=str(value))

    async def _action_hover(self, session_id: str, sender_id: str, **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='hover' 时必须提供 ref 参数"
        return await self.interact_handler.hover(session_id, sender_id, ref=int(ref))

    async def _action_focus(self, session_id: str, sender_id: str, **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='focus' 时必须提供 ref 参数"
        return await self.interact_handler.focus(session_id, sender_id, ref=int(ref))

    async def _action_blur(self, session_id: str, sender_id: str, **kwargs) -> str:
        ref = kwargs.get("ref")
        if ref is None:
            return "参数错误: action='blur' 时必须提供 ref 参数"
        return await self.interact_handler.blur(session_id, sender_id, ref=int(ref))

    async def _action_drag(self, session_id: str, sender_id: str, **kwargs) -> str:
        ref = kwargs.get("ref")
        target_ref = kwargs.get("target_ref")
        if ref is None or target_ref is None:
            return "参数错误: action='drag' 时必须提供 ref 与 target_ref 参数"
        return await self.interact_handler.drag(session_id, sender_id, ref=int(ref), target_ref=int(target_ref))

    async def _action_press_key(self, session_id: str, sender_id: str, **kwargs) -> str:
        key = kwargs.get("key")
        if not key:
            return "参数错误: action='press_key' 时必须提供 key 参数"
        return await self.interact_handler.press_key(session_id, sender_id, key=str(key))

    async def _action_scroll(self, session_id: str, sender_id: str, **kwargs) -> str:
        direction = kwargs.get("direction", "down")
        amount = kwargs.get("amount", 500)
        return await self.interact_handler.scroll(
            session_id, sender_id, direction=str(direction), amount=int(amount or 500)
        )

    async def call(self, context: AstrAgentContext, **kwargs):
        event, session_id, sender_id = _extract_event_and_ids(context)
        action = kwargs.get("action")
        handler = self._actions.get(action)
        if not handler:
            yield (
                f"未知的动作: {action}。支持的动作包括: click, fill, select, "
                "hover, focus, blur, drag, press_key, scroll"
            )
            return

        res = await _execute_with_timeout(handler(session_id, sender_id, **kwargs), self.timeout_seconds)
        yield res


@dataclass
class PwMediaTool(FunctionTool[AstrAgentContext]):
    media_handler: MediaHandler
    timeout_seconds: int = 30
    screenshot_max_height_px: int = 8000
    screenshot_timeout_seconds: int = 15
    handler: Any = None
    name: str = "pw_media"
    description: str = "执行当前视口截图、全页面长截图或下载指定文件。"
    parameters: dict = field(default_factory=lambda: PW_MEDIA_SCHEMA)

    def __post_init__(self):
        try:
            super().__init__(name=self.name, description=self.description, parameters=self.parameters)
        except Exception:
            pass

    async def call(self, context: AstrAgentContext, **kwargs) -> str:
        async def _dispatch():
            event, session_id, sender_id = _extract_event_and_ids(context)
            action = kwargs.get("action")

            if action == "screenshot_viewport":
                target = kwargs.get("target", "chat")
                res = await self.media_handler.screenshot_viewport(session_id, sender_id, target=str(target))
                if target.lower() == "chat" and res.startswith("[IMAGE_PATH:"):
                    lines = res.split("\n", 1)
                    img_path = lines[0][len("[IMAGE_PATH:"):-1]
                    note = f"\n{lines[1]}" if len(lines) > 1 else ""
                    try:
                        from astrbot.api.message_components import Image
                        from astrbot.api.event import MessageChain
                        chain = None
                        if hasattr(Image, "fromFileSystem"):
                            chain = MessageChain([Image.fromFileSystem(img_path)])
                        if chain and hasattr(event, "send") and callable(event.send):
                            await event.send(chain)
                            return f"视口截图已生成并发送至聊天。{note}".strip()
                    except Exception:
                        pass
                return res

            elif action == "screenshot_full":
                target = kwargs.get("target", "chat")
                res = await self.media_handler.screenshot_full(
                    session_id,
                    sender_id,
                    target=str(target),
                    max_height_px=self.screenshot_max_height_px,
                    timeout_sec=self.screenshot_timeout_seconds,
                )
                if target.lower() == "chat" and res.startswith("[IMAGE_PATH:"):
                    lines = res.split("\n", 1)
                    img_path = lines[0][len("[IMAGE_PATH:"):-1]
                    note = f"\n{lines[1]}" if len(lines) > 1 else ""
                    try:
                        from astrbot.api.message_components import Image
                        from astrbot.api.event import MessageChain
                        chain = None
                        if hasattr(Image, "fromFileSystem"):
                            chain = MessageChain([Image.fromFileSystem(img_path)])
                        if chain and hasattr(event, "send") and callable(event.send):
                            await event.send(chain)
                            return f"长截图已生成并发送至聊天。{note}".strip()
                    except Exception:
                        pass
                return res

            elif action == "download":
                ref = kwargs.get("ref")
                if ref is None:
                    return "参数错误: action='download' 时必须提供 ref 参数"
                res = await self.media_handler.download_file(session_id, sender_id, ref=int(ref))
                if res.startswith("[FILE_PATH:"):
                    lines = res.split("\n", 1)
                    fpath = lines[0][len("[FILE_PATH:"):-1]
                    try:
                        from astrbot.api.message_components import File
                        from astrbot.api.event import MessageChain
                        chain = None
                        if hasattr(File, "fromFileSystem"):
                            chain = MessageChain([File.fromFileSystem(fpath)])
                        if chain and hasattr(event, "send") and callable(event.send):
                            await event.send(chain)
                            return f"文件已下载并发送至聊天: {os.path.basename(fpath)}"
                    except Exception:
                        pass
                return res

            else:
                return f"未知的动作: {action}。支持的动作包括: screenshot_viewport, screenshot_full, download"

        return await _execute_with_timeout(_dispatch(), self.timeout_seconds)
