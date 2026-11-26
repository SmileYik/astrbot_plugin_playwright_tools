# ARIA 阅读器语义树 URL 隐藏与 Ref 元数据契约对齐实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底剥离 `AriaSnapshotReader` 语义树中的 `- /url: <url>` 节点并精简无名 URL 链接，同时在快照提炼阶段完整提取链接 `href` 与图片 `src`，将 `ref_map` 契约与 `InlineMarkdownReader` 彻底对齐，实现统一的 `pw_read(ref='eX')` 结构化查询。

**Architecture:** 在 `AriaSnapshotReader.extract_snapshot` 中引入单遍 YAML 扫描状态机，将 `- /url:` 行关联至父级 Ref ID 后从正文中完全移除，并清理父行尾部多余冒号；对直接以 URL 为名的链接去除引号 URL 精简为 `- link [ref=...]`；为图片元素并发拉取 `src`。标准化后的 `ref_map` 直接复用 `PageHandler.read_page` 原生查询逻辑，实现零耦合。

**Tech Stack:** Python 3.10+, Playwright, AstrBot Plugin API, unittest

**Spec:** `docs/superpowers/specs/2026-11-26-aria-reader-url-hiding-and-ref-alignment-design.md`

## Global Constraints

- **执行性能**：YAML 清洗与超链接提取在内存中单遍完成（耗时 < 1ms）；图片提取并发完成。
- **文档规范**：严格遵循 `AGENT.md` 规范，语言凝练简洁，不出现绝对化词汇。
- **日志规范**：仅允许使用 `from astrbot.api import logger`，严禁 `import logging`。
- **单测要求**：遵循测试规范，所有基础单元测试保持 100% 绿灯通过。

## Review Focus

- 当 Playwright 原生输出形如 `- link "登录" [ref=e1] [cursor=pointer]:` 并在下行附带 `- /url: ...` 时，不仅需删除子行，还必须剥离父行末尾的多余冒号 `:`，不能破坏后续 YAML 的层级解析。
- 当链接名称本身就是 URL 时（如 `- link "https://example.com" [ref=e2]`），正文需精简为 `- link [ref=e2]`，且 `ref_map['e2']['href']` 必须完整保留该 URL。
- 当 `AriaSnapshotReader.extract_snapshot` 遇到图片元素时，若 `page` 具备 `locator`，并发读取 `src`；若 `page` 缺少该方法（如简单 Mock）时平滑降级，不抛出异常。
- 当 `link` 节点内嵌套了子 `img` 节点时，父级 `link` 应能够关联子图片的 `src`，在查询时被正确识别为“超链接 (含图片)”。
- `PageHandler.read_page(ref=...)` 在 ARIA 模式下与 Markdown 模式下返回格式与文案保持完全统一。

---

### Task 1: ARIA 快照 YAML 清洗与链接 URL 提取

**Files:**
- Modify: `core/readers/aria_reader.py:150-185`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: `raw_yaml` (from Playwright `aria_snapshot(mode='ai')`)
- Produces: 清洗后无 `- /url:`、无冗余尾部冒号的 `snapshot.raw_content`；标准化的 `snapshot.ref_map`，其中 `link` 元素包含 `href`, `url`, `tag="a"`, `role="link"`, `text`。

- [ ] **Step 1: 编写失败的单元测试**

在 `tests/test_readers.py` 的 `TestAriaSnapshotReader` 中新增测试用例：
```python
async def test_aria_reader_url_filtering_and_href_extraction(self):
    mock_page = MagicMock()
    mock_root = AsyncMock()
    raw_yaml = (
        '- document [ref=e1]:\n'
        '  - heading "Header" [level=1] [ref=e2]\n'
        '  - link "官方文档" [ref=e3] [cursor=pointer]:\n'
        '    - /url: https://example.com/docs\n'
        '  - link "https://example.com/page2" [ref=e4] [cursor=pointer]:\n'
        '    - /url: https://example.com/page2\n'
    )
    mock_root.aria_snapshot = AsyncMock(return_value=raw_yaml)
    mock_page.locator.return_value = mock_root
    mock_page.url = "https://example.com"
    mock_page.title = "测试页面"

    reader = AriaSnapshotReader()
    snapshot = await reader.extract_snapshot(mock_page)

    # 1. 验证正文中彻底剥离了 - /url:
    self.assertNotIn("/url:", snapshot.raw_content)
    # 2. 验证父行末尾冒号被剥离
    self.assertIn('link "官方文档" [ref=e3] [cursor=pointer]\n', snapshot.raw_content + '\n')
    self.assertNotIn('link "官方文档" [ref=e3] [cursor=pointer]:', snapshot.raw_content)
    # 3. 验证 URL 作为文本的链接被精简
    self.assertIn('link [ref=e4] [cursor=pointer]', snapshot.raw_content)
    self.assertNotIn('link "https://example.com/page2"', snapshot.raw_content)
    # 4. 验证 ref_map 中正确记录 href 与 url
    self.assertIn("e3", snapshot.ref_map)
    self.assertEqual(snapshot.ref_map["e3"]["href"], "https://example.com/docs")
    self.assertEqual(snapshot.ref_map["e3"]["url"], "https://example.com/docs")
    self.assertEqual(snapshot.ref_map["e3"]["tag"], "a")
    self.assertIn("e4", snapshot.ref_map)
    self.assertEqual(snapshot.ref_map["e4"]["href"], "https://example.com/page2")
```

