# Markdown Reader 排版精简与表格智能分页实施计划 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 `InlineMarkdownReader` 的内联控件排版语法（精简为 `[文本][Ref]` 引用风）与分页切分算法（实现表格感知切分与跨页自动回填表头），杜绝单页 38k 字符膨胀，大幅降低 Token 消耗并提升阅读体验。

**Architecture:** 在 JS 提炼层将交互元素与链接的序列化表达升级为原生 Markdown 引用风；在 Python 侧 `_chunk_blocks` 中引入表格结构识别，按数据行进行精细化装箱计算，跨页切分时自动在下一页首部回填表头与分隔行；对超大块执行行级微切分兜底，确保任意单页严格受控于 `chunk_char_limit` 字符预算。

**Tech Stack:** Python 3.12+, Playwright, JavaScript (DOM Evaluation), unittest

**Spec:** [docs/superpowers/specs/2026-11-26-markdown-reader-formatting-and-table-pagination-design.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-26-markdown-reader-formatting-and-table-pagination-design.md)

## Global Constraints

- 日志规范：遵循 `AGENT.md`，严禁 `import logging`，必须统一使用 `from astrbot.api import logger`；
- 文案规范：严禁使用绝对化词汇（如“彻底解决”、“完美”等）；
- 兼容性规范：`PageSnapshot.ref_map` 契约与 `data-astr-ref` DOM 注入逻辑保持向下兼容，确保 `pw_interact` 与 `pw_read(ref=...)` 功能不受影响；
- 运行环境：Windows 环境下 Python 异步单测命令需设置 `BypassSandbox: true`。

## Review Focus

1. **单页字符预算严格守卫**：无论输入包含 50 行超长表格、连续上百项密集链接列表还是巨型文本块，任意单页渲染结果的总字符数必须 `<= chunk_char_limit`（默认 2000）。
2. **跨页表格语法自闭合**：跨页被截断的表格，其后续分页必须在数据行之前自动前置原表格的表头与分隔行（`| Col1 | Col2 |\n| --- | --- |`），严禁产生缺失表头的孤儿数据行。
3. **避免空表头孤儿分页**：若当前页剩余空间仅够塞入表头却无法容纳任何数据行，切分器必须将整个表格顺延至下一页，严禁产生“只有表头、无数据行”的空分页。
4. **含图链接与特殊控件区分**：含图链接需清晰表达为 `[链接 (含图): 描述][Ref]`，图片需表达为 `![图片: 描述][Ref]`，输入框/选择框需保留关键属性，语法规范严谨。
5. **单元测试 100% 绿色**：全量回归套件（226+ tests）必须保持 100% 通过。

---

### Task 1: 内联交互控件排版精简与 JS 脚本解耦独立 (Markdown Reference Syntax & JS Decoupling)

**Files:**
- Create: `core/readers/markdown_extractor.js`
- Modify: `core/readers/markdown_reader.py:16-160`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: JS 提炼逻辑与 `formatInteractive(node, ref)`
- Produces: 独立的 `core/readers/markdown_extractor.js`；精简的 `[文本][Ref]`、`![图片: 描述][Ref]`、`[按钮: 文本][Ref]`、`[输入框 details][Ref]` 等排版字符串；`get_js_extractor_script()` 从外部 JS 文件动态读取模板并注入参数。

- [ ] **Step 1: 在 `tests/test_readers.py` 中编写/更新排版格式单测**

更新 `test_markdown_reader_extract_snapshot`、`test_markdown_reader_interactive_elements` 等测试用例，断言新格式：
```python
# 链接断言
self.assertIn("[官方文档][2]", snapshot.raw_content)
self.assertIn("[链接 (含图): 查看原图][3]", snapshot.raw_content)
# 图片断言
self.assertIn("![图片: 架构图][1]", snapshot.raw_content)
# 按钮断言
self.assertIn("[按钮: 点击下载][1]", snapshot.raw_content)
# 脚本断言
self.assertIn("![图片: ${desc}][${ref}]", script)
```

- [ ] **Step 2: 运行测试验证失败**

运行: `python -m unittest tests.test_readers.TestInlineMarkdownReader`
预期结果: FAIL（仍输出旧版 `[Ref: X] [...]`）。

- [ ] **Step 3: 创建 `core/readers/markdown_extractor.js` 并改造 `core/readers/markdown_reader.py`**

