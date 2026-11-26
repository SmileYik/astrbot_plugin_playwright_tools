# Markdown 阅读器 Ref ID 统一图片与链接 URL 查询实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Markdown 页面阅读器统一普通图片的 Ref 编号与 URL 隐藏机制，并在 `pw_read` 工具中新增 `ref` 参数，支持通过 Ref ID 秒级查询对应图片或超链接的结构化元数据（类型、标题/描述及完整 URL）。

**Architecture:** 采用快照缓存原地检索方案。在 JavaScript 提取阶段，普通 `<img>` 标签统一分配 Ref ID 并将长 URL 隐藏为 `[Ref: X] [图片: alt]`，同时为超链接与图片解析绝对路径并写入快照字典 `ref_map`；在 `pw_read` 工具层与 `PageHandler` 中扩展 `ref` 参数，优先从当前会话快照的 `ref_map` 内存字典中寻址并格式化输出高可读性结构化信息。

**Tech Stack:** Python 3.10+, Playwright, AstrBot Plugin API, unittest

**Spec:** `docs/superpowers/specs/2026-11-26-markdown-ref-url-query-design.md`

## Global Constraints

- **执行性能**：Ref 查询必须基于快照缓存秒级响应（内存字典寻址，耗时 < 1ms）。
- **文档规范**：严格遵循 `AGENT.md` 规范，语言凝练简洁，不出现绝对化词汇（如“彻底”、“完美”等）。
- **日志规范**：仅允许使用 `from astrbot.api import logger`，严禁 `import logging`。
- **单测要求**：遵循测试规范，所有基础单元测试保持 100% 绿灯通过。

## Review Focus

- 当普通 `<img>` 无 `alt` 属性时，Markdown 格式化应平稳降级为 `[Ref: X] [图片]`，不抛异常或输出冗余标点。
- 当 `<a>` 标签内嵌套 `<img>` 时，元数据需同时保留链接目标 `href` 与内嵌图片的 `src`，查询时标明为“超链接 (含图片)”。
- 当用户传入不存在的 `ref` 时，返回友好的未匹配提示并给出 `pw_read(refresh=True)` 刷新指引。
- 当查询的 `ref` 为纯表单控件或按钮（无 `href` 且无 `src`）时，结构化返回其控件类型并提示该元素不含 URL 及建议的交互操作。
- 在未指定 `ref` 时，`pw_read` 原有的 `page` 分页、`keyword` 检索和 `refresh` 刷新逻辑必须完全保持向后兼容。

---

### Task 1: InlineMarkdownReader 提取脚本与图片 Ref 编号改造

**Files:**
- Modify: `core/readers/markdown_reader.py:58-175, 260-280, 410-435`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: `PageSnapshot` (from `core/readers/base.py`)
- Produces: `InlineMarkdownReader.extract_snapshot` 生成的 `snapshot.ref_map` 包含 `href`, `src`, `url`, `tag`, `text`, `alt`；`snapshot.chunks` 中图片格式化为 `[Ref: X] [图片: alt]`。

- [ ] **Step 1: 编写失败的单元测试**

在 `tests/test_readers.py` 中新增针对普通图片分配 Ref ID 与 `ref_map` 保存 `href`/`src` 的测试用例：
```python
async def test_inline_markdown_reader_extracts_img_ref_and_urls(self):
    reader = InlineMarkdownReader(chunk_char_limit=2000, mask_passwords=True)
    mock_page = AsyncMock()

    async def fake_eval(script):
        return {
            "title": "测试图文页",
            "url": "https://example.com/article",
            "blocks": [
                "# 文章标题",
                "[Ref: 1] [图片: 架构图]",
                "- [Ref: 2] [链接: 官方文档]",
            ],
            "elements": [
                {"ref": 1, "tag": "img", "text": "架构图", "alt": "架构图", "src": "https://example.com/arch.png", "href": ""},
                {"ref": 2, "tag": "a", "text": "官方文档", "alt": "", "src": "", "href": "https://example.com/docs"},
            ],
            "allocated_count": 2,
        }

    mock_page.evaluate = fake_eval
    snapshot = await reader.extract_snapshot(mock_page, "https://example.com/article")
    self.assertIn("1", snapshot.ref_map)
    self.assertEqual(snapshot.ref_map["1"]["tag"], "img")
    self.assertEqual(snapshot.ref_map["1"]["src"], "https://example.com/arch.png")
    self.assertIn("2", snapshot.ref_map)
    self.assertEqual(snapshot.ref_map["2"]["href"], "https://example.com/docs")
```

- [ ] **Step 2: 运行测试验证失败**

运行: `python -m unittest tests.test_readers.TestInlineMarkdownReader.test_inline_markdown_reader_extracts_img_ref_and_urls`
预期结果: FAIL 或断言失败。

- [ ] **Step 3: 修改 `core/readers/markdown_reader.py`**