- [ ] **Step 2: 运行测试验证失败**

运行: `python -m unittest tests.test_readers.TestAriaSnapshotReader.test_aria_reader_url_filtering_and_href_extraction`
预期结果: FAIL。

- [ ] **Step 3: 修改 `core/readers/aria_reader.py`**

在 `AriaSnapshotReader.extract_snapshot` 中实现单遍 YAML 扫描状态机：
1. 逐行解析缩进深度（前导空格数）与内容；
2. 匹配 `[ref=([^\]]+)]` 获取 `ref_id`；
3. 匹配 `- ([a-zA-Z0-9_-]+)(?:\s+"([^"]*)")?` 获取 `role` 与 `name`；
   - 映射 `tag`：`link` -> `"a"`, `img`/`image` -> `"img"`, `button` -> `"button"`, `textbox` -> `"input"` 等；
   - 若 `name` 满足 `^https?://`，将行中的 `"https?://..."` 移除，正文化简为 `- link [ref=...]`；
4. 若当前行是 `\s*-\s*/url:\s*(\S+)`：
   - 提取 `<url>`，回填给上一级父节点的 `href` 与 `url`；
   - 该行丢弃，不加入输出列表；
   - 如果上一级父行以 `:` 结尾，将该冒号移除；
5. 构建包含 `ref`, `tag`, `role`, `type`, `text`, `alt`, `href`, `src`, `url` 的标准元素字典。

- [ ] **Step 4: 运行测试验证通过**

运行: `python -m unittest tests.test_readers.TestAriaSnapshotReader.test_aria_reader_url_filtering_and_href_extraction`
预期结果: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/aria_reader.py tests/test_readers.py
git commit -m "feat(aria_reader): strip /url lines and extract href into ref_map"
```

---

### Task 2: ARIA 图片元素 `src` 提取与嵌套图文关联

**Files:**
- Modify: `core/readers/aria_reader.py:150-200`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: `page.locator(f"aria-ref={ref}")`
- Produces: `snapshot.ref_map` 中包含图片角色的元素填充 `src` 与 `url`；被 `link` 嵌套的图片将 `src` 回填给父级 `link`。

- [ ] **Step 1: 编写失败的单元测试**

在 `tests/test_readers.py` 的 `TestAriaSnapshotReader` 中新增测试用例：
```python
async def test_aria_reader_image_src_and_nested_link_extraction(self):
    mock_page = MagicMock()
    mock_root = AsyncMock()
    raw_yaml = (
        '- document [ref=e1]:\n'
        '  - link [ref=e2]:\n'
        '    - /url: https://example.com/item\n'
        '    - img "商品缩略图" [ref=e3]\n'
        '  - img "独立照片" [ref=e4]\n'
    )
    mock_root.aria_snapshot = AsyncMock(return_value=raw_yaml)
    mock_page.locator.return_value = mock_root
    mock_page.url = "https://example.com"
    mock_page.title = "测试页面"

    mock_loc_e3 = AsyncMock()
    mock_loc_e3.count = AsyncMock(return_value=1)
    mock_loc_e3.evaluate = AsyncMock(return_value="https://example.com/thumb.jpg")

    mock_loc_e4 = AsyncMock()
    mock_loc_e4.count = AsyncMock(return_value=1)
    mock_loc_e4.evaluate = AsyncMock(return_value="https://example.com/photo.jpg")

    def mock_locator_router(sel):
        if sel == "aria-ref=e3":
            return mock_loc_e3
        elif sel == "aria-ref=e4":
            return mock_loc_e4
        return mock_root
    mock_page.locator.side_effect = mock_locator_router

    reader = AriaSnapshotReader()
    snapshot = await reader.extract_snapshot(mock_page)

    # 1. 验证独立图片的 src
    self.assertIn("e4", snapshot.ref_map)
    self.assertEqual(snapshot.ref_map["e4"]["src"], "https://example.com/photo.jpg")
    self.assertEqual(snapshot.ref_map["e4"]["url"], "https://example.com/photo.jpg")
    self.assertEqual(snapshot.ref_map["e4"]["tag"], "img")

    # 2. 验证嵌套在链接内的图片与其父级链接
    self.assertIn("e3", snapshot.ref_map)
    self.assertEqual(snapshot.ref_map["e3"]["src"], "https://example.com/thumb.jpg")
    self.assertIn("e2", snapshot.ref_map)
    self.assertEqual(snapshot.ref_map["e2"]["href"], "https://example.com/item")
    self.assertEqual(snapshot.ref_map["e2"]["src"], "https://example.com/thumb.jpg")
