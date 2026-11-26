# Markdown 阅读器 Ref ID 统一图片与链接 URL 查询设计方案

## 1. 背景与意图 (Intent & Why)

当前 `InlineMarkdownReader`（Markdown 阅读器）在提炼网页正文时，为了精简 Token 消耗并保持排版紧凑，将页面上的超链接元素收敛为 `[Ref: ID] [链接: 文本]` 形式，隐藏了原始目标 URL。但在许多自动化阅读与检索场景中，大模型在阅读正文后需要获知具体元素的真实超链接 URL，或提取正文内插图的图片 URL 以便下载、分析或呈现给用户。

同时，当前实现中普通图片（`<img>`）依然直接输出为 `![alt](src)` 明文，长 URL 容易导致切片膨胀与 Token 浪费，且图片缺少独立的 Ref 编号，无法被工具精确定位与引用。

因此，本项目需要：
1. 统一普通图片 `<img>` 的输出规范，隐藏原始图片 URL 并分配独立的 Ref ID（如 `[Ref: ID] [图片: 描述]`）。
2. 在 DOM 提炼阶段为包含链接与图片的元素解析并记录绝对路径（`href` 与 `src`），持久化至快照映射字典（`ref_map`）。
3. 为 `pw_read` 工具新增 `ref` 参数，支持通过 Ref ID 查询对应元素的类型、标题/描述及完整目标 URL。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals & Anti-Goals)

### 2.1 目标 (Goals)
1. **图片统一收敛与 Ref 编号**：
   - 页面内的独立 `<img>` 标签不再暴露明文 URL，统一分配 Ref ID 并格式化为 `[Ref: X] [图片: alt]`（若无 alt 则为 `[Ref: X] [图片]`）。
   - 若 `<a>` 标签包裹 `<img>`，提炼为组合语义控件（如 `[Ref: X] [链接: alt/text]`），并在元数据中同时记录 `href` 与 `src`。
2. **快照元数据补齐**：
   - JavaScript 提取脚本在 `formatInteractive` 及图片提炼时，解析并存储绝对超链接 `href` 和图片地址 `src`。
   - `PageSnapshot.ref_map` 中存储包含 `href`、`src`、`url`、`tag`、`text` 的完整元素对象。
3. **工具参数扩展与结构化查询**：
   - `PW_READ_SCHEMA` 新增可选参数 `ref`（字符串类型）。
   - `PwReadTool` 与 `PageHandler.read_page` 支持传入 `ref`。
   - 当传入 `ref` 时，直接从当前快照缓存的 `ref_map` 中检索，并返回格式化的高可读性结构化信息。
   - 具备完备的边界防护：Ref 不存在时返回友好指引；Ref 存在但非链接/图片时（如纯文本框或普通按钮），明确说明类型并提示无可用 URL。
4. **文档与测试对齐**：
   - 更新 `skills/playwright-tool/SKILL.md`、`README.md`、`docs/ARCHITECTURE.md` 等相关文档。
   - 补充 `tests/test_readers.py`、`tests/test_page_handler.py`、`tests/test_tools.py` 单元测试，保证所有基础单测 100% 通过。

### 2.2 非目标 (Non-Goals)
- 不改变 ARIA 快照阅读器（`AriaSnapshotReader`）的原生无障碍树生成方式（仅保证在 ARIA 模式下对 `ref_map` 中已存元素的查询兼容）。
- 不调整 `pw_interact`、`pw_page`、`pw_media` 等其他工具的入参规范。

### 2.3 反目标 (Anti-Goals)
- 严禁在查询 Ref 时触发额外的浏览器网络往返或全局 DOM 重绘。
- 严禁破坏现有 `pw_read(page=...)`、`pw_read(keyword=...)` 和 `pw_read(refresh=...)` 的已有行为与向后兼容性。

---

## 3. 约束 (Constraints)

1. **执行性能**：Ref 查询必须基于快照缓存秒级响应（内存字典寻址，耗时 < 1ms）。
2. **文档风格**：严格遵守 `AGENT.md` 规范，语言凝练简洁，不出现绝对化词汇（如“彻底”、“完美”等）。
3. **日志规范**：仅允许使用 `from astrbot.api import logger`，严禁 `import logging`。
4. **单测要求**：遵循测试规范，保证单元测试全部通过。

---

## 4. 方案选型 (Approaches Considered)

- **方案一（已采纳）：快照缓存原地检索**
  - **机制**：DOM 提炼单遍遍历阶段即把 `<a>` 和 `<img>` 的绝对地址写入快照 `ref_map`。调用 `pw_read(ref='...')` 时直接在 Python 层检索当前快照的 `ref_map`。
  - **优势**：接近零延迟，快照与正文强一致，无外部环境变化导致的元素失效风险。
  - **决策**：经与需求方确认，采用此方案。