1. 在 `get_js_extractor_script()` 中：
   - 更新 `isInteractive` 或单独判定图片：识别 `tag === 'img'`，为可见的 `<img>` 分配 `data-astr-ref` 并记录 `rawElements`。
   - 在 `formatInteractive` 中提取 `href`（通过 `node.href || (node.getAttribute && node.getAttribute('href')) || ''`）；若是 `<a>` 且包含子 `img`，提取子 `img` 的 `src` 与 `alt`。
   - 在 `renderInline` 与 `traverse` 中，将 `img` 渲染改为 `[Ref: ${ref}] [图片: ${alt}]`（无 alt 时输出 `[Ref: ${ref}] [图片]`）。
2. 在 `extract_snapshot()` 中：
   - 构建 `ref_map` 时保留 `href`、`src`、`url`（取非空的 `href` 或 `src`）、`tag`、`text`、`alt`。

- [ ] **Step 4: 运行测试验证通过**

运行: `python -m unittest tests.test_readers.TestInlineMarkdownReader`
预期结果: 全部 PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/markdown_reader.py tests/test_readers.py
git commit -m "feat(reader): assign ref id to images and extract urls into ref_map"
```

---

### Task 2: 工具 Schema 扩展与 PwReadTool 透传参数

**Files:**
- Modify: `tools/schemas.py:32-48`
- Modify: `tools/tools.py:246-270`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `PW_READ_SCHEMA`
- Produces: `pw_read` 工具对外暴露 `ref` 可选参数，并在 `call()` 中将其解析为字符串透传给 `page_handler.read_page`。

- [ ] **Step 1: 编写失败的单元测试**

在 `tests/test_tools.py` 中增加对 `PW_READ_SCHEMA` 包含 `ref` 参数与 `PwReadTool.call` 透传 `ref` 的测试用例：
```python
def test_pw_read_schema_has_ref_property(self):
    self.assertIn("ref", PW_READ_SCHEMA["properties"])
    self.assertEqual(PW_READ_SCHEMA["properties"]["ref"]["type"], "string")

def test_pw_read_tool_passes_ref_parameter(self):
    with patch("asyncio.wait_for", fake_wait_for):
        run_coro(self.read_tool.call(self.mock_context_wrapper, ref="42"))
    self.mock_page_handler.read_page.assert_called_once()
    kwargs = self.mock_page_handler.read_page.call_args.kwargs
    self.assertEqual(kwargs.get("ref"), "42")
```

- [ ] **Step 2: 运行测试验证失败**

运行: `python -m unittest tests.test_tools.TestTools.test_pw_read_schema_has_ref_property tests.test_tools.TestTools.test_pw_read_tool_passes_ref_parameter`
预期结果: FAIL，提示找不到 `"ref"`。

- [ ] **Step 3: 修改 `tools/schemas.py` 与 `tools/tools.py`**

1. 在 `tools/schemas.py` 的 `PW_READ_SCHEMA["properties"]` 中添加：
   ```python
   "ref": {
       "type": "string",
       "description": "要查询详细信息或目标 URL 的元素 Ref 编号（如 '1', '2'）。传入时将直接返回该 Ref 对应的类型、标题及完整链接/图片地址 (可选)",
   },
   ```
2. 在 `tools/tools.py` 的 `PwReadTool.call()` 中解析 `ref`：
   ```python
   ref = str(kwargs.get("ref") or "").strip()
   ```
   并将 `ref=ref` 传入 `self.page_handler.read_page`。

- [ ] **Step 4: 运行测试验证通过**

运行: `python -m unittest tests.test_tools.TestTools`
预期结果: 全部 PASS。

- [ ] **Step 5: 提交更改**

```bash
git add tools/schemas.py tools/tools.py tests/test_tools.py
git commit -m "feat(tools): add ref parameter to pw_read schema and tool handler"
```

---

### Task 3: PageHandler.read_page 实现 Ref 结构化详情查询

**Files:**
- Modify: `tools/handlers/page_handler.py:116-186`
- Test: `tests/test_page_handler.py`

**Interfaces:**
- Consumes: `ctx.ref_map` (from `BrowserSessionContext`), `ref` 参数
- Produces: `read_page(ref=...)` 返回高可读性结构化 Markdown 字符串；非 URL 元素或不存在的 Ref 返回精确提示。

- [ ] **Step 1: 编写失败的单元测试**

在 `tests/test_page_handler.py` 中新增 `read_page` 支持 `ref` 查询的测试用例：
```python
def test_read_page_query_ref_link_and_img(self):
    self.fake_snapshot.ref_map = {
        "1": {"ref": "1", "tag": "a", "text": "官方文档", "href": "https://example.com/docs", "src": ""},
        "2": {"ref": "2", "tag": "img", "text": "架构图", "alt": "架构图", "href": "", "src": "https://example.com/arch.png"},
        "3": {"ref": "3", "tag": "a", "text": "大图预览", "href": "https://example.com/view", "src": "https://example.com/thumb.png"},
        "4": {"ref": "4", "tag": "button", "text": "提交"},
    }
    # 1. 链接查询
    res_link = run_coro(self.handler.read_page("s1", "u1", ref="1"))
    self.assertIn("=== Ref 元素详情查询: [1] ===", res_link)
    self.assertIn("元素类型: 超链接", res_link)
    self.assertIn("https://example.com/docs", res_link)

    # 2. 图片查询
    res_img = run_coro(self.handler.read_page("s1", "u1", ref="2"))
    self.assertIn("元素类型: 图片", res_img)
    self.assertIn("https://example.com/arch.png", res_img)

    # 3. 含图链接查询
    res_both = run_coro(self.handler.read_page("s1", "u1", ref="3"))
    self.assertIn("元素类型: 超链接 (含图片)", res_both)
    self.assertIn("https://example.com/view", res_both)
    self.assertIn("https://example.com/thumb.png", res_both)

    # 4. 普通按钮查询
    res_btn = run_coro(self.handler.read_page("s1", "u1", ref="4"))
    self.assertIn("该元素不包含可跳转的超链接或图片 URL", res_btn)

    # 5. 不存在的 Ref
    res_none = run_coro(self.handler.read_page("s1", "u1", ref="999"))
    self.assertIn("未在当前快照中找到 Ref ID 为 '999' 的元素", res_none)
