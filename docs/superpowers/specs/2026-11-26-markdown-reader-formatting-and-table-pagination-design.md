# Markdown Reader 排版精简与表格智能分页设计规范 (Design Spec)

## 1. 概述与背景 (Overview & Background)

在当前的 `InlineMarkdownReader` ([core/readers/markdown_reader.py](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/core/readers/markdown_reader.py)) 实现中，存在两大直接影响大模型交互体验与 Token 消耗的问题：
1. **分页字符预算失效（单页出现 38k 字符膨胀）**：在遇到包含大型表格（例如 GT New Horizons Wiki 主页的多列 50 行导航表）或大型列表时，JS 提炼层将整个表格拼接为单一巨大 Block。Python 侧 `_chunk_blocks` 仅在 Block 边界进行贪心合并，缺乏针对单个超限 Block 的内部切分机制，导致配置的 `page_chunk_char_limit`（默认 2000 字符）被击穿，单页快照暴增至 38,443 字符。
2. **排版冗长杂乱**：所有交互控件采用双中括号语法（如 `[Ref: 186] [链接: Beginner Tips]`），在密集链接区域（导航栏、Wiki 矩阵表格）存在大量无意义的 `[Ref: ]` 与 `[链接: ]` 字符重复，视觉干扰严重且浪费大量上下文 Token。

本项目旨在：
- 全面简化内联交互控件的排版格式，采用原生 Markdown 引用脚注风格（如 `[Beginner Tips][186]`）；
- 重构分页切分算法，引入表格智能切分与跨页表头自动补齐机制，确保任意分页严格受控在 `chunk_char_limit` 预算内。

---

## 2. 目标与非目标 (Goals, Non-Goals & Anti-Goals)

### 2.1 目标 (Goals)
1. **排版格式极简化（Markdown 引用风）**：
   - 超链接化简为 `[文本][Ref]`（含图链接为 `[链接 (含图): 描述][Ref]`，无文本链接为 `[链接][Ref]`）；
   - 图片化简为 `![图片: 描述][Ref]`（无描述为 `![图片][Ref]`）；
   - 按钮、输入框、复选框等统一定义为 `[类型: 描述][Ref]`。
2. **严格受控的字符预算（分页防膨胀）**：
   - 彻底解决单页 38k 字符的膨胀缺陷，保证任意单页正文及外围元信息的总字符数严格受控于 `chunk_char_limit`（默认 2000）。
3. **表格智能跨页拆分与表头自动补齐**：
   - 当多行 Markdown 表格被切分到多个分页时，从第二页开始在表首自动注入原表格的表头行与分隔行（`| 列1 | 列2 |\n| --- | --- |`），确保切出来的每一页中的表格在大模型视角下都是合法、自闭合、语义连贯的。
4. **底层契约与工具兼容性**：
   - 保留 DOM 注入的 `data-astr-ref` 属性，与 `InteractHandler` 定位器完全兼容；
   - 保持 `ref_map` 元数据结构完整，与 `PageHandler.read_page(ref=...)` 结构化查询完全兼容。

### 2.2 非目标 (Non-Goals)
- 不修改 `AriaSnapshotReader` 的 ARIA 语义树生成逻辑（ARIA 模式已有自身独立的行级切分机制）；
- 不调整 `pw_read` 工具入参接口与 `PageHandler` 的业务逻辑。

### 2.3 负向目标 (Anti-Goals)
- 严禁盲目按固定字符长度暴力硬截断（不得在单词、Ref 标签或表格单元格中途切断）；
- 严禁在后续分页中生成仅有表头而无数据行的“空表头分页”。

---

## 3. 技术方案选型与对比 (Approaches Considered)