- **方案二（未采纳）：实时 DOM 动态探测**
  - **机制**：快照仅记录 Ref ID，查询时调用 Playwright locator 定位 DOM 元素获取属性。
  - **缺点**：增加浏览器进程通信开销（50-200ms），易受页面异步变动或元素离开视口影响。

---

## 5. 详细实现设计 (Detailed Implementation)

### 5.1 JavaScript 提炼脚本改造 (`markdown_reader.py`)
1. **元素分类与 Ref 分配**：
   - `isInteractive` 保持交互判定，新增针对 `img` 标签的检测逻辑：所有有效可见的 `<img>` 元素均参与 `data-astr-ref` 分配并录入 `rawElements`。
   - 提取属性时，通过 `node.href || (node.getAttribute && node.getAttribute('href')) || ''` 获取绝对超链接；通过 `node.src || (node.getAttribute && node.getAttribute('src')) || ''` 获取绝对图片地址。
2. **内联渲染输出**：
   - 普通 `img` 渲染由原先的 `![alt](src)` 调整为：`[Ref: ${ref}] [图片: ${alt}]`（若无 alt 则为 `[Ref: ${ref}] [图片]`）。
   - `a` 标签若包含子图片元素，在 `formatInteractive` 中探测子 `img` 的 `src` 与 `alt`，将 `src` 绑定至该链接元素的元数据中，正文呈现为 `[Ref: ${ref}] [链接: ${text}]`。

### 5.2 工具 Schema 与分发适配
1. **`PW_READ_SCHEMA` (`tools/schemas.py`)**：
   ```python
   PW_READ_SCHEMA = {
       "type": "object",
       "properties": {
           "page": {
               "type": "integer",
               "description": "分页查看时的页码编号，从1开始 (默认为 1)",
           },
           "keyword": {
               "type": "string",
               "description": "页面内容关键词定位检索，若提供则返回包含关键词的上下文片段与元素 (可选)",
           },
           "ref": {
               "type": "string",
               "description": "要查询详细信息或目标 URL 的元素 Ref 编号（如 '1', '2'）。传入时将直接返回该 Ref 对应的类型、标题及完整链接/图片地址 (可选)",
           },
           "refresh": {
               "type": "boolean",
               "description": "是否强制重新获取当前网页快照 (默认为 False)",
           },
       },
   }
   ```
2. **`PwReadTool` (`tools/tools.py`)**：
   - 提取 `ref = str(kwargs.get("ref") or "").strip()`，并透传给 `page_handler.read_page`。
3. **`PageHandler.read_page` (`tools/handlers/page_handler.py`)**：
   - 优先级判定：若 `ref` 存在且非空，走 Ref 详情查询分支；否则走原有的 `keyword` 检索或 `page` 翻页分支。
   - 查询格式化逻辑：
     ```python
     if ref:
         el = ctx.ref_map.get(str(ref))
         if not el:
             return f"未在当前快照中找到 Ref ID 为 '{ref}' 的元素。请确认编号是否正确，或调用 pw_read(refresh=True) 刷新快照。"
         # 格式化输出元素类型、标题/文本、目标地址与图片地址
     ```

### 5.3 查询输出规范
成功查询到超链接时返回示例：
```markdown
=== Ref 元素详情查询: [1] ===
- 元素类型: 超链接
- 链接文本: 官方技术文档
- 目标地址: https://example.com/docs
```
成功查询到图片时返回示例：
```markdown
=== Ref 元素详情查询: [2] ===
- 元素类型: 图片
- 图片描述: 产品架构拓扑图
- 图片地址: https://example.com/images/arch.png
```
当元素为链接内嵌图片时：
```markdown
=== Ref 元素详情查询: [3] ===
- 元素类型: 超链接 (含图片)
- 链接文本: 查看原图
- 目标地址: https://example.com/gallery/1
- 图片地址: https://example.com/preview.png
```
当元素为普通输入控件（如输入框、按钮）：
```markdown
=== Ref 元素详情查询: [4] ===
- 元素类型: 按钮
- 元素描述: 提交订单
- 提示: 该元素不包含可跳转的超链接或图片 URL。如需操作请调用 pw_interact(action='click', ref='4')。
```

---

## 6. 验证计划 (Verification Plan)

1. **单元测试覆盖**：
   - `test_inline_markdown_reader_extracts_img_ref_and_urls`：验证 `InlineMarkdownReader` 生成正文时普通图片转为 `[Ref: X] [图片: alt]`，且 `ref_map` 中包含完整的 `src` 与 `href`。
   - `test_read_page_query_ref_link_and_img`：验证 `page_handler.read_page(ref='...')` 正确格式化返回链接与图片详情。
   - `test_read_page_query_ref_non_url_element`：验证普通按钮/输入框的防呆提示。
   - `test_read_page_query_ref_not_found`：验证不存在的 Ref 返回指引提示。
   - `test_pw_read_tool_schema_and_call_with_ref`：验证 `PwReadTool` 接受 `ref` 参数并正确调度。
2. **完整单测运行**：
   - 运行基础单测验证套件，保证所有用例 100% 通过。
