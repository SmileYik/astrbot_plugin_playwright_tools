from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any


@dataclass
class PageSnapshot:
    """页面快照结构，保存阅读器提炼后的正文数据与 Ref 元素映射。"""
    title: str
    url: str
    raw_content: Any
    ref_map: dict[str, dict]
    total_pages: int
    chunks: list[str]
    timestamp: float = field(default_factory=time.time)


class BasePageReader(ABC):
    """页面内容提炼与分页阅读抽象基类（策略模式）。"""

    def __init__(self, chunk_char_limit: int = 2000, mask_passwords: bool = True):
        self.chunk_char_limit = chunk_char_limit
        self.mask_passwords = mask_passwords

    @abstractmethod
    async def extract_snapshot(self, page: Any, url: str = "") -> PageSnapshot:
        """从 Playwright 页面中提炼内容快照并分配 Ref ID。"""
        pass

    @abstractmethod
    def format_chunk(self, snapshot: PageSnapshot, page_index: int) -> str:
        """获取并格式化指定页码的快照切片内容。"""
        pass

    @abstractmethod
    def search(self, snapshot: PageSnapshot, keyword: str) -> str:
        """在当前快照中快速检索匹配关键词的内容与上下文。"""
        pass

    @abstractmethod
    def get_tool_metadata(self) -> dict[str, Any]:
        """返回适配当前 Reader 的大模型调用工具元数据与 Schema。"""
        pass
