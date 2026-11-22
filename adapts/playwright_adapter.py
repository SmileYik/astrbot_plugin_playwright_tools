import os
from typing import TYPE_CHECKING
from .base import BrowserAdapterBase

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright
else:
    try:
        from playwright.async_api import Browser, BrowserContext, Playwright
    except ImportError:
        Browser = None
        BrowserContext = None
        Playwright = None

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

from astrbot.api import logger


class PlaywrightAdapter(BrowserAdapterBase):
    """基于原生 Playwright 的异步浏览器适配器。"""

    def __init__(
        self,
        browser_type: str = "chromium",
        headless: bool = True,
        user_agent: str = "",
        window_width: int = 1280,
        window_height: int = 720,
        executable_path: str = "",
    ):
        super().__init__(
            headless=headless,
            user_agent=user_agent,
            window_width=window_width,
            window_height=window_height,
            executable_path=executable_path,
        )
        self.browser_type = browser_type.lower() if browser_type else "chromium"
        self._playwright_cm = None
        self._playwright = None
        self._browser = None

    @property
    def browser(self) -> "Browser | None":
        """获取当前活跃的 Playwright Browser 实例。"""
        return self._browser

    async def start(self) -> None:
        """启动原生 Playwright 浏览器实例。"""
        if self._browser is not None:
            return

        if async_playwright is None:
            raise RuntimeError(
                "未检测到 playwright 依赖包。请先运行 pip install playwright 进行安装。"
            )

        self._playwright_cm = async_playwright()
        self._playwright = await self._playwright_cm.start()

        browser_launcher = getattr(self._playwright, self.browser_type, None)
        if browser_launcher is None:
            raise ValueError(f"不支持的 Playwright 浏览器类型: {self.browser_type}")

        launch_kwargs = {"headless": self.headless}
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path

        self._browser = await browser_launcher.launch(**launch_kwargs)

        if hasattr(self._browser, "on"):
            def _on_disconnected():
                logger.warning("[PlaywrightAdapter] 检测到底层浏览器进程已断开/崩溃")
                self._browser = None
                self._trigger_disconnect_callbacks()
            try:
                self._browser.on("disconnected", _on_disconnected)
            except Exception as e:
                logger.debug(f"[PlaywrightAdapter] 注册 disconnected 事件监听异常: {e}")

    async def stop(self) -> None:
        """关闭浏览器并释放资源。"""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning(f"[PlaywrightAdapter] 关闭浏览器实例失败: {e}")
            finally:
                self._browser = None

        if self._playwright_cm is not None:
            try:
                await self._playwright_cm.stop()
            except Exception as e:
                logger.warning(f"[PlaywrightAdapter] 停止 Playwright 运行时失败: {e}")
            finally:
                self._playwright_cm = None
                self._playwright = None

    async def create_context(self, storage_state_path: str | None = None) -> "BrowserContext":
        """创建独立的 BrowserContext，应用视口宽高与 user_agent，若 storage_state 文件有效且存在则注入。"""
        if not self.is_running:
            await self.start()

        kwargs = {}
        if self.window_width and self.window_height:
            kwargs["viewport"] = {"width": self.window_width, "height": self.window_height}
        if self.user_agent:
            kwargs["user_agent"] = self.user_agent
        if storage_state_path and os.path.exists(storage_state_path):
            kwargs["storage_state"] = storage_state_path

        context = await self._browser.new_context(**kwargs)
        return context
