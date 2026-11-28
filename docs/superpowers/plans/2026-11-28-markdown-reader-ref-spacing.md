# Markdown Reader Ref 前缀与空白分隔 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `InlineMarkdownReader` 提取的 Ref ID 增加 `@r` 前缀（保持精确匹配），压缩多余空白字符并在交互控件边界自动补空格分隔，同时同步更新 `skills/`、项目文档与单元测试。

**Architecture:** 所有 DOM 提取、Ref 分配与内联排版逻辑均位于 `core/readers/markdown_extractor.js`；`core/readers/markdown_reader.py` 仅透传 `ref_map` 与提供工具元数据。通过在 JS 端生成 `@rN` 字符串写入 `data-astr-ref` 与 `elements[].ref`，下游所有 Handler 无需修改即可天然保持对 `@rN` 的精确匹配。

**Tech Stack:** Python 3.12 (`unittest`), JavaScript (ES6 in `markdown_extractor.js`), Node.js (用于单测直接执行 JS 提取脚本)

**Spec:** [2026-11-28-markdown-reader-ref-spacing-design.md](../specs/2026-11-28-markdown-reader-ref-spacing-design.md)

## Global Constraints

- 严格遵守 `AGENT.md`：文档与注释凝练简洁，不使用“彻底”、“根治”、“杜绝”、“完全”等绝对化词汇。
- 严禁在 `core/`、`tools/` 中使用 `import logging`，仅能使用 `from astrbot.api import logger`。
- 保持下游 `ref` 精确匹配语义：调用方必须传入 `@r1` 才能匹配，不兼容无前缀数字。
- 每次核心代码修改后必须运行 `.venv/bin/python -m unittest discover tests` 确保全量单测通过。

## Review Focus

- 复用已有 `data-astr-ref="@r1"` 属性二次提取时，不能重复拼接成 `@r@r1`，且不能重复递增 `allocatedCount`。
- 相邻交互控件之间（包括被 `<strong>` / `<em>` / `<span>` 包裹的交互控件）必须用单个空格分隔，如 `[A][@r1] [B][@r2]`。
- HTML 文本节点中的多空格、换行与制表符应压缩为单个空格，同时保留 `<br>` 产生的真实 `\n` 换行。
- 非交互普通行内标签与紧邻文本之间（如 `<strong>100</strong>元`）不应被强行插入多余空格。
- 块级容器（`div`）中混排文本节点与内联控件时，`inlineBuffer` 拼接也应遵循相同的边界分隔与空白压缩规则。

---

### Task 1: 更新 `markdown_extractor.js` 的 `@r` 前缀与空白分隔逻辑

**Files:**
- Modify: `core/readers/markdown_extractor.js:147-312`
- Test: `tests/test_readers.py:206-292`

**Interfaces:**
- Produces: `markdown_extractor.js` 返回 `{ title, url, blocks, elements, allocated_count }`，其中 `elements[i].ref` 与 DOM `data-astr-ref` 均为 `'@r' + N` 格式。

- [ ] **Step 1: 在 `tests/test_readers.py` 编写针对 JS 行为的失败单测并更新 mock 数据**

在 `tests/test_readers.py` 中：
1. 将 `test_extract_snapshot_with_mock_page` 与 `test_inline_markdown_reader_extracts_img_ref_and_urls` 中的 mock `ref` 更新为 `"@r1"`、`"@r2"`、`"@r3"`。
2. 新增测试方法 `test_js_extractor_ref_prefix_and_spacing`（使用 `subprocess.run(["node", "-e", ...])` 构造轻量 mock DOM，直接执行 `InlineMarkdownReader().get_js_extractor_script(start_ref=1)`），验证以下 5 种输入场景：
   - 相邻交互控件 `<a>A</a><a>B</a>` 输出 `"[A][@r1] [B][@r2]"`，且 `elements[0]["ref"] == "@r1"`、`data-astr-ref == "@r1"`。
   - 包裹在 `<strong>` 中的交互控件 `<strong><a>A</a></strong><button>B</button>` 输出 `"**[A][@r1]** [按钮: B][@r2]"`。
   - 多余空白文本 `"  点击 \n\t  "` + `<a>这里</a>` + `"  继续  "` 输出 `"点击 [这里][@r1] 继续"`。
   - 普通行内标签 `<strong>100</strong>元` 输出 `"**100**元"`。
   - 已有 `data-astr-ref="@r9"` 的节点再次提取时保持 `"@r9"` 不变且不计入 `allocated_count`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_readers -v`
Expected: FAIL（`test_js_extractor_ref_prefix_and_spacing` 断言失败，因为当前输出为 `[A][1][B][2]` 且未压缩多空格）。

- [ ] **Step 3: 实现 `core/readers/markdown_extractor.js` 的 Ref 前缀与空白分隔**

在 `core/readers/markdown_extractor.js` 中修改：
1. **Ref 分配（第 158-168 行）**：
   - 若节点已有 `data-astr-ref`，读取字符串值 `existing = node.getAttribute('data-astr-ref')`，非空则直接复用 `ref = existing`（兼容非空字符串，不重复加 `@r`）。
   - 否则分配 `ref = '@r' + (nextRef++)`，`allocatedCount++`，并写入 `node.setAttribute('data-astr-ref', ref)`。
2. **空白压缩与行内拼接辅助函数**：
   - 新增 `collapseSpaces(str)`：将 `[ \t\r\n]+`（或分段按 `\n` 拆分每行后再将 `[ \t]+` 压缩为单空格），保留 `<br>` 产生的 `\n`。
   - 新增 `joinInlineParts(parts)`：过滤空串后遍历拼接，若当前累积结果末尾和下一个非空片段开头均不是空白字符，且相邻两项中至少有一项包含交互控件标记（例如通过 `[...][@rN]` 或节点交互标记判断），则中间插入 `' '`；最后对每行合并连续空格。
   - 在 `renderInline` 的文本节点（第 150 行）、`strong`/`b`（第 174 行）、`em`/`i`（第 178 行）、通用子节点（第 182 行）以及 `traverse` 的 `inlineBuffer`（第 291-311 行）中统一使用上述逻辑。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m unittest tests.test_readers -v`
