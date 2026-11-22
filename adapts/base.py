from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext
else:
    try:
        from playwright.async_api import Browser, BrowserContext
    except ImportError:
        Browser = None
        BrowserContext = None

class BrowserAdapterBase(ABC):
    """浏览器适配器基类，解耦上层工具逻辑与底层浏览器生命周期。"""

    def __init__(
        self,
        headless: bool = True,
        user_agent: str = "",
        window_width: int = 1280,
        window_height: int = 720,
        executable_path: str = "",
    ):
        self.headless = headless
        self.user_agent = user_agent
        self.window_width = window_width
        self.window_height = window_height
        self.executable_path = str(executable_path or "").strip()
        self._disconnect_callbacks: list = []

    @property
    def is_running(self) -> bool:
        """底层浏览器进程是否正在运行且保持连接。"""
        b = self.browser
        if b is None:
            return False
        if hasattr(b, "is_connected"):
            try:
                res = b.is_connected()
                return bool(res)
            except Exception:
                return False
        return True

    def set_disconnect_callback(self, cb) -> None:
        """注册底层浏览器崩溃/失联事件的回调函数。"""
        if cb and cb not in self._disconnect_callbacks:
            self._disconnect_callbacks.append(cb)

    def _trigger_disconnect_callbacks(self) -> None:
        """执行所有注册的断开连接回调。"""
        for cb in list(self._disconnect_callbacks):
            try:
                res = cb()
                if hasattr(res, "__await__"):
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception:
                pass

    @property
    @abstractmethod
    def browser(self) -> "Browser | None":
        """获取当前活跃的 Playwright Browser 实例。"""
        pass

    @abstractmethod
    async def start(self) -> None:
        """启动底层浏览器实例或驱动服务。"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止底层浏览器并释放所有进程资源。"""
        pass

    @abstractmethod
    async def create_context(self, storage_state_path: str | None = None) -> "BrowserContext":
        """创建全新隔离的浏览器上下文（BrowserContext），可选注入登录态凭证。"""
        pass
