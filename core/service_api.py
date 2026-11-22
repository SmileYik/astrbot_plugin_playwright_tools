import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext
    from .context_manager import ContextManager
    from ..main import PlaywrightToolPlugin


class PlaywrightServiceAPI:
    """供其他 AstrBot 插件接入的 Playwright 共享浏览器基座服务。

    遵循 AstrBot Star 寻址机制，外部插件可通过:
    ```python
    meta = self.context.get_registered_star("astrbot_plugin_playwright_tools")
    if meta and meta.star_cls:
        service = meta.star_cls.service
        async with service.context("my_plugin") as b_ctx:
            page = await b_ctx.new_page()
            await page.goto("https://example.com")
    ```
    安全获取专属隔离的 BrowserContext，具备独立空闲淘汰与静默保活能力。
    """

    def __init__(self, plugin: Any, context_manager: Any):
        self._plugin = plugin
        self._context_mgr = context_manager
        self._ready_event = asyncio.Event()

    @property
    def ready(self) -> bool:
        """底层浏览器引擎是否已完成初始化并就绪。"""
        return self._ready_event.is_set()

    def set_ready(self) -> None:
        """标记浏览器基座服务已就绪。"""
        self._ready_event.set()

    async def wait_ready(self, timeout: float = 30.0) -> bool:
        """等待浏览器服务就绪，超时抛出 TimeoutError。"""
        if self._ready_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            raise TimeoutError(f"等待 Playwright 浏览器基座服务就绪超时 ({timeout}s)")

    async def get_browser_context(
        self,
        plugin_name: str,
        idle_timeout_minutes: int | None = None,
        clean: bool = False,
        timeout: float = 30.0,
    ) -> Any:
        """获取指定外部插件专用的原生 Playwright BrowserContext。

        Args:
            plugin_name: 外部插件名称，用于多租户隔离与配额审计
            idle_timeout_minutes: 独立空闲超时（分钟），若为 None 则默认沿用全局 runtime 配置
            clean: 是否强制关闭已有上下文并全新实例化
            timeout: 等待服务就绪超时秒数
        """
        if not plugin_name or not str(plugin_name).strip():
            raise ValueError("plugin_name 不能为空")
        plugin_name = str(plugin_name).strip()

        await self.wait_ready(timeout=timeout)

        session_ctx = await self._context_mgr.get_or_create_external_context(
            plugin_name=plugin_name,
            idle_timeout_minutes=idle_timeout_minutes,
            clean=clean,
        )
        return session_ctx.browser_context

    async def release_browser_context(self, plugin_name: str) -> bool:
        """外部插件主动释放专用的 BrowserContext。"""
        if not plugin_name or not str(plugin_name).strip():
            return False
        return await self._context_mgr.release_external_context(str(plugin_name).strip())

    @asynccontextmanager
    async def context(
        self,
        plugin_name: str,
        idle_timeout_minutes: int | None = None,
        clean: bool = False,
        timeout: float = 30.0,
    ) -> AsyncIterator[Any]:
        """异步上下文管理器模式：获取 BrowserContext，在代码块执行完毕退出时自动触发主动释放。"""
        b_ctx = await self.get_browser_context(
            plugin_name=plugin_name,
            idle_timeout_minutes=idle_timeout_minutes,
            clean=clean,
            timeout=timeout,
        )
        try:
            yield b_ctx
        finally:
            await self.release_browser_context(plugin_name)