1. 将原嵌入在 Python 中的 JS 代码抽取至独立的 `core/readers/markdown_extractor.js`；
2. 按照设计规范更新 `markdown_extractor.js` 中各元素渲染模板：
- `tag === 'img'`: `desc ? \`![图片: ${desc}][${ref}]\` : \`![图片][${ref}]\``
- `tag === 'a' || role === 'link'`:
  - `if (src)`: `desc ? \`[链接 (含图): ${desc}][${ref}]\` : \`[链接 (含图)][${ref}]\``
  - `else`: `text ? \`[${text}][${ref}]\` : \`[链接][${ref}]\``
- `tag === 'button' || role === 'button'`: `btnText ? \`[按钮: ${btnText}][${ref}]\` : \`[按钮][${ref}]\``
- `tag === 'input'`:
  - checkbox / radio: `\`[复选框: ${label} (${checked})][${ref}]\``
  - 其他 input: `\`[输入框${detailStr}][${ref}]\``
- `tag === 'select'`: `\`[选择框${detailStr}][${ref}]\``
- `tag === 'textarea'`: `\`[文本域${detailStr}][${ref}]\``
- 兜底: `\`[控件: ${text || tag}][${ref}]\``
3. 在 `markdown_reader.py` 中通过 `Path(__file__).parent / "markdown_extractor.js"` 读取模板并完成参数替换返回。

- [ ] **Step 4: 运行测试验证通过**

运行: `python -m unittest tests.test_readers.TestInlineMarkdownReader`
预期结果: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/markdown_extractor.js core/readers/markdown_reader.py tests/test_readers.py
git commit -m "feat(markdown_reader): decouple js extractor and simplify interactive elements"
```

---

### Task 2: 表格跨页智能切分与表头自动回填

**Files:**
- Modify: `core/readers/markdown_reader.py:373-420`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: `blocks: list[str]`, `self.chunk_char_limit`
- Produces: `_chunk_blocks` 切分后的 `list[str]`，所有跨页表格在后续分页均自动重放表头行

- [ ] **Step 1: 在 `tests/test_readers.py` 中编写长表格切分与表头回填测试**

```python
def test_chunk_blocks_table_header_repetition(self):
    reader = InlineMarkdownReader(chunk_char_limit=450)
    # 构造一个 20 行的表格
    header = "| 序号 | 名称 | 描述 |"
    separator = "| --- | --- | --- |"
    rows = [f"| {i} | [条目{i}][{i}] | 这是关于第{i}项的长文本详细说明信息 |" for i in range(1, 21)]
    table_block = "\n".join([header, separator] + rows)

    chunks = reader._chunk_blocks([table_block], url="https://example.com", title="表格测试")
    self.assertGreater(len(chunks), 1)

    # 验证每一个切片分页都包含完整的表头与分隔行
    for idx, chunk in enumerate(chunks, 1):
        self.assertIn(header, chunk, f"分页 {idx} 缺少表头行")
        self.assertIn(separator, chunk, f"分页 {idx} 缺少分隔行")
        self.assertLessEqual(len(chunk), 450, f"分页 {idx} 字符数超出预算: {len(chunk)}")
```

- [ ] **Step 2: 运行测试验证失败**

运行: `python -m unittest tests.test_readers.TestInlineMarkdownReader.test_chunk_blocks_table_header_repetition`
预期结果: FAIL（当前切分器未拆分单表格 block，字符数超出 450 且只有 1 页）。

- [ ] **Step 3: 在 `core/readers/markdown_reader.py` 中重构 `_chunk_blocks` 表格切分逻辑**

1. 编写辅助函数 `_is_markdown_table(block: str) -> tuple[bool, list[str], list[str]]`，识别多行表格并提取 `header_lines`（表头与分隔符）及 `data_rows`；
2. 在装箱切分循环中：
   - 若遇到表格块且整体超出当前页剩余预算：
     - 若当前页已有其他前置块且容纳不下 `header_lines` + 1 行数据，先将当前页推入 `groups`；
     - 逐行装入 `data_rows`：当当前页达到字符预算时推入 `groups`；
     - **新分页首部自动前置 `header_lines`**，再继续装入后续 `data_rows`；
3. 确保每次装箱严格以 `_render_chunk` 后的总字符长测量，严防越界。

- [ ] **Step 4: 运行测试验证通过**

运行: `python -m unittest tests.test_readers.TestInlineMarkdownReader.test_chunk_blocks_table_header_repetition`
预期结果: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/markdown_reader.py tests/test_readers.py
git commit -m "feat(markdown_reader): support table-aware chunking and automatic header repetition"
```

