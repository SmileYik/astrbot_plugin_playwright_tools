import math
from typing import Any

class PageExtractor:
    """页面精简提炼与 Ref ID 索引映射器。负责将可见 DOM 提炼为低 Token、高精确度的文本骨架。"""

    def __init__(self, max_page_char_length: int = 2500):
        self.max_page_char_length = max_page_char_length

    def extract_snapshot(
        self,
        page_title: str,
        url: str,
        raw_elements: list[dict],
        text_blocks: list[str] | None = None,
    ) -> tuple[str, dict[int, dict]]:
        """提取可交互元素并编号，构建纯文本快照与 Ref ID 映射表。"""
        text_blocks = text_blocks or []
        ref_map: dict[int, dict] = {}
        lines: list[str] = []

        # 头部信息
        lines.append(f"页面标题: {page_title or '无标题'}")
        lines.append(f"页面地址: {url}")
        lines.append("")

        # 文本段落
        if text_blocks:
            lines.append("【页面主要文本】")
            for block in text_blocks:
                cleaned = block.strip()
                if cleaned:
                    lines.append(f"[文本] {cleaned}")
            lines.append("")

        # 交互元素编号映射
        if raw_elements:
            lines.append("【可操作元素】")
            for idx, el in enumerate(raw_elements, start=1):
                ref_id = idx
                ref_map[ref_id] = el
                tag = el.get("tag", "").lower()
                el_type = el.get("type", "").lower()
                name = el.get("name", "")
                text = el.get("text", "").strip()
                placeholder = el.get("placeholder", "").strip()
                value = el.get("value", "").strip()

                if tag in ("input", "textarea"):
                    details = []
                    if name:
                        details.append(f'name="{name}"')
                    if placeholder:
                        details.append(f'placeholder="{placeholder}"')
                    if value:
                        details.append(f'value="{value}"')
                    detail_str = f" ({', '.join(details)})" if details else ""
                    lines.append(f"[{ref_id}] [输入框]{detail_str}")
                elif tag == "button" or el_type == "button" or el.get("role") == "button":
                    btn_label = f' "{text}"' if text else ""
                    lines.append(f"[{ref_id}] [按钮]{btn_label}")
                elif tag == "a":
                    link_label = f' "{text}"' if text else ""
                    lines.append(f"[{ref_id}] [链接]{link_label}")
                elif tag == "select":
                    options = el.get("options", [])
                    opt_str = f" (选项: {options[:5]})" if options else ""
                    lines.append(f"[{ref_id}] [下拉选择]{opt_str}")
                else:
                    label = f' "{text}"' if text else ""
                    lines.append(f"[{ref_id}] [{tag.upper()}]{label}")

        snapshot_content = "\n".join(lines)
        return snapshot_content, ref_map

    def format_page_chunk(self, snapshot_text: str, page_index: int = 1) -> str:
        """根据长度限制对快照进行分页，并附加分页引导提示。"""
        if not snapshot_text:
            return "页面内容为空"

        lines = snapshot_text.splitlines()
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1
            if current_len + line_len > self.max_page_char_length and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
            else:
                current_chunk.append(line)
                current_len += line_len

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        total_pages = max(1, len(chunks))
        page_index = max(1, min(page_index, total_pages))
        chunk_content = chunks[page_index - 1]

        header = f"=== 页面视图 [分页: {page_index}/{total_pages}] ==="
        result_parts = [header, chunk_content]

        if page_index < total_pages:
            remain = total_pages - page_index
            result_parts.append(
                f"--- [提示: 本页未完，剩余 {remain} 页，可调用 read_page(page={page_index + 1}) 查看后续] ---"
            )

        return "\n".join(result_parts)

    def get_js_extractor_script(self) -> str:
        """返回注入至浏览器执行的 JavaScript 提取脚本。"""
        return """
        (() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            const interactiveSelectors = 'button, a, input, select, textarea, [role="button"], [role="link"], [onclick]';
            const rawElements = [];
            const nodes = document.querySelectorAll(interactiveSelectors);

            let idx = 1;
            for (const node of nodes) {
                if (!isVisible(node)) continue;
                let text = node.innerText || node.textContent || '';
                if (text.length > 50) text = text.substring(0, 50) + '...';
                
                node.setAttribute('data-astr-ref', idx.toString());
                rawElements.push({
                    tag: node.tagName.toLowerCase(),
                    type: node.getAttribute('type') || '',
                    name: node.getAttribute('name') || '',
                    placeholder: node.getAttribute('placeholder') || '',
                    value: node.value || '',
                    text: text.trim(),
                    role: node.getAttribute('role') || '',
                    options: node.tagName.toLowerCase() === 'select' ? Array.from(node.options).map(o => o.text) : []
                });
                idx++;
            }

            const textBlocks = [];
            const textNodes = document.querySelectorAll('h1, h2, h3, p, article, [role="article"]');
            for (const tn of textNodes) {
                if (!isVisible(tn)) continue;
                const t = (tn.innerText || '').trim();
                if (t.length > 10 && !interactiveSelectors.includes(tn.tagName.toLowerCase())) {
                    textBlocks.push(t.length > 200 ? t.substring(0, 200) + '...' : t);
                }
            }

            return {
                title: document.title,
                url: window.location.href,
                elements: rawElements,
                text_blocks: textBlocks.slice(0, 20)
            };
        })();
        """
