import os
from typing import TYPE_CHECKING
from .base import BrowserAdapterBase

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext
else:
    try:
        from playwright.async_api import Browser, BrowserContext
    except ImportError:
        Browser = None
        BrowserContext = None

# 动态导入 Camoufox 驱动
try:
    from camoufox.async_api import AsyncCamoufox
except ImportError:
    AsyncCamoufox = None

from astrbot.api import logger

class CamoufoxAdapter(BrowserAdapterBase):
    """基于 Camoufox 的异步浏览器适配器。"""

    def __init__(
        self,
        headless: bool = True,
        geoip: bool = False,
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
        self.geoip = geoip
        self._camoufox_cm = None
        self._browser = None

    @property
    def browser(self) -> "Browser | None":
        """获取当前活跃的 Playwright Browser 实例。"""
        return self._browser

    async def start(self) -> None:
        """启动 Camoufox 浏览器实例并获取 Playwright Browser。"""
        if self._browser is not None:
            return

        if AsyncCamoufox is None:
            raise RuntimeError(
                "未检测到 camoufox 依赖包。请先运行 pip install camoufox[geoip] 进行安装。"
            )

        self._camoufox_cm = AsyncCamoufox(headless=self.headless, geoip=self.geoip)
        self._browser = await self._camoufox_cm.__aenter__()

        if hasattr(self._browser, "on"):
            def _on_disconnected():
                logger.warning("[CamoufoxAdapter] 检测到底层浏览器进程已断开/崩溃")
                self._browser = None
                self._trigger_disconnect_callbacks()
            try:
                self._browser.on("disconnected", _on_disconnected)
            except Exception as e:
                logger.debug(f"[CamoufoxAdapter] 注册 disconnected 事件监听异常: {e}")

    async def stop(self) -> None:
        """关闭浏览器并释放资源。"""
        if self._camoufox_cm is not None:
            try:
                await self._camoufox_cm.__aexit__(None, None, None)
            finally:
                self._camoufox_cm = None
                self._browser = None

    async def create_context(self, storage_state_path: str | None = None) -> "BrowserContext":
        """创建独立的 BrowserContext，若 storage_state 文件有效且存在则注入。"""
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
