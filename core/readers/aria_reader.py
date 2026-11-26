import asyncio
import inspect
import re
from typing import Any
from .base import BasePageReader, PageSnapshot

from astrbot.api import logger


TAG_MAP = {
    "link": "a",
    "img": "img",
    "image": "img",
    "button": "button",
    "textbox": "input",
    "checkbox": "input",
    "radio": "input",
    "combobox": "select",
    "heading": "h",
}


class _AriaNode:
    def __init__(self, indent: int, raw_line: str):
        self.indent = indent
        self.raw_line = raw_line
        self.is_url = False
        self.url_val = ""
        self.ref_id = ""
        self.role = ""
        self.name = ""
        self.children: list["_AriaNode"] = []
        self.parent: "_AriaNode | None" = None


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

    def _parse_aria_yaml(
        self, raw_yaml: str
    ) -> tuple[str, dict[str, dict], dict[str, str]]:
        """解析并清洗 Playwright ARIA YAML 文本。

        - 过滤并剥离 `- /url: <url>` 行，将 URL 提取并记录至父级链接的 ref_map 中；
        - 若超链接无障碍名称本身直接为 URL，在正文中化简为不带引号的 `link [ref=...]`；
        - 剥离因过滤子节点而遗留的多余末尾冒号；
        - 标准化 ref_map 元素字典契约，记录父子从属关系映射。
        """
        if not raw_yaml or not raw_yaml.strip():
            return "", {}, {}

        nodes: list[_AriaNode] = []
        stack: list[_AriaNode] = []

        for line in raw_yaml.splitlines():
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            node = _AriaNode(indent, line)

            # 匹配 /url: 子行
            m_url = re.match(r"^\s*(?:-\s*)?/url:\s*(.+)$", line)
            if m_url:
                node.is_url = True
                node.url_val = m_url.group(1).strip().strip('"').strip("'")

            # 匹配 [ref=...]
            m_ref = re.search(r"\[ref=([^\]]+)\]", line)
            if m_ref:
                node.ref_id = m_ref.group(1).strip()

            # 匹配 - role "name"
            m_role = re.match(r'^\s*-\s*([a-zA-Z0-9_-]+)(?:\s+"([^"]*)")?', line)
            if m_role:
                node.role = m_role.group(1)
                node.name = m_role.group(2) or ""

            # 依缩进维护祖先栈
            while stack and stack[-1].indent >= indent:
                stack.pop()

            if stack:
                node.parent = stack[-1]
                stack[-1].children.append(node)

            stack.append(node)
            nodes.append(node)

        ref_map: dict[str, dict] = {}
        parent_map: dict[str, str] = {}

        # 1. 初始化所有含 Ref ID 节点的标准化字典
        for node in nodes:
            if node.ref_id:
                role = node.role or ""
                name = node.name or ""
                is_url_name = role == "link" and (
                    name.startswith("http://") or name.startswith("https://")
                )
                tag = TAG_MAP.get(role, role)
                ref_map[node.ref_id] = {
                    "ref": node.ref_id,
                    "role": role,
                    "tag": tag,
                    "type": "text" if role == "textbox" else "",
                    "name": name,
                    "text": "" if is_url_name else name,
                    "alt": name if role in ("img", "image") else "",
                    "href": name if is_url_name else "",
                    "src": "",
                    "url": name if is_url_name else "",
                }
                # 记录最近具有 ref_id 的祖先
                curr = node.parent
                while curr:
                    if curr.ref_id:
                        parent_map[node.ref_id] = curr.ref_id
                        break
                    curr = curr.parent

        # 2. 将 /url: 节点的 URL 回填至父级 Ref
        for node in nodes:
            if node.is_url and node.url_val:
                curr = node.parent
                while curr:
                    if curr.ref_id and curr.ref_id in ref_map:
                        ref_map[curr.ref_id]["href"] = node.url_val
                        ref_map[curr.ref_id]["url"] = node.url_val
                        break
                    curr = curr.parent

        # 3. 构造清洗后的正文行
        cleaned_lines: list[str] = []
        for node in nodes:
            if node.is_url:
                continue

            line = node.raw_line

            # 超链接文本本身即为 URL 时，脱敏/精简为不带引号的 link
            if (
                node.role == "link"
                and node.name
                and (node.name.startswith("http://") or node.name.startswith("https://"))
            ):
                line = re.sub(r'(\blink)\s+"https?://[^"]*"(\s*)', r"\1\2", line)

            # 若该行无剩余渲染子节点，剥离多余末尾冒号
            has_rendered_children = any(not c.is_url for c in node.children)
            if not has_rendered_children:
                line = re.sub(r":\s*$", "", line)

            cleaned_lines.append(line)

        cleaned_yaml = "\n".join(cleaned_lines)
        if cleaned_lines and raw_yaml.endswith("\n"):
            cleaned_yaml += "\n"

        return cleaned_yaml, ref_map, parent_map

    async def _fetch_element_src(self, page: Any, ref: str) -> str:
        """根据 Ref ID 异步获取图片元素的真实 src。"""
        try:
            if not hasattr(page, "locator"):
                return ""
            loc = page.locator(f"aria-ref={ref}")
            if hasattr(loc, "count"):
                cnt = loc.count()
                if inspect.isawaitable(cnt):
                    cnt = await cnt
                if cnt == 0:
                    return ""
            if hasattr(loc, "evaluate"):
                res = loc.evaluate("el => el.src || el.getAttribute('src') || ''")
                if inspect.isawaitable(res):
                    res = await res
                if isinstance(res, str):
                    return res.strip()
        except Exception as e:
            logger.debug(f"[AriaReader] 获取元素 Ref [{ref}] src 异常: {e}")
        return ""

    async def extract_snapshot(
        self, page: Any, url: str = "", start_ref: int = 1, **kwargs
    ) -> PageSnapshot:
        """从页面提取官方原生 ARIA 快照并解析 Ref 键映射。"""
        title = await self._get_page_title(page)
        page_url = self._get_page_url(page, url)
        raw_yaml = await self._fetch_aria_snapshot(page)

        cleaned_yaml, ref_map, parent_map = self._parse_aria_yaml(raw_yaml)

        # 提取图片元素的真实 src 并关联父级 link
        img_refs = [
            r_id
            for r_id, info in ref_map.items()
            if info.get("role") in ("img", "image")
        ]
        if img_refs and hasattr(page, "locator"):
            src_results = await asyncio.gather(
                *(self._fetch_element_src(page, r_id) for r_id in img_refs),
                return_exceptions=True,
            )
            for r_id, src in zip(img_refs, src_results):
                if isinstance(src, str) and src:
                    ref_map[r_id]["src"] = src
                    if not ref_map[r_id].get("url"):
                        ref_map[r_id]["url"] = src
                    # 向上寻找关联的父级 link
                    curr_ref = r_id
                    while curr_ref in parent_map:
                        p_ref = parent_map[curr_ref]
                        if p_ref in ref_map:
                            if ref_map[p_ref].get("role") == "link":
                                if not ref_map[p_ref].get("src"):
                                    ref_map[p_ref]["src"] = src
                                if not ref_map[p_ref].get("alt"):
                                    ref_map[p_ref]["alt"] = ref_map[r_id].get("alt", "")
                                break
                            curr_ref = p_ref
                        else:
                            break

        chunks = self._chunk_aria_tree(cleaned_yaml, page_url, title)
        total_pages = len(chunks)

        return PageSnapshot(
            title=title,
            url=page_url,
            raw_content=cleaned_yaml,
            ref_map=ref_map,
            total_pages=total_pages,
            chunks=chunks,
            allocated_count=len(ref_map),
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
            "description": "读取当前网页的内容快照（以 ARIA 语义可访问性树形式呈现，包含 Landmark 区域、控件语义角色、状态及 Ref 编号，支持按区域分页、关键词搜索与按 Ref 查询链接与图片详情）。",
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
                        "description": "要查询详细信息或目标 URL 的元素 Ref 编号（如 'e1', 'e2'） (可选)",
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
