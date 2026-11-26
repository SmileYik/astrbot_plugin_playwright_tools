(() => {
    const isVisible = (el) => {
        if (!el || el.nodeType !== 1) return false;
        const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
        if (style && (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')) return false;
        const tag = (el.tagName || '').toLowerCase();
        if (el.getBoundingClientRect && tag !== 'img') {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 && rect.height <= 0 && !el.innerText && el.children.length === 0) return false;
        }
        return true;
    };

    const noiseTags = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'TEMPLATE', 'IFRAME']);

    let nextRef = __START_REF__;
    let allocatedCount = 0;
    const rawElements = [];

    const isInteractive = (node) => {
        if (!node || node.nodeType !== 1) return false;
        const tag = (node.tagName || '').toLowerCase();
        const role = ((node.getAttribute && node.getAttribute('role')) || '').toLowerCase();
        if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'select' || tag === 'textarea' || tag === 'img') return true;
        if (role === 'button' || role === 'link' || role === 'checkbox' || role === 'radio' || role === 'textbox' || role === 'combobox') return true;
        if (node.hasAttribute && node.hasAttribute('onclick')) return true;
        return false;
    };

    const formatInteractive = (node, ref) => {
        const tag = (node.tagName || '').toLowerCase();
        const type = ((node.getAttribute && node.getAttribute('type')) || node.type || '').toLowerCase();
        const role = ((node.getAttribute && node.getAttribute('role')) || '').toLowerCase();
        const name = (node.getAttribute && node.getAttribute('name')) || '';
        const placeholder = (node.getAttribute && node.getAttribute('placeholder')) || '';
        const ariaLabel = ((node.getAttribute && node.getAttribute('aria-label')) || '').trim();
        const title = ((node.getAttribute && node.getAttribute('title')) || '').trim();
        let alt = ((node.getAttribute && node.getAttribute('alt')) || '').trim();
        let src = (node.src || (node.getAttribute && node.getAttribute('src')) || '').trim();
        let href = (node.href || (node.getAttribute && node.getAttribute('href')) || '').trim();
        let rawText = (node.innerText || node.textContent || '').trim();

        if (!src && node.querySelector) {
            try {
                const childImg = node.querySelector('img');
                if (childImg) {
                    src = (childImg.src || (childImg.getAttribute && childImg.getAttribute('src')) || '').trim();
                    if (!alt) alt = ((childImg.getAttribute && childImg.getAttribute('alt')) || '').trim();
                }
            } catch (e) {}
        }

        let text = rawText || alt || ariaLabel || title;
        if (text.length > 80) text = text.substring(0, 80) + '...';

        let value = '';
        if (type === 'password') {
            __PWD_MASK_EXPR__
        } else {
            value = node.value || (node.getAttribute && node.getAttribute('value')) || '';
        }

        const elObj = {
            ref: ref,
            tag: tag,
            type: type,
            role: role,
            name: name,
            placeholder: placeholder,
            value: value,
            text: text,
            alt: alt,
            src: src,
            href: href,
            url: href || src || ''
        };
        rawElements.push(elObj);

        // 1. 普通图片
        if (tag === 'img') {
            const desc = alt || title || ariaLabel || '';
            return desc ? `![图片: ${desc}][${ref}]` : `![图片][${ref}]`;
        }

        // 2. 超链接
        if (tag === 'a' || role === 'link') {
            if (src) {
                // 含图超链接
                const desc = text || alt || title || ariaLabel || '';
                return desc ? `[链接 (含图): ${desc}][${ref}]` : `[链接 (含图)][${ref}]`;
            }
            // 普通超链接
            return text ? `[${text}][${ref}]` : `[链接][${ref}]`;
        }

        // 3. 按钮
        if (tag === 'button' || role === 'button' || (tag === 'input' && (type === 'button' || type === 'submit' || type === 'reset'))) {
            const btnText = text || value || '';
            return btnText ? `[按钮: ${btnText}][${ref}]` : `[按钮][${ref}]`;
        }

        // 4. 输入框系列
        if (tag === 'input') {
            if (type === 'checkbox') {
                const checked = node.checked ? '已勾选' : '未勾选';
                const label = text || name || '';
                return label ? `[复选框: ${label} (${checked})][${ref}]` : `[复选框 (${checked})][${ref}]`;
            }
            if (type === 'radio') {
                const checked = node.checked ? '已勾选' : '未勾选';
                const label = text || name || '';
                return label ? `[单选框: ${label} (${checked})][${ref}]` : `[单选框 (${checked})][${ref}]`;
            }
            const details = [];
            if (name) details.push(`name="${name}"`);
            if (placeholder) details.push(`placeholder="${placeholder}"`);
            if (value) details.push(`value="${value}"`);
            const detailStr = details.length > 0 ? ` ${details.join(', ')}` : '';
            return `[输入框${detailStr}][${ref}]`;
        }

        // 5. 选择框
        if (tag === 'select') {
            const details = [];
            if (name) details.push(`name="${name}"`);
            if (node.options && node.selectedIndex >= 0 && node.options[node.selectedIndex]) {
                details.push(`选中="${node.options[node.selectedIndex].text.trim()}"`);
            }
            const detailStr = details.length > 0 ? ` ${details.join(', ')}` : '';
            return `[选择框${detailStr}][${ref}]`;
        }

        // 6. 文本域
        if (tag === 'textarea') {
            const details = [];
            if (name) details.push(`name="${name}"`);
            if (placeholder) details.push(`placeholder="${placeholder}"`);
            if (value) details.push(`value="${value}"`);
            const detailStr = details.length > 0 ? ` ${details.join(', ')}` : '';
            return `[文本域${detailStr}][${ref}]`;
        }

        // 7. 兜底其它控件
        return `[控件: ${text || tag}][${ref}]`;
    };

    const renderInline = (node) => {
        if (!node) return '';
        if (node.nodeType === 3) {
            return node.nodeValue.replace(/[\r\n\t]+/g, ' ');
        }
        if (node.nodeType !== 1) return '';
        if (!isVisible(node) || noiseTags.has(node.tagName)) return '';

        const tag = node.tagName.toLowerCase();
        if (tag === 'br') return '\n';

        if (isInteractive(node)) {
            let ref;
            if (node.hasAttribute && node.hasAttribute('data-astr-ref')) {
                ref = parseInt(node.getAttribute('data-astr-ref'));
            } else {
                ref = nextRef++;
                allocatedCount++;
                if (node.setAttribute) node.setAttribute('data-astr-ref', ref.toString());
            }
            return formatInteractive(node, ref);
        }

        if (tag === 'code') {
            return '`' + (node.textContent || '').trim() + '`';
        }
        if (tag === 'strong' || tag === 'b') {
            const inner = Array.from(node.childNodes).map(renderInline).join('');
            return inner.trim() ? `**${inner.trim()}**` : '';
        }
        if (tag === 'em' || tag === 'i') {
            const inner = Array.from(node.childNodes).map(renderInline).join('');
            return inner.trim() ? `*${inner.trim()}*` : '';
        }

        return Array.from(node.childNodes).map(renderInline).join('');
    };

    const isBlockTag = (tag) => {
        return ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'pre', 'ul', 'ol', 'table', 'hr'].includes(tag);
    };

    const isContainerTag = (tag) => {
        return ['div', 'section', 'article', 'main', 'aside', 'header', 'footer', 'nav', 'form', 'body'].includes(tag);
    };

    const isBlockOrContainer = (el) => {
        if (!el || el.nodeType !== 1) return false;
        const tag = el.tagName.toLowerCase();
        return isBlockTag(tag) || isContainerTag(tag);
    };

    const blocks = [];

    const traverse = (node) => {
        if (!node || node.nodeType !== 1) return;
        if (!isVisible(node) || noiseTags.has(node.tagName)) return;

        const tag = node.tagName.toLowerCase();

        if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) {
            const level = parseInt(tag.charAt(1));
            const text = renderInline(node).trim();
            if (text) {
                blocks.push('#'.repeat(level) + ' ' + text);
            }
            return;
        }

        if (tag === 'p') {
            const text = renderInline(node).trim();
            if (text) blocks.push(text);
            return;
        }

        if (tag === 'blockquote') {
            const text = renderInline(node).trim();
            if (text) blocks.push('> ' + text.replace(/\n/g, '\n> '));
            return;
        }

        if (tag === 'pre') {
            const text = (node.innerText || node.textContent || '').trim();
            if (text) blocks.push('```\n' + text + '\n```');
            return;
        }

        if (tag === 'ul' || tag === 'ol') {
            const isOl = tag === 'ol';
            let itemIdx = 1;
            const items = [];
            const lis = Array.from(node.children).filter(c => c.tagName && c.tagName.toLowerCase() === 'li');
            const targetLis = lis.length > 0 ? lis : Array.from(node.querySelectorAll('li'));
            for (const li of targetLis) {
                if (!isVisible(li)) continue;
                const liText = renderInline(li).trim();
                if (liText) {
                    items.push((isOl ? `${itemIdx++}. ` : '- ') + liText);
                }
            }
            if (items.length > 0) {
                blocks.push(items.join('\n'));
            }
            return;
        }

        if (tag === 'table') {
            const rows = Array.from(node.querySelectorAll('tr')).slice(0, 50);
            const tableLines = [];
            for (let r = 0; r < rows.length; r++) {
                const cells = Array.from(rows[r].querySelectorAll('th, td')).map(c => renderInline(c).trim());
                if (cells.length > 0) {
                    tableLines.push('| ' + cells.join(' | ') + ' |');
                    if (r === 0) {
                        tableLines.push('| ' + cells.map(() => '---').join(' | ') + ' |');
                    }
                }
            }
            if (tableLines.length > 0) {
                blocks.push(tableLines.join('\n'));
            }
            return;
        }

        if (tag === 'hr') {
            blocks.push('---');
            return;
        }

        if (isInteractive(node)) {
            const text = renderInline(node).trim();
            if (text) blocks.push(text);
            return;
        }

        const children = Array.from(node.children);
        const hasBlockChildren = children.some(c => isBlockOrContainer(c));

        if (!hasBlockChildren) {
            const text = renderInline(node).trim();
            if (text) blocks.push(text);
            return;
        }

        let inlineBuffer = [];
        const flushInline = () => {
            const text = inlineBuffer.join('').trim();
            if (text) blocks.push(text);
            inlineBuffer = [];
        };

        for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === 3) {
                const val = child.nodeValue.replace(/[\r\n\t]+/g, ' ');
                if (val.trim()) inlineBuffer.push(val);
            } else if (child.nodeType === 1) {
                if (isBlockOrContainer(child)) {
                    flushInline();
                    traverse(child);
                } else {
                    inlineBuffer.push(renderInline(child));
                }
            }
        }
        flushInline();
    };

    const root = document.body || document.documentElement;
    if (root) {
        traverse(root);
    }

    return {
        title: document.title || '',
        url: (window.location && window.location.href) || '',
        blocks: blocks,
        elements: rawElements,
        allocated_count: allocatedCount
    };
})();