```

- [ ] **Step 2: 运行测试验证失败**

运行: `python -m unittest tests.test_page_handler.TestPageHandler.test_read_page_query_ref_link_and_img`
预期结果: FAIL。

- [ ] **Step 3: 修改 `tools/handlers/page_handler.py`**

在 `read_page` 方法中增加 `ref: str = ""` 参数并实现格式化响应逻辑：
1. 校验 `ref = str(ref or "").strip()`。若 `ref` 存在：
   - 若当前快照存在且有效，从 `ctx.ref_map` 中提取；若快照为空或脏则先提炼快照。
   - 若 `ref not in ctx.ref_map`，返回规范的未找到提示：
     `未在当前快照中找到 Ref ID 为 '{ref}' 的元素。请确认编号是否正确，或调用 pw_read(refresh=True) 刷新快照。`
   - 若找到对应元素 `el`：
     - 若 `href` 与 `src` 均存在：类型显示为 `超链接 (含图片)`，分别输出 `链接文本`、`目标地址`、`图片地址`。
     - 若仅有 `href`：类型显示为 `超链接`，输出 `链接文本`、`目标地址`。
     - 若仅有 `src`：类型显示为 `图片`，输出 `图片描述`、`图片地址`。
     - 若均无：输出元素类型（按钮/输入框等）与文本，并提示 `该元素不包含可跳转的超链接或图片 URL。如需操作请调用 pw_interact(action=..., ref='{ref}')。`
2. 若 `ref` 为空，继续执行原有 `keyword` 检索或 `format_chunk` 翻页分支。

- [ ] **Step 4: 运行测试验证通过**

运行: `python -m unittest tests.test_page_handler.TestPageHandler`
预期结果: 全部 PASS。

- [ ] **Step 5: 提交更改**

```bash
git add tools/handlers/page_handler.py tests/test_page_handler.py
git commit -m "feat(page_handler): implement ref query in read_page"
```

---

### Task 4: 文档同步与全量回归测试验证

**Files:**
- Modify: `skills/playwright-tool/SKILL.md`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: 全功能与全接口定义
- Produces: 准确同步并凝练描述 `pw_read(ref='...')` 的功能文档；全量基础单元测试 100% 运行通过。

- [ ] **Step 1: 更新 `skills/playwright-tool/SKILL.md`**

在“步骤二：结构化正文阅读与快照提取 (`pw_read`)”中追加：
- **查询元素详情与 URL**：`pw_read(ref='1')`
  通过 Ref ID 查询指定元素的类型、标题文本及完整超链接或图片 URL，适合在需要下载图片、核对目标跳转地址时按需查询。

- [ ] **Step 2: 更新 `README.md`、`docs/ARCHITECTURE.md` 与 `CHANGELOG.md`**

1. `README.md`：在 `pw_read` 工具参数表格中加入 `ref` 参数说明。
2. `docs/ARCHITECTURE.md`：在 Markdown 阅读器与工具体系章节记录图片 Ref 编号收敛与按需查询能力。
3. `CHANGELOG.md`：在最新版本记录新增的 `pw_read` Ref URL 查询与 Markdown 图片 Ref 收敛功能。

- [ ] **Step 3: 运行全量基础单元测试验证**

运行: `python -m unittest discover tests` (结合实际环境配置运行)
预期结果: 所有单测均 100% 通过，无回归问题。

- [ ] **Step 4: 提交文档与最终验证**

```bash
git add skills/playwright-tool/SKILL.md README.md docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: document ref query parameter and image ref behavior"
```
