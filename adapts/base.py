from abc import ABC, abstractmethod
from typing import Any

class BrowserAdapterBase(ABC):
    """浏览器适配器基类，解耦上层工具逻辑与底层浏览器生命周期。"""

    @abstractmethod
    async def start(self) -> None:
        """启动底层浏览器实例或驱动服务。"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止底层浏览器并释放所有进程资源。"""
        pass

    @abstractmethod
    async def create_context(self, storage_state_path: str | None = None) -> Any:
        """创建全新隔离的浏览器上下文（BrowserContext），可选注入登录态凭证。"""
        pass