```

- [ ] **Step 2: 运行测试验证失败**

运行: `python -m unittest tests.test_readers.TestAriaSnapshotReader.test_aria_reader_image_src_and_nested_link_extraction`
预期结果: FAIL。

- [ ] **Step 3: 修改 `core/readers/aria_reader.py`**

1. 收集 `role in ('img', 'image')` 或 `tag == 'img'` 的 `img_refs` 列表；
2. 若该 `img` 具有父级 `link`，记录映射关系；
3. 如果 `page` 拥有 `locator` 且 `callable(page.locator)`：
   并发（`asyncio.gather`）针对每个图片 Ref 执行获取 `src`：
   `await loc.evaluate('el => el.src || el.getAttribute("src") || ""')`；
4. 将获取到的 `src` 写入图片自身的 `ref_map[ref]["src"]` 与 `["url"]`；
5. 若该图片有父级 `link`，同时同步给 `ref_map[parent_link_ref]["src"]`。

- [ ] **Step 4: 运行测试验证通过**

运行: `python -m unittest tests.test_readers.TestAriaSnapshotReader`
预期结果: 全部 PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/aria_reader.py tests/test_readers.py
git commit -m "feat(aria_reader): extract image src and correlate nested links"
```

---

### Task 3: 端到端集成验证与测试对齐 (`PageHandler.read_page`)

**Files:**
- Modify: `tests/test_page_handler.py`

**Interfaces:**
- Consumes: `AriaSnapshotReader`
- Produces: 验证 `PageHandler.read_page(ref=...)` 在使用 `AriaSnapshotReader` 时产出与 Markdown 模式完全一致的高质量结构化响应。

- [ ] **Step 1: 编写测试用例**

在 `tests/test_page_handler.py` 中增加使用 `AriaSnapshotReader` 快照时查询 `ref` 的集成单测：
```python
def test_read_page_aria_mode_query_ref(self):
    self.fake_snapshot.ref_map = {
        "e1": {"ref": "e1", "tag": "a", "role": "link", "text": "登录入口", "href": "https://example.com/login", "src": ""},
        "e2": {"ref": "e2", "tag": "img", "role": "img", "text": "Logo", "alt": "Logo", "href": "", "src": "https://example.com/logo.png"},
        "e3": {"ref": "e3", "tag": "a", "role": "link", "text": "详情原图", "href": "https://example.com/detail", "src": "https://example.com/preview.png"},
    }
    self.mock_context.ref_map = self.fake_snapshot.ref_map

    res_link = run_coro(self.handler.read_page("s1", "u1", ref="e1"))
    self.assertIn("=== Ref 元素详情查询: [e1] ===", res_link)
    self.assertIn("元素类型: 超链接", res_link)
    self.assertIn("https://example.com/login", res_link)

    res_img = run_coro(self.handler.read_page("s1", "u1", ref="e2"))
    self.assertIn("=== Ref 元素详情查询: [e2] ===", res_img)
    self.assertIn("元素类型: 图片", res_img)
    self.assertIn("https://example.com/logo.png", res_img)

    res_both = run_coro(self.handler.read_page("s1", "u1", ref="e3"))
    self.assertIn("元素类型: 超链接 (含图片)", res_both)
    self.assertIn("https://example.com/detail", res_both)
    self.assertIn("https://example.com/preview.png", res_both)
```

- [ ] **Step 2: 运行测试验证通过**

运行: `python -m unittest tests.test_page_handler.TestPageHandler.test_read_page_aria_mode_query_ref`
预期结果: PASS。

- [ ] **Step 3: 提交更改**

```bash
git add tests/test_page_handler.py
git commit -m "test(page_handler): verify ref query in aria mode"
```

---

### Task 4: 文档同步与全量回归测试

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: 全功能与全接口定义
- Produces: 架构文档与变更日志同步记录 ARIA 语义树 URL 剥离与 Ref 元数据对齐；全量基础单测 100% 运行通过。

- [ ] **Step 1: 更新 `docs/ARCHITECTURE.md` 与 `CHANGELOG.md`**

1. `docs/ARCHITECTURE.md`：在 `AriaSnapshotReader` 章节更新说明，增加从原生 YAML 剥离 `- /url:`、化简长 URL 链接及通过 Ref 映射提取绝对跳转与图片地址的设计。
2. `CHANGELOG.md`：在 `[v1.3.0]` 中追加记录 ARIA 语义树脱敏与两款 Reader 的 `ref_map` 契约对齐。

- [ ] **Step 2: 运行全量基础单元测试验证**

运行: `python -m unittest discover tests`
预期结果: 225+ 单测全部 100% 通过。

- [ ] **Step 3: 提交文档与最终验证**

```bash
git add docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: document aria reader url hiding and ref alignment"
```
