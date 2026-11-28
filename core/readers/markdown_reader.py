import json
from pathlib import Path
import re
from typing import Any
from .base import BasePageReader, PageSnapshot


class InlineMarkdownReader(BasePageReader):
    """内联 Markdown 页面提炼阅读器。
    
    单遍遍历 DOM，将标题、段落、图片、控件内联为 Markdown 正文，
    在语义块边界处按字符预算安全切分分页，保证 Ref 控件不被截断。
    """

    def __init__(self, chunk_char_limit: int = 2000, mask_passwords: bool = True):
        super().__init__(chunk_char_limit=chunk_char_limit, mask_passwords=mask_passwords)

    def get_js_extractor_script(self, start_ref: int = 1) -> str:
        """返回注入至浏览器执行的 JavaScript 提取脚本。
        
        密码框在 mask_passwords 为 True 时脱敏为 value="******"，
        为 False 时保留原始值。
        可交互元素 Ref ID 从 start_ref 持续单调自增。
        """
        start_ref_int = max(1, int(start_ref))
        if self.mask_passwords:
            pwd_mask_expr = 'value = "******";'
        else:
            pwd_mask_expr = 'value = node.value || (node.getAttribute && node.getAttribute("value")) || "";'

        js_path = Path(__file__).parent / "markdown_extractor.js"
        template = js_path.read_text(encoding="utf-8")
        return template.replace("__START_REF__", str(start_ref_int)).replace(
            "__PWD_MASK_EXPR__", pwd_mask_expr
        )

    def _render_chunk(
        self,
        group: list[str],
        page_index: int,
        total_pages: int,
        url: str = "",
        title: str = "",
    ) -> str:
        """格式化单个分页切片，包含规范化页眉元信息与页脚引导提示。"""
        header_parts = [f"=== 页面内容 [分页: {page_index}/{total_pages}] ==="]
        meta_parts = []
        if title:
            meta_parts.append(f"页面标题: {title}")
        if url:
            meta_parts.append(f"页面地址: {url}")
        if meta_parts:
            header_parts.append("\n".join(meta_parts))

        header = "\n".join(header_parts)
        body = "\n\n".join(group)

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

    def _render_tentative(
        self,
        group: list[str],
        page_index: int,
        url: str = "",
        title: str = "",
    ) -> str:
        """预渲染切片用于估算字符预算。
        
        使用保守的 total_pages 估算，确保最终渲染时因页码位数增加不会突破预算。
        """
        est_total = max(page_index + 1, 99)
        return self._render_chunk(group, page_index, est_total, url, title)

    TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")

    @classmethod
    def _parse_markdown_table(cls, block: str) -> tuple[bool, list[str], list[str]]:
        """检测并解析 Markdown 表格。
        
        返回 (is_table, header_lines, data_rows)。
        判定标准：多行文本（至少 2 行），第一行为以 | 起止的表头，第二行为匹配分隔行的行。
        header_lines 包含 [表头行, 分隔行]，data_rows 包含后续各行。
        """
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            return False, [], []
        line0 = lines[0]
        if not (line0.startswith("|") and line0.endswith("|")):
            return False, [], []
        if not cls.TABLE_SEPARATOR_PATTERN.match(lines[1]):
            return False, [], []
        header_lines = [lines[0], lines[1]]
        data_rows = lines[2:]
        return True, header_lines, data_rows

    _is_markdown_table = _parse_markdown_table

    def _chunk_blocks(self, blocks: list[str], url: str = "", title: str = "") -> list[str]:
        """按语义块边界切分正文，不切断单个语义块或 Ref 控件，累加至字符预算。
        
        支持多行 Markdown 表格跨页智能切分，并在跨页时自动回填表头行与分隔行。
        """
        clean_blocks = [b.strip() for b in blocks if b and b.strip()]
        if not clean_blocks:
            clean_blocks = ["(当前页面未提取到有效正文内容)"]

        groups: list[list[str]] = []
        current_group: list[str] = []

        for block in clean_blocks:
            is_table, header_lines, data_rows = self._parse_markdown_table(block)

            # 1. 优先尝试将整个 block 完整塞入当前页
            tentative = current_group + [block] if current_group else [block]
            tentative_str = self._render_tentative(
                tentative,
                len(groups) + 1,
                url,
                title,
            )

            if len(tentative_str) <= self.chunk_char_limit:
                current_group.append(block)
                continue

            # 2. 若超出当前预算，且当前 block 是可切分的多行表格
            if is_table and data_rows:
                # 若当前页已有其他前置块，检查能否至少容纳表头 + 1 条数据行
                if current_group:
                    min_table_block = "\n".join(header_lines + [data_rows[0]])
                    tentative_min = current_group + [min_table_block]
                    tentative_min_str = self._render_tentative(
                        tentative_min,
                        len(groups) + 1,
                        url,
                        title,
                    )
                    if len(tentative_min_str) > self.chunk_char_limit:
                        # 空间不足以容纳表头 + 1 条数据，先封顶当前页
                        groups.append(current_group)
                        current_group = []

                # 表格逐行装箱切分
                current_table_rows: list[str] = []
                row_idx = 0
                n_rows = len(data_rows)

                while row_idx < n_rows:
                    row = data_rows[row_idx]
                    candidate_rows = current_table_rows + [row]
                    candidate_table = "\n".join(header_lines + candidate_rows)
                    candidate_page = current_group + [candidate_table]
                    candidate_str = self._render_tentative(
                        candidate_page,
                        len(groups) + 1,
                        url,
                        title,
                    )

                    if len(candidate_str) <= self.chunk_char_limit:
                        current_table_rows.append(row)
                        row_idx += 1
                    else:
                        if current_table_rows:
                            # 当前页已有装入行，封顶当前页
                            current_group.append("\n".join(header_lines + current_table_rows))
                            groups.append(current_group)
                            current_group = []
                            current_table_rows = []
                            # candidate_row 在下一页重新尝试
                        else:
                            # 即使当前页为空页，表头 + 单行仍超出预算；为避免死循环或空表头分页，保底装入 1 行
                            current_table_rows.append(row)
                            row_idx += 1
                            if row_idx < n_rows:
                                current_group.append("\n".join(header_lines + current_table_rows))
                                groups.append(current_group)
                                current_group = []
                                current_table_rows = []

                if current_table_rows:
                    current_group.append("\n".join(header_lines + current_table_rows))
            else:
                # 3. 普通 Block 无法完整放入当前页
                # 若当前页已有其他前置块，先封顶当前页
                if current_group:
                    groups.append(current_group)
                    current_group = []

                # 检查 block 自身是否能塞入新的空页
                tentative_str = self._render_tentative(
                    [block],
                    len(groups) + 1,
                    url,
                    title,
                )
                if len(tentative_str) <= self.chunk_char_limit:
                    current_group.append(block)
                    continue

                # block 自身超出字符预算：执行行级微切分装箱
                lines = block.split("\n")
                current_lines: list[str] = []

                line_idx = 0
                n_lines = len(lines)
                while line_idx < n_lines:
                    line = lines[line_idx]

                    candidate_lines = current_lines + [line]
                    candidate_block = "\n".join(candidate_lines)
                    candidate_page = current_group + [candidate_block]
                    candidate_str = self._render_tentative(
                        candidate_page,
                        len(groups) + 1,
                        url,
                        title,
                    )

                    if len(candidate_str) <= self.chunk_char_limit:
                        current_lines.append(line)
                        line_idx += 1
                    else:
                        if current_lines:
                            # 当前页已有装入行，封顶当前页
                            current_group.append("\n".join(current_lines))
                            groups.append(current_group)
                            current_group = []
                            current_lines = []
                            # line 在下一页重新尝试
                        else:
                            # 单行 line 在空页上也超限：执行字符级硬切片切断
                            rem_line = line
                            while rem_line:
                                base_len = len(
                                    self._render_tentative([""], len(groups) + 1, url, title)
                                )
                                avail = self.chunk_char_limit - base_len
                                if avail <= 0:
                                    avail = 1
                                k = min(len(rem_line), avail)
                                while (
                                    k > 1
                                    and len(
                                        self._render_tentative(
                                            [rem_line[:k]], len(groups) + 1, url, title
                                        )
                                    )
                                    > self.chunk_char_limit
                                ):
                                    k -= 1

                                piece = rem_line[:k]
                                rem_line = rem_line[k:]

                                if rem_line:
                                    groups.append([piece])
                                else:
                                    current_lines.append(piece)

                            line_idx += 1

                if current_lines:
                    current_group.append("\n".join(current_lines))

        if current_group:
            groups.append(current_group)

        total_pages = len(groups)
        chunks = [
            self._render_chunk(group, idx + 1, total_pages, url, title)
            for idx, group in enumerate(groups)
        ]
        return chunks

    async def extract_snapshot(self, page: Any, url: str = "", start_ref: int = 1) -> PageSnapshot:
        """在浏览器中执行 JS 提炼并构建 PageSnapshot。"""
        script = self.get_js_extractor_script(start_ref=start_ref)
        data = await page.evaluate(script)
        if not isinstance(data, dict):
            data = {}

        title = str(data.get("title") or "").strip()
        page_url = str(data.get("url") or url or getattr(page, "url", "")).strip()
        blocks = data.get("blocks", [])
        if not isinstance(blocks, list):
            blocks = [str(blocks)] if blocks else []

        allocated_count = int(data.get("allocated_count", 0) or 0)
        raw_elements = data.get("elements", [])
        ref_map: dict[str, dict] = {}
        if isinstance(raw_elements, list):
            for el in raw_elements:
                if isinstance(el, dict) and "ref" in el:
                    ref_str = str(el["ref"]).strip()
                    if ref_str:
                        el_copy = dict(el)
                        el_copy["ref"] = ref_str
                        if "url" not in el_copy or not el_copy["url"]:
                            el_copy["url"] = el_copy.get("href") or el_copy.get("src") or ""
                        ref_map[ref_str] = el_copy

        chunks = self._chunk_blocks(blocks, page_url, title)
        total_pages = len(chunks)

        return PageSnapshot(
            title=title,
            url=page_url,
            raw_content=blocks,
            ref_map=ref_map,
            total_pages=total_pages,
            chunks=chunks,
            allocated_count=allocated_count,
        )

    def format_chunk(self, snapshot: PageSnapshot, page_index: int) -> str:
        """获取指定页码的快照切片内容，具备边界保护。"""
        if not snapshot.chunks:
            return "页面内容为空"
        total = snapshot.total_pages or len(snapshot.chunks)
        clamped_idx = max(1, min(page_index, total))
        return snapshot.chunks[clamped_idx - 1]

    def search(self, snapshot: PageSnapshot, keyword: str) -> str:
        """在快照中精准检索匹配行并高亮返回上下文。"""
        kw = (keyword or "").strip()
        if not kw:
            return "检索失败: 请提供有效的检索关键词"

        lines: list[str] = []
        if isinstance(snapshot.raw_content, list):
            for block in snapshot.raw_content:
                lines.extend(str(block).splitlines())
        elif isinstance(snapshot.raw_content, str):
            lines = snapshot.raw_content.splitlines()
        else:
            for chunk in snapshot.chunks:
                lines.extend(chunk.splitlines())

        kw_lower = kw.lower()
        matched_lines = [line.strip() for line in lines if kw_lower in line.lower() and line.strip()]

        # 去重但保持原始阅读序
        seen = set()
        dedup_matched = []
        for line in matched_lines:
            if line not in seen:
                seen.add(line)
                dedup_matched.append(line)

        if not dedup_matched:
            return (
                f"=== 页面关键词检索结果: '{kw}' ===\n"
                f"未在页面正文中找到匹配 '{kw}' 的内容。建议调用 pw_read() 浏览页面。"
            )

        header = f"=== 页面关键词检索结果: '{kw}' (找到 {len(dedup_matched)} 处匹配) ==="
        body = "\n".join(dedup_matched)
        return (
            f"{header}\n{body}\n"
            f"--- [提示: 如需交互可查看匹配到的 Ref 编号并调用 pw_interact 执行点击/输入] ---"
        )

    def get_tool_metadata(self) -> dict[str, Any]:
        """返回适配 Markdown 阅读的工具定义元数据。"""
        return {
            "name": "pw_read",
            "description": "读取当前网页的内容快照（以结构化 Markdown 形式呈现，正文中原位内联可交互控件与 Ref ID，支持按语义块分页与关键词搜索）。",
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
                    "ref": {
                        "type": "string",
                        "description": "要查询详细信息或目标 URL 的元素 Ref 编号（如 '@r1', '@r2'） (可选)",
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
