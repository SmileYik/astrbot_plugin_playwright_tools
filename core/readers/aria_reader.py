import inspect
import re
from typing import Any
from .base import BasePageReader, PageSnapshot

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger("AriaSnapshotReader")


class AriaSnapshotReader(BasePageReader):
    """基于 Playwright 官方原生 ARIA 快照与 Ref 映射的分页阅读器。

    直接调用 Playwright 官方原生 `page.locator(':root').aria_snapshot(mode='ai')`，
    获得符合规范的 YAML 缩进无障碍树与 `[ref=...]` 交互引用，
    支持多页按字符预算安全切分、关键词定位搜索与边界防护。
    """

    def __init__(self, chunk_char_limit: int = 2000, mask_passwords: bool = True):
        super().__init__(chunk_char_limit=chunk_char_limit, mask_passwords=mask_passwords)

    async def _get_page_title(self, page: Any) -> str:
        if not hasattr(page, "title"):
            return ""
        try:
            t = page.title
            if callable(t):
                res = t()
                if inspect.isawaitable(res):
                    res = await res
                return str(res) if isinstance(res, str) else ""
            if isinstance(t, str):
                return t
        except Exception as e:
            logger.debug(f"[AriaReader] 获取页面标题异常: {e}")
        return ""

    def _get_page_url(self, page: Any, default_url: str = "") -> str:
        if default_url:
            return default_url
        if hasattr(page, "url"):
            try:
                u = page.url
                if callable(u):
                    res = u()
                    return str(res) if isinstance(res, str) else ""
                if isinstance(u, str):
                    return u
            except Exception as e:
                logger.debug(f"[AriaReader] 获取页面 URL 异常: {e}")
        return ""

    async def _fetch_aria_snapshot(self, page: Any) -> str:
        # 1. 优先调用 page.locator(':root').aria_snapshot(mode='ai')
        if hasattr(page, "locator"):
            try:
                root = page.locator(":root")
                if hasattr(root, "aria_snapshot"):
                    try:
                        res = root.aria_snapshot(mode="ai")
                    except TypeError:
                        res = root.aria_snapshot()
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, str):
                        return res
            except Exception as e:
                logger.debug(f"[AriaReader] 获取 :root aria_snapshot 异常: {e}")

        # 2. 回退到 page.aria_snapshot(mode='ai')
        if hasattr(page, "aria_snapshot"):
            try:
                try:
                    res = page.aria_snapshot(mode="ai")
                except TypeError:
                    res = page.aria_snapshot()
                if inspect.isawaitable(res):
                    res = await res
                if isinstance(res, str):
                    return res
            except Exception as e:
                logger.debug(f"[AriaReader] 获取 page.aria_snapshot 异常: {e}")

        return ""

    def _render_chunk(
        self,
        body: str,
        page_index: int,
        total_pages: int,
        url: str = "",
        title: str = "",
    ) -> str:
        """格式化单个分页切片，包含规范化页眉元信息与页脚引导提示。"""
        header_parts = [f"=== 页面 ARIA 语义树视图 [分页: {page_index}/{total_pages}] ==="]
        meta_parts = []
        if title:
            meta_parts.append(f"页面标题: {title}")
        if url:
            meta_parts.append(f"页面地址: {url}")
        if meta_parts:
            header_parts.append("\n".join(meta_parts))

        header = "\n".join(header_parts)

        footer_parts = []
        if page_index < total_pages:
            remain = total_pages - page_index
            footer_parts.append(
                f"--- [提示: 本页未完，剩余 {remain} 页，可调用 pw_read(page={page_index + 1}) 查看后续] ---"
            )
        else:
            footer_parts.append(
                "--- [提示: 页面已读完，若需交互可调用 pw_interact 执行相应操作] ---"
            )
        footer = "\n".join(footer_parts)

        return f"{header}\n\n{body}\n\n{footer}"

    def _chunk_aria_tree(self, tree_text: str, url: str = "", title: str = "") -> list[str]:
        """将 ARIA 语义树按行分组切分为多个符合字符预算的分页。"""
        lines = [line for line in tree_text.splitlines() if line.strip()]
        if not lines:
            return [self._render_chunk("(当前页面未提取到有效 ARIA 语义树)", 1, 1, url, title)]

        groups: list[list[str]] = []
        current_group: list[str] = []

        for line in lines:
            if not current_group:
                current_group.append(line)
            else:
                tentative = current_group + [line]
                tentative_str = self._render_chunk("\n".join(tentative), len(groups) + 1, len(groups) + 2, url, title)
                if len(tentative_str) <= self.chunk_char_limit:
                    current_group = tentative
                else:
                    groups.append(current_group)
                    current_group = [line]

        if current_group:
            groups.append(current_group)

        total_pages = len(groups)
        chunks = [
            self._render_chunk("\n".join(group), idx + 1, total_pages, url, title)
            for idx, group in enumerate(groups)
        ]
        return chunks

    async def extract_snapshot(self, page: Any, url: str = "") -> PageSnapshot:
        """从页面提取官方原生 ARIA 快照并解析 Ref 键映射。"""
        title = await self._get_page_title(page)
        page_url = self._get_page_url(page, url)
        raw_yaml = await self._fetch_aria_snapshot(page)

        ref_map: dict[str, dict] = {}
        for line in raw_yaml.splitlines():
            matches = re.finditer(r'\[ref=([^\]]+)\]', line)
            for m in matches:
                ref_id = m.group(1).strip()
                if ref_id:
                    el_info = {"ref": ref_id}
                    m_role = re.match(r'^\s*-\s*([a-zA-Z0-9_-]+)(?:\s+"([^"]*)")?', line)
                    if m_role:
                        role = m_role.group(1)
                        name = m_role.group(2) or ""
                        el_info["role"] = role
                        el_info["tag"] = role
                        el_info["name"] = name
                        el_info["text"] = name
                    ref_map[ref_id] = el_info

        chunks = self._chunk_aria_tree(raw_yaml, page_url, title)
        total_pages = len(chunks)

        return PageSnapshot(
            title=title,
            url=page_url,
            raw_content=raw_yaml,
            ref_map=ref_map,
            total_pages=total_pages,
            chunks=chunks,
        )

    def format_chunk(self, snapshot: PageSnapshot, page_index: int) -> str:
        """获取指定页码的切片内容，具备边界保护。"""
        if not snapshot.chunks:
            return "页面内容为空"
        total = snapshot.total_pages or len(snapshot.chunks)
        clamped_idx = max(1, min(page_index, total))
        return snapshot.chunks[clamped_idx - 1]

    def search(self, snapshot: PageSnapshot, keyword: str) -> str:
        """在快照的 ARIA 语义树中检索匹配行并高亮返回上下文。"""
        kw = (keyword or "").strip()
        if not kw:
            return "检索失败: 请提供有效的检索关键词"

        lines: list[str] = []
        if isinstance(snapshot.raw_content, str):
            lines = snapshot.raw_content.splitlines()
        elif isinstance(snapshot.raw_content, list):
            for item in snapshot.raw_content:
                lines.extend(str(item).splitlines())
        else:
            for chunk in snapshot.chunks:
                lines.extend(chunk.splitlines())

        kw_lower = kw.lower()
        matched_lines = [line.strip() for line in lines if kw_lower in line.lower() and line.strip()]

        seen = set()
        dedup_matched = []
        for line in matched_lines:
            if line not in seen:
                seen.add(line)
                dedup_matched.append(line)

        if not dedup_matched:
            return (
                f"=== 页面 ARIA 关键词检索结果: '{kw}' ===\n"
                f"未在页面 ARIA 语义树中找到匹配 '{kw}' 的内容。建议调用 pw_read() 浏览页面。"
            )

        header = f"=== 页面 ARIA 关键词检索结果: '{kw}' (找到 {len(dedup_matched)} 处匹配) ==="
        body = "\n".join(dedup_matched)
        return (
            f"{header}\n{body}\n"
            f"--- [提示: 如需交互可查看匹配到的 Ref 编号并调用 pw_interact 执行点击/输入] ---"
        )

    def get_tool_metadata(self) -> dict[str, Any]:
        """返回适配 ARIA 语义树阅读的工具定义元数据。"""
        return {
            "name": "pw_read",
            "description": "读取当前网页的内容快照（以 ARIA 语义可访问性树形式呈现，包含 Landmark 区域、控件语义角色、状态及 Ref 编号，支持按区域分页与关键词搜索）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "分页查看时的页码编号，从1开始 (默认为1)",
                        "default": 1,
                    },
                    "keyword": {
                        "type": "string",
                        "description": "关键词快速检索页面内容 (可选)",
                        "default": "",
                    },
                    "refresh": {
                        "type": "boolean",
                        "description": "是否强制刷新重新提取页面快照 (默认为False)",
                        "default": False,
                    },
                },
                "required": [],
            },
        }
