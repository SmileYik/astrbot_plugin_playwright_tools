import math
import re
from typing import Any

class PageExtractor:
    """页面结构化提炼与 Ref ID 索引映射器。负责将可见 DOM 提炼为低 Token、高精确度的 Markdown 正文与单行化控件骨架。"""

    def __init__(self, max_page_char_length: int = 2500, multiline_separator: str = " | "):
        self.max_page_char_length = max_page_char_length
        self.multiline_separator = multiline_separator

    def _normalize_multiline(self, text: str) -> str:
        """将包含换行符的多行文本安全规整为单行，消除字面粘连与歧义。"""
        if not text:
            return ""
        # 统一将 \r 替换为 \n 并按行切分
        raw_lines = text.replace("\r", "\n").split("\n")
        lines = [" ".join(line.split()) for line in raw_lines]
        lines = [line for line in lines if line]
        if not lines:
            return ""
        sep = self.multiline_separator if self.multiline_separator != "" else " "
        return sep.join(lines)

    def extract_snapshot(
        self,
        page_title: str,
        url: str,
        raw_elements: list[dict],
        markdown_text: str | list[str] = "",
    ) -> tuple[dict[str, str], dict[int, dict]]:
        """纯无状态提取，返回结构化快照字典与 Ref ID 映射表。"""
        ref_map: dict[int, dict] = {}

        # 1. 整理正文 Markdown
        if isinstance(markdown_text, list):
            md_clean = "\n\n".join([str(b).strip() for b in markdown_text if str(b).strip()])
        else:
            md_clean = str(markdown_text or "").strip()

        # 规范化多余换行与列表紧凑排布
        if md_clean:
            # 折叠 3 个及以上连续换行为双换行
            md_clean = re.sub(r'\n{3,}', '\n\n', md_clean)
            # 消除列表项之间多余的空行
            while re.search(r'(^|\n)([-*]\s[^\n]+)\n\n+(?=[-*]\s)', md_clean):
                md_clean = re.sub(r'(^|\n)([-*]\s[^\n]+)\n\n+(?=[-*]\s)', r'\1\2\n', md_clean)
            while re.search(r'(^|\n)(\d+\.\s[^\n]+)\n\n+(?=\d+\.\s)', md_clean):
                md_clean = re.sub(r'(^|\n)(\d+\.\s[^\n]+)\n\n+(?=\d+\.\s)', r'\1\2\n', md_clean)

        # 2. 整理控件列表（过滤无效空链接/按钮，去重连续相同控件）
        el_lines: list[str] = []
        if raw_elements:
            ref_idx = 1
            prev_interactive_key = None
            for el in raw_elements:
                tag = el.get("tag", "").lower()
                el_type = el.get("type", "").lower()
                role = el.get("role", "").lower()
                name = el.get("name", "")
                placeholder = el.get("placeholder", "").strip()
                value = el.get("value", "").strip()
                raw_text = el.get("text", "")
                aria_label = el.get("aria-label", "").strip()
                title = el.get("title", "").strip()

                text = self._normalize_multiline(raw_text)

                # 过滤空链接与空按钮（无 text、aria-label、title、value）
                if tag in ("a", "button") or el_type == "button" or role in ("button", "link"):
                    if not text:
                        text = aria_label or title or value
                    if not text:
                        continue
                    # 连续重复项去重
                    current_key = (tag, role, text)
                    if current_key == prev_interactive_key:
                        continue
                    prev_interactive_key = current_key
                else:
                    prev_interactive_key = None

                ref_id = ref_idx
                ref_map[ref_id] = el
                ref_idx += 1

                if tag in ("input", "textarea"):
                    details = []
                    if name:
                        details.append(f'name="{name}"')
                    if placeholder:
                        details.append(f'placeholder="{placeholder}"')
                    if value:
                        details.append(f'value="{value}"')
                    detail_str = f" ({', '.join(details)})" if details else ""
                    el_lines.append(f"[{ref_id}] [输入框]{detail_str}")
                elif tag == "button" or el_type == "button" or role == "button":
                    btn_label = f' "{text}"' if text else ""
                    el_lines.append(f"[{ref_id}] [按钮]{btn_label}")
                elif tag == "a" or role == "link":
                    link_label = f' "{text}"' if text else ""
                    el_lines.append(f"[{ref_id}] [链接]{link_label}")
                elif tag == "select":
                    options = el.get("options", [])
                    opt_str = f" (选项: {options[:5]})" if options else ""
                    el_lines.append(f"[{ref_id}] [下拉选择]{opt_str}")
                else:
                    label = f' "{text}"' if text else ""
                    el_lines.append(f"[{ref_id}] [{tag.upper()}]{label}")

            if len(el_lines) > 0:
                el_lines.insert(0, "【可操作元素】")

        elements_text = "\n".join(el_lines)

        # 3. 组合全量视图文本
        full_parts = [
            f"页面标题: {page_title or '无标题'}",
            f"页面地址: {url}",
            ""
        ]
        if md_clean:
            full_parts.append("【页面主要正文】")
            full_parts.append(md_clean)
            full_parts.append("")
        if elements_text:
            full_parts.append(elements_text)

        full_text = "\n".join(full_parts)

        snapshot_data = {
            "title": page_title or "无标题",
            "url": url,
            "markdown_text": md_clean,
            "elements_text": elements_text,
            "full_text": full_text,
        }
        return snapshot_data, ref_map

    def _split_into_chunks(self, text: str) -> list[str]:
        """按行与长度切分成块。"""
        if not text:
            return []
        lines = text.splitlines()
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
        return chunks

    def format_page_chunk(
        self,
        snapshot_data: dict[str, str] | str,
        target: str = "all",
        page_index: int = 1,
    ) -> str:
        """根据目标域（all / text / elements）对快照进行独立分页，并附加分页引导提示。"""
        target = (target or "all").lower().strip()
        if target not in ("all", "text", "elements"):
            target = "all"

        if isinstance(snapshot_data, str):
            # 兼容纯字符串快照
            snapshot_data = {
                "title": "",
                "url": "",
                "markdown_text": "",
                "elements_text": "",
                "full_text": snapshot_data,
            }

        title = snapshot_data.get("title", "")
        url = snapshot_data.get("url", "")
        header_meta = f"页面标题: {title}\n页面地址: {url}\n" if (title or url) else ""

        if target == "text":
            raw_content = snapshot_data.get("markdown_text", "").strip()
            if not raw_content:
                return f"{header_meta}=== 页面正文视图 ===\n(当前页面未提取到有效正文段落)\n--- [提示: 可调用 pw_page(action='read', target='elements') 查看可操作元素] ---"
            chunks = self._split_into_chunks(raw_content)
            total_pages = max(1, len(chunks))
            page_index = max(1, min(page_index, total_pages))
            body = chunks[page_index - 1]

            header = f"=== 页面正文视图 [分页: {page_index}/{total_pages}] ==="
            parts = [header, header_meta.strip(), body]
            if page_index < total_pages:
                remain = total_pages - page_index
                parts.append(
                    f"--- [提示: 正文未完，剩余 {remain} 页，可调用 pw_page(action='read', target='text', page={page_index + 1}) 查看后续；或调用 target='elements' 查看操作元素] ---"
                )
            else:
                parts.append(
                    "--- [提示: 正文已读完，若需交互可调用 pw_page(action='read', target='elements') 浏览可操作元素] ---"
                )
            return "\n\n".join([p for p in parts if p.strip()])

        elif target == "elements":
            raw_content = snapshot_data.get("elements_text", "").strip()
            if not raw_content:
                return f"{header_meta}=== 页面可操作元素视图 ===\n(当前页面无可见可操作元素)"
            chunks = self._split_into_chunks(raw_content)
            total_pages = max(1, len(chunks))
            page_index = max(1, min(page_index, total_pages))
            body = chunks[page_index - 1]

            header = f"=== 页面可操作元素视图 [分页: {page_index}/{total_pages}] ==="
            parts = [header, header_meta.strip(), body]
            if page_index < total_pages:
                remain = total_pages - page_index
                parts.append(
                    f"--- [提示: 元素未完，剩余 {remain} 页，可调用 pw_page(action='read', target='elements', page={page_index + 1}) 查看后续] ---"
                )
            else:
                parts.append(
                    "--- [提示: 元素已加载完毕，可直接调用 pw_interact(action='click', ref=...) 执行交互] ---"
                )
            return "\n\n".join([p for p in parts if p.strip()])

        else:  # target == "all"
            raw_content = snapshot_data.get("full_text", "").strip()
            if not raw_content:
                return "页面内容为空"
            chunks = self._split_into_chunks(raw_content)
            total_pages = max(1, len(chunks))
            page_index = max(1, min(page_index, total_pages))
            body = chunks[page_index - 1]

            header = f"=== 页面全局视图 [分页: {page_index}/{total_pages}] ==="
            parts = [header, body]
            if page_index < total_pages:
                remain = total_pages - page_index
                parts.append(
                    f"--- [提示: 本页未完，剩余 {remain} 页，可调用 pw_page(action='read', target='all', page={page_index + 1}) 查看后续；或指定 target='text' / target='elements' 独立查看] ---"
                )
            return "\n\n".join([p for p in parts if p.strip()])

    def search_snapshot(
        self,
        snapshot_data: dict[str, str] | str,
        keyword: str,
        target: str = "all",
    ) -> str:
        """在指定目标域中快速检索包含关键词的行并高亮返回匹配上下文。"""
        kw = (keyword or "").strip()
        if not kw:
            return "检索失败: 请提供有效的检索关键词"

        target = (target or "all").lower().strip()
        if target not in ("all", "text", "elements"):
            target = "all"

        if isinstance(snapshot_data, str):
            content_to_search = snapshot_data
        elif target == "text":
            content_to_search = snapshot_data.get("markdown_text", "")
        elif target == "elements":
            content_to_search = snapshot_data.get("elements_text", "")
        else:
            content_to_search = snapshot_data.get("full_text", "")

        kw_lower = kw.lower()
        lines = content_to_search.splitlines()
        matched_lines: list[str] = []

        for line in lines:
            if kw_lower in line.lower():
                matched_lines.append(line)

        domain_label = "正文" if target == "text" else ("可操作元素" if target == "elements" else "全域")
        if not matched_lines:
            return (
                f"=== 页面关键词检索结果 [{domain_label}]: '{kw}' ===\n"
                f"未在 {domain_label} 中找到匹配 '{kw}' 的内容。建议调用 pw_page(action='read', target='{target}') 浏览页面。"
            )

        header = f"=== 页面关键词检索结果 [{domain_label}]: '{kw}' (找到 {len(matched_lines)} 处匹配) ==="
        body = "\n".join(matched_lines)
        return f"{header}\n{body}\n--- [提示: 如需交互可查看匹配到的 Ref 编号并调用 pw_interact 执行点击/输入] ---"

    def get_js_extractor_script(self) -> str:
        """返回注入至浏览器执行的 JavaScript 提取脚本，支持结构化 Markdown 正文提炼与噪声剔除。"""
        return """
        (() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
                if (style && (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')) return false;
                if (el.getBoundingClientRect) {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                return true;
            };

            const noiseSelector = 'script, style, noscript, nav, header, footer, aside, .sidebar, .login-tip, .login-box';
            const isNoise = (el) => {
                if (!el) return false;
                if (el.closest) return !!el.closest(noiseSelector);
                if (el.matches && el.matches(noiseSelector)) return true;
                return false;
            };

            const getNodeTextWithBr = (el) => {
                if (!el) return '';
                if (el.querySelector && el.querySelector('br') && el.cloneNode) {
                    try {
                        const clone = el.cloneNode(true);
                        const brs = clone.querySelectorAll('br');
                        for (const br of brs) {
                            if (br.replaceWith) {
                                br.replaceWith('\\n');
                            } else if (br.parentNode) {
                                br.parentNode.removeChild(br);
                            }
                        }
                        const cloneText = (clone.textContent || '').trim();
                        if (cloneText) return cloneText;
                    } catch (e) {}
                }
                let text = el.innerText || el.textContent || '';
                return text.trim();
            };

            // 1. 提取可交互元素（过滤空控件与连续重复项）
            const interactiveSelectors = 'button, a, input, select, textarea, [role="button"], [role="link"], [onclick]';
            const rawElements = [];
            const interactiveNodes = document.querySelectorAll(interactiveSelectors);

            let idx = 1;
            let prevInteractiveKey = null;

            for (const node of interactiveNodes) {
                if (!isVisible(node)) continue;
                const tag = (node.tagName || '').toLowerCase();
                const type = (node.getAttribute && node.getAttribute('type')) || '';
                const role = (node.getAttribute && node.getAttribute('role') || '').toLowerCase();
                const name = (node.getAttribute && node.getAttribute('name')) || '';
                const placeholder = (node.getAttribute && node.getAttribute('placeholder')) || '';
                const value = node.value || (node.getAttribute && node.getAttribute('value')) || '';
                const ariaLabel = (node.getAttribute && node.getAttribute('aria-label') || '').trim();
                const title = (node.getAttribute && node.getAttribute('title') || '').trim();
                let text = (node.innerText || node.textContent || '').trim();

                // 过滤空链接与空按钮（无 text、aria-label、title、value）
                if (tag === 'a' || tag === 'button' || role === 'button' || role === 'link') {
                    if (!text) {
                        text = ariaLabel || title || value;
                    }
                    if (!text) continue;

                    // 连续重复项去重
                    const currentKey = tag + ':' + role + ':' + text;
                    if (currentKey === prevInteractiveKey) continue;
                    prevInteractiveKey = currentKey;
                } else {
                    prevInteractiveKey = null;
                }

                if (text.length > 80) text = text.substring(0, 80) + '...';

                if (node.setAttribute) {
                    node.setAttribute('data-astr-ref', idx.toString());
                }
                rawElements.push({
                    tag: tag,
                    type: type,
                    name: name,
                    placeholder: placeholder,
                    value: value,
                    text: text,
                    role: role,
                    options: tag === 'select' && node.options ? Array.from(node.options).map(o => o.text) : []
                });
                idx++;
            }

            // 2. 结构化正文提炼与容器识别
            // 候选专用正文容器
            const explicitMain = document.querySelector('article, main, [role="main"], .mw-parser-output, .markdown-body, #content');
            let mainContainer = (explicitMain && !isNoise(explicitMain)) ? explicitMain : null;

            if (!mainContainer) {
                // 文本密度与标点密度打分查找最佳正文容器
                const candidates = Array.from(document.querySelectorAll('div, section, article, main')).filter(el => !isNoise(el) && isVisible(el));
                let bestScore = -1;
                let bestEl = null;

                for (const el of candidates) {
                    const text = (el.innerText || el.textContent || '').trim();
                    if (text.length < 50) continue;

                    const punctMatches = text.match(/[,.?!;:，。？！；：\\n]/g);
                    const punctCount = punctMatches ? punctMatches.length : 0;

                    let linkLen = 0;
                    if (el.querySelectorAll) {
                        const links = el.querySelectorAll('a');
                        for (const a of links) {
                            linkLen += (a.innerText || a.textContent || '').trim().length;
                        }
                    }

                    const nonLinkLen = Math.max(0, text.length - linkLen);
                    // 标点密度加权
                    const score = nonLinkLen * (1 + (punctCount / (text.length + 1)));
                    if (score > bestScore) {
                        bestScore = score;
                        bestEl = el;
                    }
                }
                mainContainer = bestEl || document.body;
            }

            const mdLines = [];
            const visited = new Set();

            const markVisited = (el) => {
                visited.add(el);
                if (el.querySelectorAll) {
                    const children = el.querySelectorAll('*');
                    for (const child of children) {
                        visited.add(child);
                    }
                }
            };

            const querySelectorTarget = 'h1, h2, h3, h4, h5, h6, p, ul, ol, blockquote, pre, table, .d_post_content, .post-content, div';
            const textNodes = (mainContainer && mainContainer.querySelectorAll) ? mainContainer.querySelectorAll(querySelectorTarget) : [];

            for (const node of textNodes) {
                if (!isVisible(node) || isNoise(node) || visited.has(node)) continue;

                const tag = (node.tagName || '').toLowerCase();
                const isPostContent = (node.matches && (node.matches('.d_post_content, .post-content, .entry-content'))) ||
                                      (node.className && typeof node.className === 'string' && (node.className.includes('post_content') || node.className.includes('post-content')));

                if (tag === 'h1') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text) mdLines.push('# ' + text);
                    markVisited(node);
                } else if (tag === 'h2') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text) mdLines.push('## ' + text);
                    markVisited(node);
                } else if (tag === 'h3') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text) mdLines.push('### ' + text);
                    markVisited(node);
                } else if (tag === 'h4' || tag === 'h5' || tag === 'h6') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text) mdLines.push('#### ' + text);
                    markVisited(node);
                } else if (tag === 'p') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text && text.length >= 2) mdLines.push(text);
                    markVisited(node);
                } else if (tag === 'ul' || tag === 'ol') {
                    markVisited(node);
                    const lis = Array.from(node.querySelectorAll ? node.querySelectorAll('li') : []).slice(0, 30);
                    const listItems = [];
                    for (const li of lis) {
                        visited.add(li);
                        const liText = (li.innerText || li.textContent || '').trim();
                        if (liText) listItems.push('- ' + liText);
                    }
                    if (listItems.length > 0) {
                        mdLines.push(listItems.join('\\n'));
                    }
                } else if (tag === 'blockquote') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text) mdLines.push('> ' + text);
                    markVisited(node);
                } else if (tag === 'pre') {
                    const text = (node.innerText || node.textContent || '').trim();
                    if (text) mdLines.push('```\\n' + text.substring(0, 500) + '\\n```');
                    markVisited(node);
                } else if (tag === 'table') {
                    markVisited(node);
                    const rows = Array.from(node.querySelectorAll ? node.querySelectorAll('tr') : []).slice(0, 10);
                    for (const row of rows) {
                        visited.add(row);
                        const cells = Array.from(row.querySelectorAll ? row.querySelectorAll('th, td') : []).map(c => (c.innerText || c.textContent || '').trim());
                        if (cells.length > 0) {
                            mdLines.push('| ' + cells.join(' | ') + ' |');
                        }
                    }
                } else if (isPostContent) {
                    const text = getNodeTextWithBr(node);
                    if (text && text.length >= 2) {
                        mdLines.push(text);
                    }
                    markVisited(node);
                } else if (tag === 'div') {
                    // 对于普通 div：仅当不包含其他待查询块级元素时作为文本块提取
                    const hasInnerBlock = node.querySelector && !!node.querySelector('div, p, h1, h2, h3, h4, h5, h6, ul, ol, table, blockquote, pre');
                    if (!hasInnerBlock) {
                        const text = getNodeTextWithBr(node);
                        if (text && text.length >= 2) {
                            mdLines.push(text);
                        }
                        markVisited(node);
                    }
                }
            }

            let markdownText = mdLines.join('\\n\\n');

            return {
                title: document.title || '',
                url: (window.location && window.location.href) || '',
                elements: rawElements,
                markdownText: markdownText
            };
        })();
        """
