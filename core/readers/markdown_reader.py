import json
from typing import Any
from .base import BasePageReader, PageSnapshot


class InlineMarkdownReader(BasePageReader):
    """内联 Markdown 页面提炼阅读器。
    
    单遍遍历 DOM，将标题、段落、图片、控件内联为 Markdown 正文，
    在语义块边界处按字符预算安全切分分页，保证 Ref 控件不被截断。
    """

    def __init__(self, chunk_char_limit: int = 2000, mask_passwords: bool = True):
        super().__init__(chunk_char_limit=chunk_char_limit, mask_passwords=mask_passwords)

    def get_js_extractor_script(self) -> str:
        """返回注入至浏览器执行的 JavaScript 提取脚本。
        
        密码框在 mask_passwords 为 True 时脱敏为 value="******"，
        为 False 时保留原始值。
        """
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
                if (el.getBoundingClientRect) {{
                    const rect = el.getBoundingClientRect();
                    if (rect.width <= 0 && rect.height <= 0 && !el.innerText && el.children.length === 0) return false;
                }}
                return true;
            }};

            const noiseTags = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'TEMPLATE', 'IFRAME']);

            let nextRef = 1;
            const rawElements = [];

            const isInteractive = (node) => {{
                if (!node || node.nodeType !== 1) return false;
                const tag = (node.tagName || '').toLowerCase();
                const role = (node.getAttribute && node.getAttribute('role') || '').toLowerCase();
                if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'select' || tag === 'textarea') return true;
                if (role === 'button' || role === 'link' || role === 'checkbox' || role === 'radio' || role === 'textbox' || role === 'combobox') return true;
                if (node.hasAttribute && node.hasAttribute('onclick')) return true;
                return false;
            }};

            const formatInteractive = (node, ref) => {{
                const tag = (node.tagName || '').toLowerCase();
                const type = ((node.getAttribute && node.getAttribute('type')) || node.type || '').toLowerCase();
                const role = ((node.getAttribute && node.getAttribute('role')) || '').toLowerCase();
                const name = (node.getAttribute && node.getAttribute('name')) || '';
                const placeholder = (node.getAttribute && node.getAttribute('placeholder')) || '';
                const ariaLabel = ((node.getAttribute && node.getAttribute('aria-label')) || '').trim();
                const title = ((node.getAttribute && node.getAttribute('title')) || '').trim();
                let rawText = (node.innerText || node.textContent || '').trim();
                let text = rawText || ariaLabel || title;
                if (text.length > 80) text = text.substring(0, 80) + '...';

                let value = '';
                if (type === 'password') {{
                    {pwd_mask_expr}
                }} else {{
                    value = node.value || (node.getAttribute && node.getAttribute('value')) || '';
                }}

                const elObj = {{
                    ref: ref,
                    tag: tag,
                    type: type,
                    role: role,
                    name: name,
                    placeholder: placeholder,
                    value: value,
                    text: text
                }};
                rawElements.push(elObj);

                if (tag === 'button' || role === 'button' || (tag === 'input' && (type === 'button' || type === 'submit' || type === 'reset'))) {{
                    const btnText = text || value || '';
                    return btnText ? `[Ref: ${{ref}}] [按钮: ${{btnText}}]` : `[Ref: ${{ref}}] [按钮]`;
                }}
                if (tag === 'a' || role === 'link') {{
                    return text ? `[Ref: ${{ref}}] [链接: ${{text}}]` : `[Ref: ${{ref}}] [链接]`;
                }}
                if (tag === 'input') {{
                    if (type === 'checkbox') {{
                        const checked = node.checked ? '已勾选' : '未勾选';
                        return `[Ref: ${{ref}}] [复选框: ${{text || name || ''}} (${{checked}})]`.replace(' : ', ': ');
                    }}
                    if (type === 'radio') {{
                        const checked = node.checked ? '已勾选' : '未勾选';
                        return `[Ref: ${{ref}}] [单选框: ${{text || name || ''}} (${{checked}})]`.replace(' : ', ': ');
                    }}
                    const details = [];
                    if (name) details.push(`name="${{name}}"`);
                    if (placeholder) details.push(`placeholder="${{placeholder}}"`);
                    if (value) details.push(`value="${{value}}"`);
                    const detailStr = details.length > 0 ? `: ${{details.join(', ')}}` : '';
                    return `[Ref: ${{ref}}] [输入框${{detailStr}}]`;
                }}
                if (tag === 'select') {{
                    const details = [];
                    if (name) details.push(`name="${{name}}"`);
                    if (node.options && node.selectedIndex >= 0 && node.options[node.selectedIndex]) {{
                        details.push(`选中="${{node.options[node.selectedIndex].text.trim()}}"`);
                    }}
                    const detailStr = details.length > 0 ? `: ${{details.join(', ')}}` : '';
                    return `[Ref: ${{ref}}] [选择框${{detailStr}}]`;
                }}
                if (tag === 'textarea') {{
                    const details = [];
                    if (name) details.push(`name="${{name}}"`);
                    if (placeholder) details.push(`placeholder="${{placeholder}}"`);
                    if (value) details.push(`value="${{value}}"`);
                    const detailStr = details.length > 0 ? `: ${{details.join(', ')}}` : '';
                    return `[Ref: ${{ref}}] [文本域${{detailStr}}]`;
                }}
                return `[Ref: ${{ref}}] [控件: ${{text || tag}}]`;
            }};

            const renderInline = (node) => {{
                if (!node) return '';
                if (node.nodeType === 3) {{
                    return node.nodeValue.replace(/[\\r\\n\\t]+/g, ' ');
                }}
                if (node.nodeType !== 1) return '';
                if (!isVisible(node) || noiseTags.has(node.tagName)) return '';

                const tag = node.tagName.toLowerCase();
                if (tag === 'br') return '\\n';
                if (tag === 'img') {{
                    const alt = (node.getAttribute && node.getAttribute('alt')) || '';
                    const src = (node.getAttribute && node.getAttribute('src')) || '';
                    return src ? `![${{alt}}](${{src}})` : (alt ? `[图片: ${{alt}}]` : '');
                }}

                if (isInteractive(node)) {{
                    let ref;
                    if (node.hasAttribute && node.hasAttribute('data-astr-ref')) {{
                        ref = parseInt(node.getAttribute('data-astr-ref'));
                    }} else {{
                        ref = nextRef++;
                        if (node.setAttribute) node.setAttribute('data-astr-ref', ref.toString());
                    }}
                    return formatInteractive(node, ref);
                }}

                if (tag === 'code') {{
                    return '`' + (node.textContent || '').trim() + '`';
                }}
                if (tag === 'strong' || tag === 'b') {{
                    const inner = Array.from(node.childNodes).map(renderInline).join('');
                    return inner.trim() ? `**${{inner.trim()}}**` : '';
                }}
                if (tag === 'em' || tag === 'i') {{
                    const inner = Array.from(node.childNodes).map(renderInline).join('');
                    return inner.trim() ? `*${{inner.trim()}}*` : '';
                }}

                return Array.from(node.childNodes).map(renderInline).join('');
            }};

            const isBlockTag = (tag) => {{
                return ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'pre', 'ul', 'ol', 'table', 'hr'].includes(tag);
            }};

            const isContainerTag = (tag) => {{
                return ['div', 'section', 'article', 'main', 'aside', 'header', 'footer', 'nav', 'form', 'body'].includes(tag);
            }};

            const isBlockOrContainer = (el) => {{
                if (!el || el.nodeType !== 1) return false;
                const tag = el.tagName.toLowerCase();
                return isBlockTag(tag) || isContainerTag(tag);
            }};

            const blocks = [];

            const traverse = (node) => {{
                if (!node || node.nodeType !== 1) return;
                if (!isVisible(node) || noiseTags.has(node.tagName)) return;

                const tag = node.tagName.toLowerCase();

                if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) {{
                    const level = parseInt(tag.charAt(1));
                    const text = renderInline(node).trim();
                    if (text) {{
                        blocks.push('#'.repeat(level) + ' ' + text);
                    }}
                    return;
                }}

                if (tag === 'p') {{
                    const text = renderInline(node).trim();
                    if (text) blocks.push(text);
                    return;
                }}

                if (tag === 'blockquote') {{
                    const text = renderInline(node).trim();
                    if (text) blocks.push('> ' + text.replace(/\\n/g, '\\n> '));
                    return;
                }}

                if (tag === 'pre') {{
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text) blocks.push('```\\n' + text + '\\n```');
                    return;
                }}

                if (tag === 'ul' || tag === 'ol') {{
                    const isOl = tag === 'ol';
                    let itemIdx = 1;
                    const items = [];
                    const lis = Array.from(node.children).filter(c => c.tagName && c.tagName.toLowerCase() === 'li');
                    const targetLis = lis.length > 0 ? lis : Array.from(node.querySelectorAll('li'));
                    for (const li of targetLis) {{
                        if (!isVisible(li)) continue;
                        const liText = renderInline(li).trim();
                        if (liText) {{
                            items.push((isOl ? `${{itemIdx++}}. ` : '- ') + liText);
                        }}
                    }}
                    if (items.length > 0) {{
                        blocks.push(items.join('\\n'));
                    }}
                    return;
                }}

                if (tag === 'table') {{
                    const rows = Array.from(node.querySelectorAll('tr')).slice(0, 50);
                    const tableLines = [];
                    for (let r = 0; r < rows.length; r++) {{
                        const cells = Array.from(rows[r].querySelectorAll('th, td')).map(c => renderInline(c).trim());
                        if (cells.length > 0) {{
                            tableLines.push('| ' + cells.join(' | ') + ' |');
                            if (r === 0) {{
                                tableLines.push('| ' + cells.map(() => '---').join(' | ') + ' |');
                            }}
                        }}
                    }}
                    if (tableLines.length > 0) {{
                        blocks.push(tableLines.join('\\n'));
                    }}
                    return;
                }}

                if (tag === 'hr') {{
                    blocks.push('---');
                    return;
                }}

                if (tag === 'img') {{
                    const alt = (node.getAttribute && node.getAttribute('alt')) || '';
                    const src = (node.getAttribute && node.getAttribute('src')) || '';
                    if (src) blocks.push(`![${{alt}}](${{src}})`);
                    return;
                }}

                if (isInteractive(node)) {{
                    const text = renderInline(node).trim();
                    if (text) blocks.push(text);
                    return;
                }}

                const children = Array.from(node.children);
                const hasBlockChildren = children.some(c => isBlockOrContainer(c));

                if (!hasBlockChildren) {{
                    const text = renderInline(node).trim();
                    if (text) blocks.push(text);
                    return;
                }}

                let inlineBuffer = [];
                const flushInline = () => {{
                    const text = inlineBuffer.join('').trim();
                    if (text) blocks.push(text);
                    inlineBuffer = [];
                }};

                for (const child of Array.from(node.childNodes)) {{
                    if (child.nodeType === 3) {{
                        const val = child.nodeValue.replace(/[\\r\\n\\t]+/g, ' ');
                        if (val.trim()) inlineBuffer.push(val);
                    }} else if (child.nodeType === 1) {{
                        if (isBlockOrContainer(child)) {{
                            flushInline();
                            traverse(child);
                        }} else {{
                            inlineBuffer.push(renderInline(child));
                        }}
                    }}
                }}
                flushInline();
            }};

            const root = document.body || document.documentElement;
            if (root) {{
                traverse(root);
            }}

            return {{
                title: document.title || '',
                url: (window.location && window.location.href) || '',
                blocks: blocks,
                elements: rawElements
            }};
        }})();
        """

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

    def _chunk_blocks(self, blocks: list[str], url: str = "", title: str = "") -> list[str]:
        """按语义块边界切分正文，不切断单个语义块或 Ref 控件，累加至字符预算。"""
        clean_blocks = [b.strip() for b in blocks if b and b.strip()]
        if not clean_blocks:
            clean_blocks = ["(当前页面未提取到有效正文内容)"]

        groups: list[list[str]] = []
        current_group: list[str] = []

        for block in clean_blocks:
            if not current_group:
                current_group.append(block)
            else:
                tentative = current_group + [block]
                tentative_str = self._render_chunk(
                    tentative,
                    len(groups) + 1,
                    len(groups) + 2,
                    url,
                    title,
                )
                if len(tentative_str) <= self.chunk_char_limit:
                    current_group = tentative
                else:
                    groups.append(current_group)
                    current_group = [block]

        if current_group:
            groups.append(current_group)

        total_pages = len(groups)
        chunks = [
            self._render_chunk(group, idx + 1, total_pages, url, title)
            for idx, group in enumerate(groups)
        ]
        return chunks

    async def extract_snapshot(self, page: Any, url: str = "") -> PageSnapshot:
        """在浏览器中执行 JS 提炼并构建 PageSnapshot。"""
        script = self.get_js_extractor_script()
        data = await page.evaluate(script)
        if not isinstance(data, dict):
            data = {}

        title = str(data.get("title") or "").strip()
        page_url = str(data.get("url") or url or getattr(page, "url", "")).strip()
        blocks = data.get("blocks", [])
        if not isinstance(blocks, list):
            blocks = [str(blocks)] if blocks else []

        raw_elements = data.get("elements", [])
        ref_map: dict[int, dict] = {}
        if isinstance(raw_elements, list):
            for el in raw_elements:
                if isinstance(el, dict) and "ref" in el:
                    try:
                        ref_map[int(el["ref"])] = el
                    except (ValueError, TypeError):
                        pass

        chunks = self._chunk_blocks(blocks, page_url, title)
        total_pages = len(chunks)

        return PageSnapshot(
            title=title,
            url=page_url,
            raw_content=blocks,
            ref_map=ref_map,
            total_pages=total_pages,
            chunks=chunks,
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
                    "refresh": {
                        "type": "boolean",
                        "description": "是否强制刷新重新提取页面快照 (默认为False)",
                        "default": False,
                    },
                },
                "required": [],
            },
        }
