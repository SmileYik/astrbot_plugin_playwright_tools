import re
from typing import Any
from .base import BasePageReader, PageSnapshot


class AriaNode:
    """ARIA 语法树节点表示。"""

    def __init__(self, line: str, indent: int):
        self.line = line
        self.indent = indent
        self.parent: AriaNode | None = None
        self.children: list[AriaNode] = []

    def get_role_and_name(self) -> str:
        s = self.line.strip()
        if s.startswith("- "):
            s = s[2:]
        if s.endswith(":"):
            s = s[:-1]
        s = re.sub(r"\s*\[ref=\d+\]", "", s)
        s = re.sub(r"\s*\[level=\d+\]", "", s)
        s = re.sub(r"\s*\[(checked|disabled)\]", "", s)
        return s.strip()

    def get_ancestors(self) -> list["AriaNode"]:
        ancestors = []
        curr = self.parent
        while curr is not None and curr.indent >= 0:
            ancestors.append(curr)
            curr = curr.parent
        ancestors.reverse()
        return ancestors

    def get_all_nodes(self) -> list["AriaNode"]:
        res = [self]
        for child in self.children:
            res.extend(child.get_all_nodes())
        return res


class AriaSnapshotReader(BasePageReader):
    """基于 ARIA 语义树的页面快照提取与分页阅读器。

    使用客户端 DOM ARIA 遍历脚本递归计算元素的语义角色 (Role)、可访问名称 (Name)、
    状态与层级结构，自动向可交互节点注入 `data-astr-ref` 属性，并输出符合规范的 YAML 缩进树。
    在切分分页时按顶层区域划分，超长跨页时自动回填祖先路径缩进树桩 (Ancestor Breadcrumbs)。
    """

    def __init__(self, chunk_char_limit: int = 2000, mask_passwords: bool = True):
        super().__init__(chunk_char_limit=chunk_char_limit, mask_passwords=mask_passwords)

    def get_js_extractor_script(self) -> str:
        """返回注入至浏览器执行的客户端 ARIA 语义树遍历与 Ref 映射脚本。"""
        if self.mask_passwords:
            pwd_mask_expr = 'value = "******";'
        else:
            pwd_mask_expr = 'value = node.value || (node.getAttribute && node.getAttribute("value")) || "";'

        return f"""
        (() => {{
            const isVisible = (el) => {{
                if (!el || el.nodeType !== 1) return false;
                const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
                if (style && (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')) return false;
                if (el.hasAttribute && (el.hasAttribute('hidden') || el.getAttribute('aria-hidden') === 'true')) return false;
                if (el.getBoundingClientRect) {{
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 && rect.height <= 0 && !el.innerText && el.children.length === 0) return false;
                }}
                return true;
            }};

            const noiseTags = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'TEMPLATE', 'IFRAME']);
            const interactiveRoles = new Set([
                'button', 'link', 'textbox', 'searchbox', 'checkbox', 'radio',
                'combobox', 'listbox', 'option', 'menuitem', 'tab', 'switch',
                'slider', 'spinbutton'
            ]);

            let nextRef = 1;
            const rawElements = [];

            const getRole = (node) => {{
                if (!node || node.nodeType !== 1) return '';
                const explicitRole = (node.getAttribute && node.getAttribute('role') || '').trim().toLowerCase();
                if (explicitRole) return explicitRole;

                const tag = node.tagName.toLowerCase();
                if (tag === 'main') return 'main';
                if (tag === 'header') return 'banner';
                if (tag === 'nav') return 'navigation';
                if (tag === 'footer') return 'contentinfo';
                if (tag === 'aside') return 'complementary';
                if (tag === 'section') {{
                    return (node.getAttribute('aria-label') || node.getAttribute('title') || node.getAttribute('aria-labelledby')) ? 'region' : 'section';
                }}
                if (tag === 'article') return 'article';
                if (tag === 'form') return 'form';
                if (tag.match(/^h[1-6]$/)) return 'heading';
                if (tag === 'button') return 'button';
                if (tag === 'a') return node.hasAttribute('href') ? 'link' : '';
                if (tag === 'input') {{
                    const type = ((node.getAttribute && node.getAttribute('type')) || node.type || 'text').toLowerCase();
                    if (type === 'button' || type === 'submit' || type === 'reset') return 'button';
                    if (type === 'checkbox') return 'checkbox';
                    if (type === 'radio') return 'radio';
                    if (type === 'search') return 'searchbox';
                    return 'textbox';
                }}
                if (tag === 'textarea') return 'textbox';
                if (tag === 'select') return 'combobox';
                if (tag === 'ul' || tag === 'ol') return 'list';
                if (tag === 'li') return 'listitem';
                if (tag === 'table') return 'table';
                if (tag === 'tr') return 'row';
                if (tag === 'th' || tag === 'td') return 'cell';
                if (tag === 'img') return 'img';
                if (tag === 'dialog') return 'dialog';
                if (tag === 'p' || tag === 'blockquote' || tag === 'pre') return 'paragraph';
                return '';
            }};

            const getName = (node) => {{
                if (!node) return '';
                let name = '';
                if (node.getAttribute) {{
                    name = node.getAttribute('aria-label') || node.getAttribute('alt') || node.getAttribute('title') || node.getAttribute('placeholder') || '';
                }}
                if (!name) {{
                    const tag = node.tagName ? node.tagName.toLowerCase() : '';
                    if (tag === 'input' && (node.type === 'button' || node.type === 'submit' || node.type === 'reset')) {{
                        name = node.value || '';
                    }} else if (tag === 'button' || tag === 'a' || tag.match(/^h[1-6]$/) || tag === 'li' || tag === 'th' || tag === 'td') {{
                        name = (node.innerText || node.textContent || '').trim();
                    }} else if (tag === 'img') {{
                        name = (node.getAttribute && node.getAttribute('alt')) || '';
                    }}
                }}
                name = name.replace(/[\\r\\n\\t]+/g, ' ').trim();
                if (name.length > 80) name = name.substring(0, 80) + '...';
                return name;
            }};

            const isInteractive = (role, tag, node) => {{
                if (interactiveRoles.has(role)) return true;
                if (tag === 'button' || tag === 'select' || tag === 'textarea') return true;
                if (tag === 'a' && node.hasAttribute('href')) return true;
                if (tag === 'input') {{
                    const type = ((node.getAttribute && node.getAttribute('type')) || node.type || '').toLowerCase();
                    return type !== 'hidden';
                }}
                if (node.hasAttribute && node.hasAttribute('onclick')) return true;
                return false;
            }};

            const lines = [];

            const walk = (node, depth) => {{
                if (!node || node.nodeType !== 1) return;
                if (!isVisible(node) || noiseTags.has(node.tagName)) return;

                const tag = node.tagName.toLowerCase();
                const role = getRole(node);
                const name = getName(node);
                const isInter = isInteractive(role, tag, node);

                let ref = null;
                let value = '';
                const type = ((node.getAttribute && node.getAttribute('type')) || node.type || '').toLowerCase();

                if (type === 'password') {{
                    {pwd_mask_expr}
                }} else if (node.value !== undefined) {{
                    value = node.value || (node.getAttribute && node.getAttribute('value')) || '';
                }}

                if (isInter) {{
                    if (node.hasAttribute && node.hasAttribute('data-astr-ref')) {{
                        ref = parseInt(node.getAttribute('data-astr-ref'));
                    }} else {{
                        ref = nextRef++;
                        if (node.setAttribute) node.setAttribute('data-astr-ref', ref.toString());
                    }}
                    rawElements.push({{
                        ref: ref,
                        tag: tag,
                        type: type,
                        role: role || tag,
                        name: name,
                        value: value,
                        text: (node.innerText || node.textContent || '').trim().substring(0, 80)
                    }});
                }}

                const indent = '  '.repeat(depth);

                if (role) {{
                    const rolePart = role;
                    const namePart = name ? ` "${{name}}"` : '';
                    let attrPart = '';
                    if (role === 'heading') {{
                        const level = tag.match(/^h([1-6])$/) ? tag.charAt(1) : (node.getAttribute('aria-level') || '2');
                        attrPart += ` [level=${{level}}]`;
                    }}
                    if (role === 'checkbox' || role === 'radio') {{
                        if (node.checked) attrPart += ' [checked]';
                    }}
                    if (node.disabled) {{
                        attrPart += ' [disabled]';
                    }}
                    if (ref !== null) {{
                        attrPart += ` [ref=${{ref}}]`;
                    }}

                    let valPart = '';
                    if (value && (role === 'textbox' || role === 'searchbox' || role === 'combobox')) {{
                        valPart = `: ${{value}}`;
                    }}

                    const childNodes = Array.from(node.children).filter(c => isVisible(c) && !noiseTags.has(c.tagName));

                    if (isInter && (tag === 'button' || tag === 'input' || tag === 'select' || tag === 'textarea' || (tag === 'a' && childNodes.length === 0))) {{
                        lines.push(`${{indent}}- ${{rolePart}}${{namePart}}${{attrPart}}${{valPart}}`);
                        return;
                    }}

                    if (role === 'paragraph') {{
                        const pText = (node.innerText || node.textContent || '').trim().replace(/[\\r\\n\\t]+/g, ' ');
                        if (pText && childNodes.length === 0) {{
                            const shortText = pText.length > 120 ? pText.substring(0, 120) + '...' : pText;
                            lines.push(`${{indent}}- paragraph: ${{shortText}}`);
                            return;
                        }}
                    }}

                    if (childNodes.length === 0) {{
                        lines.push(`${{indent}}- ${{rolePart}}${{namePart}}${{attrPart}}${{valPart}}`);
                        return;
                    }}

                    lines.push(`${{indent}}- ${{rolePart}}${{namePart}}${{attrPart}}${{valPart ? valPart : ':'}}`);
                    for (const child of childNodes) {{
                        walk(child, depth + 1);
                    }}
                }} else {{
                    const childNodes = Array.from(node.children).filter(c => isVisible(c) && !noiseTags.has(c.tagName));
                    if (childNodes.length === 0) {{
                        const txt = (node.innerText || node.textContent || '').trim().replace(/[\\r\\n\\t]+/g, ' ');
                        if (txt && (tag === 'p' || tag === 'span' || tag === 'div' || tag === 'label')) {{
                            const shortText = txt.length > 120 ? txt.substring(0, 120) + '...' : txt;
                            lines.push(`${{indent}}- text: "${{shortText}}"`);
                        }}
                        return;
                    }}
                    for (const child of childNodes) {{
                        walk(child, depth);
                    }}
                }}
            }};

            const root = document.body || document.documentElement;
            if (root) {{
                walk(root, 0);
            }}

            return {{
                title: document.title || '',
                url: (window.location && window.location.href) || '',
                ariaTree: lines.join('\\n'),
                elements: rawElements
            }};
        }})();
        """

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

    def _collect_units(self, node: AriaNode, budget: int) -> list[list[AriaNode]]:
        """递归提炼候选分块单元，优先保持区域或子树完整。"""
        if node.indent < 0:
            units = []
            for child in node.children:
                units.extend(self._collect_units(child, budget))
            return units

        descendants = node.get_all_nodes()
        subtree_len = sum(len(n.line) + 1 for n in descendants)
        est_total_len = subtree_len + 140

        if est_total_len <= budget or not node.children:
            return [descendants]
        else:
            units = []
            for child in node.children:
                units.extend(self._collect_units(child, budget))
            return units

    def _render_group_body(
        self,
        group_units: list[list[AriaNode]],
        is_continuation: bool,
    ) -> str:
        """将一组分块单元渲染为带祖先路径回填的自闭合 YAML 层级片段。"""
        nodes_in_group: list[AriaNode] = []
        for u in group_units:
            for n in u:
                if n not in nodes_in_group:
                    nodes_in_group.append(n)

        if not nodes_in_group:
            return ""

        emitted_lines: list[str] = []
        seen_nodes: set[AriaNode] = set()

        first_node = nodes_in_group[0]
        ancestors = first_node.get_ancestors()

        if is_continuation and ancestors:
            path_names = [a.get_role_and_name() for a in ancestors if a.get_role_and_name()]
            if path_names:
                emitted_lines.append(f"[祖先路径: {' > '.join(path_names)}]")

        def ensure_ancestors_emitted(n: AriaNode):
            for anc in n.get_ancestors():
                if anc not in seen_nodes:
                    seen_nodes.add(anc)
                    emitted_lines.append(anc.line)

        for n in nodes_in_group:
            ensure_ancestors_emitted(n)
            if n not in seen_nodes:
                seen_nodes.add(n)
                emitted_lines.append(n.line)

        return "\n".join(emitted_lines)

    def _chunk_aria_tree(self, tree_text: str, url: str = "", title: str = "") -> list[str]:
        """将完整 ARIA 语义树按区域与字符预算切分为多页，跨页自动回填祖先树桩。"""
        clean_lines = [line for line in tree_text.splitlines() if line.strip()]
        if not clean_lines:
            return [self._render_chunk("(当前页面未提取到有效 ARIA 语义树)", 1, 1, url, title)]

        # 语法树层级解析
        root = AriaNode("", -1)
        stack = [root]
        for raw_line in clean_lines:
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            while stack[-1].indent >= indent:
                stack.pop()
            node = AriaNode(raw_line, indent)
            node.parent = stack[-1] if stack[-1] is not root else None
            stack[-1].children.append(node)
            stack.append(node)

        units = self._collect_units(root, self.chunk_char_limit)
        if not units:
            return [self._render_chunk(tree_text, 1, 1, url, title)]

        # 顺序聚合单元至分页
        groups: list[list[list[AriaNode]]] = []
        current_group: list[list[AriaNode]] = []

        for unit in units:
            if not current_group:
                current_group.append(unit)
            else:
                tentative_group = current_group + [unit]
                is_cont = len(groups) > 0
                tentative_body = self._render_group_body(tentative_group, is_continuation=is_cont)
                tentative_str = self._render_chunk(
                    tentative_body,
                    len(groups) + 1,
                    len(groups) + 2,
                    url,
                    title,
                )
                if len(tentative_str) <= self.chunk_char_limit:
                    current_group = tentative_group
                else:
                    groups.append(current_group)
                    current_group = [unit]

        if current_group:
            groups.append(current_group)

        total_pages = len(groups)
        chunks = []
        for idx, group in enumerate(groups):
            is_cont = idx > 0
            body = self._render_group_body(group, is_continuation=is_cont)
            chunk_str = self._render_chunk(body, idx + 1, total_pages, url, title)
            chunks.append(chunk_str)

        return chunks

    async def extract_snapshot(self, page: Any, url: str) -> PageSnapshot:
        """在浏览器中执行 JS 提取 ARIA 语义树与交互 Ref，并构建 PageSnapshot。"""
        script = self.get_js_extractor_script()
        data = await page.evaluate(script)
        if not isinstance(data, dict):
            data = {}

        title = str(data.get("title") or "").strip()
        page_url = str(data.get("url") or url).strip()
        tree_text = str(data.get("ariaTree") or "").strip()
        raw_elements = data.get("elements", [])

        ref_map: dict[int, dict] = {}
        if isinstance(raw_elements, list):
            for el in raw_elements:
                if isinstance(el, dict) and "ref" in el:
                    try:
                        ref_map[int(el["ref"])] = el
                    except (ValueError, TypeError):
                        pass

        chunks = self._chunk_aria_tree(tree_text, page_url, title)
        total_pages = len(chunks)

        return PageSnapshot(
            title=title,
            url=page_url,
            raw_content=tree_text,
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