---

### Task 3: 超大块行级微切分兜底与极限长表防膨胀集成验证

**Files:**
- Modify: `core/readers/markdown_reader.py:373-420`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: 含有极端大文本（超长无表格代码块、列表或段落）的 `blocks`
- Produces: 保证任意类型超限块均可在行级优雅切分，单页永远不突破预算

- [ ] **Step 1: 在 `tests/test_readers.py` 中编写极端大文本与 GTNH Wiki 密集表防膨胀集成测试**

```python
def test_chunk_blocks_giant_block_fallback_splitting(self):
    reader = InlineMarkdownReader(chunk_char_limit=300)
    # 单个超过 2000 字符的巨大列表块（非表格）
    giant_list_block = "\n".join([f"- 项目 {i}: [测试链接{i}][{i}] 详细数据填充文本" for i in range(1, 60)])
    
    chunks = reader._chunk_blocks([giant_list_block], url="https://example.com", title="超大块测试")
    self.assertGreater(len(chunks), 3)
    for idx, chunk in enumerate(chunks, 1):
        self.assertLessEqual(len(chunk), 300, f"分页 {idx} 字符数超出预算: {len(chunk)}")

def test_gtnh_dense_navigation_table_snapshot_limit(self):
    # 模拟包含 50 行密集多链接的复杂导航表
    reader = InlineMarkdownReader(chunk_char_limit=2000)
    cols = ["Introduction", "World Gen", "World Seeds", "Crops", "Thaumcraft"]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    ref_id = 1
    for r in range(50):
        row_cells = [f"[{col} Item {r}][{ref_id + i}]" for i, col in enumerate(cols)]
        ref_id += len(cols)
        rows.append("| " + " | ".join(row_cells) + " |")
    giant_wiki_table = "\n".join([header, sep] + rows)

    chunks = reader._chunk_blocks([giant_wiki_table], url="https://wiki.gtnewhorizons.com/wiki/Main_Page", title="GT New Horizons")
    self.assertGreater(len(chunks), 5)
    for idx, chunk in enumerate(chunks, 1):
        self.assertLessEqual(len(chunk), 2000, f"Wiki 表格分页 {idx} 字符数超出预算: {len(chunk)}")
```

- [ ] **Step 2: 运行测试验证**

运行: `python -m unittest tests.test_readers.TestInlineMarkdownReader.test_chunk_blocks_giant_block_fallback_splitting tests.test_readers.TestInlineMarkdownReader.test_gtnh_dense_navigation_table_snapshot_limit`
预期结果: FAIL 或 PASS（根据 Task 2 兜底实现的完整度）。

- [ ] **Step 3: 完善 `core/readers/markdown_reader.py` 中的行级微切分兜底**

对任意单个非表格 Block，若单块长度使得渲染超出 `chunk_char_limit`，按 `\n` 进行行级拆分装箱，消除任何潜在击穿预算的路径。

- [ ] **Step 4: 运行所有 Reader 测试验证通过**

运行: `python -m unittest tests.test_readers`
预期结果: 全部 PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/markdown_reader.py tests/test_readers.py
git commit -m "feat(markdown_reader): add line-level fallback splitting for giant blocks"
```

---

### Task 4: 文档同步与全量回归测试

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新架构文档与变更日志**

- 更新 `docs/ARCHITECTURE.md`：在阅读器部分记录内联 Markdown 格式精简为 `[文本][Ref]` 及表格跨页表头自动补齐机制；
- 更新 `CHANGELOG.md`：在 `[v1.3.0]` 中记录排版精简、表格跨页表头补齐与单页防膨胀增强。

- [ ] **Step 2: 运行全量测试套件验证**

运行: `python -m unittest discover tests`（带 `BypassSandbox: true`）
预期结果: 全部 226+ 项测试 100% PASS。

- [ ] **Step 3: 提交更改**

```bash
git add docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: update architecture and changelog for markdown formatting and table pagination"
```
