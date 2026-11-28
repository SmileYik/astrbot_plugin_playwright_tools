import inspect
from typing import Any

from astrbot.api import logger

from .base import BasePageReader, PageSnapshot


class PlainTextReader(BasePageReader):
    """纯文本响应分页阅读器，支持按字符预算分页、超长单行安全切分与关键词检索。"""

    def __init__(self, chunk_char_limit: int = 4000, mask_passwords: bool = True):
        super().__init__(chunk_char_limit=max(100, int(chunk_char_limit or 4000)), mask_passwords=mask_passwords)

    @staticmethod
    def _render_chunk(
        body_text: str,
        page_index: int,
        total_pages: int,
        url: str = "",
        title: str = "",
        mime_type: str = "text/plain",
    ) -> str:
        header_lines = [
            f"=== 文本内容 (第 {page_index}/{total_pages} 页) ===",
            f"URL: {url or '未知'}",
        ]
        if title:
            header_lines.append(f"标题: {title}")
        if mime_type:
            header_lines.append(f"类型: {mime_type}")
        header_lines.append("-" * 40)

        footer_lines = ["-" * 40]
        if page_index < total_pages:
            footer_lines.append(
                f"当前第 {page_index}/{total_pages} 页，可调用 pw_read(page={page_index + 1}) 查看下一页，或调用 pw_read(keyword='...') 检索内容。"
            )
        else:
            footer_lines.append(
                f"已到达最后一页 (共 {total_pages} 页)，可调用 pw_read(keyword='...') 检索内容。"
            )

        parts = ["\n".join(header_lines), body_text, "\n".join(footer_lines)]
        return "\n".join(p for p in parts if p)

    def _split_lines_into_groups(self, text: str, body_budget: int) -> list[str]:
        """按行合并为不超过 body_budget 的文本块；超长单行按字符切片。"""
        if not text:
            return ["(空文本内容)"]

        safe_budget = max(40, body_budget)
        groups: list[str] = []
        current_lines: list[str] = []
        current_len = 0

        for line in text.splitlines():
            line_len = len(line)
            if line_len > safe_budget:
                if current_lines:
                    groups.append("\n".join(current_lines))
                    current_lines = []
                    current_len = 0
                for start in range(0, line_len, safe_budget):
                    groups.append(line[start : start + safe_budget])
                continue

            added_len = line_len + (1 if current_lines else 0)
            if current_lines and current_len + added_len > safe_budget:
                groups.append("\n".join(current_lines))
                current_lines = [line]
                current_len = line_len
            else:
                current_lines.append(line)
                current_len += added_len

        if current_lines:
            groups.append("\n".join(current_lines))

        return groups or ["(空文本内容)"]

    def build_snapshot(
        self,
        text: str,
        url: str = "",
        title: str = "",
        mime_type: str = "text/plain",
    ) -> PageSnapshot:
        """将纯文本字符串切分为分页 PageSnapshot。"""
        sample_chrome = self._render_chunk("", 99, 99, url=url, title=title, mime_type=mime_type)
        body_budget = max(40, self.chunk_char_limit - len(sample_chrome))
        groups = self._split_lines_into_groups(text, body_budget)
        total_pages = len(groups)
        chunks = [
            self._render_chunk(group, idx + 1, total_pages, url=url, title=title, mime_type=mime_type)
            for idx, group in enumerate(groups)
        ]
        return PageSnapshot(
            title=title or url or "Plain Text",
            url=url,
            raw_content=text,
            ref_map={},
            total_pages=total_pages,
            chunks=chunks,
            allocated_count=0,
            reader_mode="plain_text",
        )

    async def extract_snapshot(self, page: Any, url: str = "", start_ref: int = 1) -> PageSnapshot:
        """从页面提取纯文本内容并构建分页快照。"""
        page_url = url or getattr(page, "url", "") or ""
        text = ""
        if page is not None and hasattr(page, "inner_text"):
            try:
                res = page.inner_text("body")
                text = await res if inspect.isawaitable(res) else str(res)
            except Exception as e:
                logger.debug(f"[PlainTextReader] inner_text 提取异常: {e}")
                text = ""
        if not text and page is not None and hasattr(page, "content"):
            try:
                res = page.content()
                text = await res if inspect.isawaitable(res) else str(res)
            except Exception as e:
                logger.debug(f"[PlainTextReader] page.content 提取异常: {e}")
                text = ""
        return self.build_snapshot(text=text, url=page_url)

    def format_chunk(self, snapshot: PageSnapshot, page_index: int) -> str:
        """获取指定页码的分页文本内容。"""
        if not snapshot or not snapshot.chunks:
            return "文本内容为空。"
        total = snapshot.total_pages or len(snapshot.chunks)
        clamped_idx = max(1, min(int(page_index or 1), total))
        return snapshot.chunks[clamped_idx - 1]

    def search(self, snapshot: PageSnapshot, keyword: str) -> str:
        """在纯文本快照中检索匹配关键词的行与上下文。"""
        kw = str(keyword or "").strip()
        if not kw:
            return "检索失败: 请提供非空关键词。"

        raw_text = str(getattr(snapshot, "raw_content", "") or "")
        if not raw_text and getattr(snapshot, "chunks", None):
            raw_text = "\n".join(snapshot.chunks)

        lines = raw_text.splitlines()
        kw_lower = kw.lower()
        matches: list[str] = []
        for idx, line in enumerate(lines, start=1):
            pos = line.lower().find(kw_lower)
            if pos != -1:
                if len(line) <= 200:
                    snippet = line
                else:
                    start = max(0, pos - 80)
                    end = min(len(line), pos + len(kw) + 120)
                    prefix = "..." if start > 0 else ""
                    suffix = "..." if end < len(line) else ""
                    snippet = f"{prefix}{line[start:end]}{suffix}"
                matches.append(f"[第 {idx} 行] {snippet}")
                if len(matches) >= 20:
                    break

        if not matches:
            return f"未在文本内容中找到匹配 '{kw}' 的结果。"

        header = f"=== 文本检索结果: '{kw}' (找到 {len(matches)} 处匹配) ==="
        return header + "\n" + "\n".join(matches)

    def get_tool_metadata(self) -> dict[str, Any]:
        return {
            "mode": "plain_text",
            "chunk_char_limit": self.chunk_char_limit,
        }
