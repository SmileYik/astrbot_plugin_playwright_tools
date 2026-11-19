import os
from typing import Any
from .base import BrowserAdapterBase

# 支持外部 mock 或动态导入
try:
    from camoufox.async_api import AsyncCamoufox
except ImportError:
    AsyncCamoufox = None

class CamoufoxAdapter(BrowserAdapterBase):
    """基于 Camoufox (反指纹 Firefox) 的异步浏览器适配器。"""

    def __init__(self, headless: bool = True, geoip: bool = False):
        self.headless = headless
        self.geoip = geoip
        self._camoufox_cm = None
        self._browser = None

    async def start(self) -> None:
        """启动 Camoufox 浏览器实例。"""
        if self._browser is not None:
            return

        if AsyncCamoufox is None:
            raise RuntimeError(
                "未检测到 camoufox 依赖包。请先运行 pip install camoufox[geoip] 进行安装。"
            )

        self._camoufox_cm = AsyncCamoufox(headless=self.headless, geoip=self.geoip)
        self._browser = await self._camoufox_cm.__aenter__()

    async def stop(self) -> None:
        """关闭浏览器并释放资源。"""
        if self._camoufox_cm is not None:
            try:
                await self._camoufox_cm.__aexit__(None, None, None)
            finally:
                self._camoufox_cm = None
                self._browser = None

    async def create_context(self, storage_state_path: str | None = None) -> Any:
        """创建独立的 BrowserContext，若 storage_state 文件有效且存在则注入。"""
        if self._browser is None:
            await self.start()

        kwargs = {}
        if storage_state_path and os.path.exists(storage_state_path):
            kwargs["storage_state"] = storage_state_path

        context = await self._browser.new_context(**kwargs)
        return context