Expected: PASS

- [ ] **Step 5: 提交 Task 1**

```bash
git add core/readers/markdown_extractor.js tests/test_readers.py
git commit -m "feat(reader): add @r ref prefix and normalize inline spacing in markdown extractor"
```

---

### Task 2: 更新 `markdown_reader.py` 工具元数据示例

**Files:**
- Modify: `core/readers/markdown_reader.py:394-398`
- Test: `tests/test_readers.py`

- [ ] **Step 1: 在 `tests/test_readers.py` 增加元数据示例断言**

在 `tests/test_readers.py` 中新增 `test_inline_markdown_reader_tool_metadata_ref_example`，断言 `InlineMarkdownReader().get_tool_metadata()["parameters"]["properties"]["ref"]["description"]` 包含 `"@r1"`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests.test_readers.TestInlineMarkdownReader.test_inline_markdown_reader_tool_metadata_ref_example -v`
Expected: FAIL

- [ ] **Step 3: 更新 `core/readers/markdown_reader.py` 元数据描述**

将 `core/readers/markdown_reader.py` 第 396 行的 `"（如 '1', '2'）"` 更新为 `"（如 '@r1', '@r2'）"`。

- [ ] **Step 4: 运行全量测试确认通过**

Run: `.venv/bin/python -m unittest discover tests`
Expected: PASS（全量单测 100% 通过）

- [ ] **Step 5: 提交 Task 2**

```bash
git add core/readers/markdown_reader.py tests/test_readers.py
git commit -m "chore(reader): update pw_read ref parameter example to @r prefix"
```

---

### Task 3: 同步更新 `skills/` 与项目文档

**Files:**
- Modify: `skills/playwright-tool/SKILL.md:33-64`
- Modify: `README.md:18,182`
- Modify: `docs/ARCHITECTURE.md:139`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新 `skills/playwright-tool/SKILL.md`**

将 `skills/playwright-tool/SKILL.md` 中 Markdown 模式相关的 Ref 示例从 `'12'`、`[12]`、`[15]` 等更新为 `'@r12'`、`[@r12]`、`[@r15]` 等（保留 `'e1'` 作为 ARIA 模式示例，并明确说明 Markdown 模式为 `@r` 前缀字符串，调用时需传入完整 Ref）。

- [ ] **Step 2: 更新 `README.md`、`docs/ARCHITECTURE.md` 与 `CHANGELOG.md`**

- `README.md`：将 `[按钮: 登录][1]` 与 `'1'` 示例更新为 `[按钮: 登录][@r1]` 与 `'@r1'`。
- `docs/ARCHITECTURE.md`：将第 139 行“当 Ref ID 为数字编号（如 `'1'`）”更新为“当 Ref ID 为 `@r` 前缀编号（如 `'@r1'`）”。
- `CHANGELOG.md`：在顶部新增一条简明记录，说明 Markdown 阅读器新增 `@r` Ref 前缀与行内空白分隔优化。

- [ ] **Step 3: 运行全量单测与文档检查**

Run: `.venv/bin/python -m unittest discover tests`
Expected: PASS

- [ ] **Step 4: 提交 Task 3**

```bash
git add skills/playwright-tool/SKILL.md README.md docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: update skills and docs for @r ref prefix and spacing"
```