| 方案 | 分页切分机制 | 排版展现形式 | 优势 | 劣势 | 选型结论 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **方案 A：JS 端字符硬截断** | 在浏览器 DOM 遍历时根据固定字符数截断为多个 Block | 维持原双括号 `[Ref: X] [类型: 文本]` | 实现相对集中在 JS 侧 | 无法响应 Python 侧动态配置的 `chunk_char_limit`；排版依然杂乱 | 放弃 |
| **方案 B：Python 侧纯文本行级盲切** | 将所有 Block 拼成大文本后按行切分 | 单括号紧凑风 `[#186 文本]` | 切分逻辑实现简单 | 跨页表格会丢失表头，导致第二页表格缺失列名语义；单括号与 issue 容易歧义 | 放弃 |
| **方案 C：表格感知智能切分 + Markdown 引用风 (选定方案)** | Python 侧智能识别表格结构，按数据行装箱，跨页自动补齐表头；超大 Block 行级兜底 | Markdown 引用脚注风 `[文本][Ref]` | **完美贴合 Markdown 原生语义，Token 开销直降约 45%，大模型阅读体验与表格结构完整性最优** | 切分算法需要解析并重放表头行 | **采纳** |

---

## 4. 详细设计 (Detailed Design)

### 4.1 控件与链接排版规范 (Format Specification)

在 `core/readers/markdown_reader.py` 的 `get_js_extractor_script()` 中，重构 `formatInteractive(node, ref)` 模板：

```javascript
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
```

---

### 4.2 表格跨页智能切分与表头自动补齐算法

在 `_chunk_blocks(self, blocks: list[str], url: str = "", title: str = "") -> list[str]` 中：

1. **表格结构特征识别**：
   - 检查 `block` 是否为 Markdown 表格：以 `|` 开头，且至少包含 2 行（首行为列头，第二行为类似 `| --- | --- |` 的对齐分隔行）。
2. **切分与装箱逻辑**：
   - 若表格总长度加上当前页已有内容在 `chunk_char_limit` 预算内，则作为整体保留在当前页；
   - 若超出预算：
     - 若当前页已有其他前置块（如标题、引言段落），且剩余空间不足以容纳表头加至少 1 行数据，则先将当前页封顶闭合，新起一页；
     - 在装入该表格数据行时：
       - 首页包含 `header_lines` 与若干条 `data_rows`；
       - 当当前页预算耗尽时封顶闭合；
       - 下一页开始时，**自动将 `header_lines`（包含表头行与 `---` 分隔行）作为当前页的首部内容注入**，随后继续装填后续的 `data_rows`；
       - 重复此过程，直到表格所有数据行处理完毕。
3. **超长非表格 Block 兜底拆分**：
   - 对于非表格但单块长度超过 `chunk_char_limit` 的大文本/长列表，按 `\n` 进行行级微切分装箱，避免孤儿超大块突破字符限制。

---

### 4.3 预算验证与边界安全

- 每次将候选内容组装入切片时，通过调用 `self._render_chunk(tentative, page_idx, total_pages, url, title)` 精确测量包含 Header（标题、URL）与 Footer（提示引导）在内的最终渲染字符总数；
- 确保 `len(tentative_str) <= self.chunk_char_limit`，实现真正的端到端字符预算控制。

---

## 5. 验证计划 (Verification Plan)

1. **排版格式单元测试**：
   - 验证链接、图片、按钮、输入框、复选框格式变更为 `[文本][Ref]` 及 `![图片: 描述][Ref]`；
   - 验证 `PageHandler.read_page(ref=...)` 查询返回不受排版格式变化影响。
2. **长表格切分与表头回填单元测试**：
   - 构造一个包含表头及 30 行数据的 Markdown 表格，设定较小字符预算（如 `chunk_char_limit=400`）；
   - 验证表格被切分为多个分页，且**每个分页均包含完整的表头行与分隔行**；
   - 验证每个分页的最终渲染长度严格小于或等于 `chunk_char_limit`。
3. **真实长 Wiki 页面模拟测试**：
   - 模拟具有大量矩阵链接的复杂页面，验证不会生成单页数万字符的膨胀快照。
4. **全量回归测试**：
   - 运行项目全量测试套件（226+ tests），确保 100% 通过。
