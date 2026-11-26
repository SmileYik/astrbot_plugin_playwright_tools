# ARIA 阅读器语义树 URL 隐藏与 Ref 元数据契约对齐设计方案

## 1. 背景与意图 (Intent & Why)

在当前的 ARIA 阅读器（`AriaSnapshotReader`）中，Playwright 官方原生的 `aria_snapshot(mode='ai')` 会在无障碍树中为所有超链接输出 `- /url: <url>` 子节点行，且部分没有文本的超链接直接以完整的 URL 作为可访问性名称（例如 `- link "https://..."`）。这导致 ARIA 语义树正文中暴露出大量原始长 URL，严重消耗大模型的上下文 Token。

同时，`AriaSnapshotReader` 目前构建的 `ref_map` 仅保存了 `role`、`tag`、`name`、`text`，完全缺失了 `href`、`src` 与 `url` 字段。这使得大模型在使用 ARIA 模式时，调用 `pw_read(ref='eX')` 无法查询到目标超链接或图片地址，与刚刚完成的 `InlineMarkdownReader` 产生了数据契约与行为上的不一致。

此外，为了避免工具层（`PageHandler`）与具体 Reader 之间产生特判与私有逻辑耦合，需要建立两个 Reader 统一的 `ref_map` 数据契约，并将 Ref 详情查询逻辑沉淀到基类 `BasePageReader` 中。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals & Anti-Goals)

### 2.1 目标 (Goals)
1. **ARIA 语义树 URL 彻底隐藏与精简**：
   - 过滤删除 ARIA 快照 YAML 中所有的 `- /url: <url>` 子节点行。
   - 若父行（如 `- link "..." [ref=eX]:`）因包含子节点而以冒号结尾，在子节点移除后剥离末尾冒号，还原为纯净的 `- link "..." [ref=eX]`。
   - 若超链接的无障碍名称本身直接为 URL（如 `link "https://example.com/..." [ref=eX]`），直接移除该引号中的 URL 字符串，化简为 `- link [ref=eX]`（`link` 本身已代表链接语义，无需冗余追加 `"[链接]"`），并将原 URL 完整保存在 `ref_map['eX']['href']` 中。
2. **ARIA 快照元数据完整提取**：
   - 从扫描到的 `- /url: <url>` 或链接名称中提取真实绝对跳转地址，赋值给对应 Ref ID 的 `href` 与 `url`。
   - 在提炼快照时，为页面中包含 `img` / `image` 角色或标签的元素并发预取 `src`，赋值给对应 Ref ID 的 `src` 与 `url`。
   - 若链接包含子图片，将子图片 `src` 关联至父级链接，标明为“超链接 (含图片)”。
3. **`ref_map` 标准数据契约对齐**：
   - 统一 `InlineMarkdownReader` 与 `AriaSnapshotReader` 导出的 `ref_map` 元素结构，统一具备 `ref`, `tag`, `role`, `type`, `text`, `alt`, `href`, `src`, `url`。
4. **保持单点查询分发架构**：
   - 因为 `ref_map` 格式已被彻底规范化，`PageHandler.read_page` 现有的 Ref 查询与格式化逻辑直接对所有符合规范的 `ref_map` 原生通用。
   - 两个 Reader 均无需额外分散实现 `query_ref`，Reader 专注于正文提炼与快照生成，工具层（`PageHandler`）专注于结果交付与格式化，职责分明。
5. **单元测试与文档同步**：
   - 新增 ARIA URL 隐藏与 Ref 查询单测，全量基础单测保持 100% 通过；更新架构与变更日志。

### 2.2 非目标 (Non-Goals)
- 不改变大模型面向 `pw_read` 工具的调用参数签名（保持 `page`, `keyword`, `ref`, `refresh`）。
- 不破坏 Markdown 阅读器已实现的所有功能与测试用例。

### 2.3 反目标 (Anti-Goals)
- 严禁在 `PageHandler` 或 `PwReadTool` 中编写任何诸如 `if isinstance(reader, AriaSnapshotReader)` 或 `if ref.startswith('e')` 的穿透与特判逻辑。
- 严禁破坏原有 ARIA 语义树的缩进层级、节点依赖关系及其他非 URL 元素属性。

---

## 3. 约束 (Constraints)

1. **执行效率**：YAML 过滤与链接 URL 提取在内存中单遍完成（耗时 < 1ms）；图片 `src` 预取采用 `asyncio.gather` 并发完成。
2. **测试质量**：必须严格遵循 TDD 规范，单元测试 100% 绿灯。
3. **代码与文档规范**：遵循 `AGENT.md` 要求，凝练简洁，杜绝绝对化词汇，统一使用官方 `logger`。

---

## 4. 方案选型 (Approaches Considered)

- **方案一（已采纳）：AriaSnapshotReader 数据规范化自闭环，复用统一查询分发**
  - **机制**：
    - `AriaSnapshotReader` 内部在扫描 YAML 时解析 `- /url:` 行并将其从正文中彻底剥离；针对图片元素内部并发补全 `src`。
    - 将 `AriaSnapshotReader` 的 `ref_map` 字段对齐至标准契约（`tag`, `role`, `text`, `alt`, `href`, `src`, `url`）。
    - 工具层 `PageHandler.read_page` 的现有结构化查询逻辑直接基于该标准契约通用生效，两个 Reader 均无需各自编写或侵入查询方法。
  - **优势**：
    - 职责分明：Reader 专注于快照提炼与 URL 剥离，工具层专注于结果查询展示；
    - `PageSnapshot` 纯数据自闭环，离线单测无需依赖真实浏览器环境。
- **方案二（未采纳）：工具层动态探测与异步穿透**
  - **缺点**：工具层和具体 Reader 严重耦合，且查询依赖页面存活状态。

---

## 5. 详细实现设计 (Detailed Implementation)

### 5.1 标准 `ref_map` 契约定义

两款阅读器产出的 `PageSnapshot.ref_map[ref_id]` 字典必须包含以下标准键值：
- `ref`: `str`（如 `"1"` 或 `"e123"`）
- `tag`: `str`（统一映射为 HTML 标签名：`"a"`, `"img"`, `"button"`, `"input"` 等）
- `role`: `str`（ARIA 语义角色：`"link"`, `"img"`, `"button"`, `"textbox"` 等）
- `type`: `str`（如 `"password"`, `"checkbox"`, `""`）
- `text`: `str`（主要文本/名称）
- `alt`: `str`（图片描述）
- `href`: `str`（超链接绝对 URL，无则为 `""`）
- `src`: `str`（图片绝对 URL，无则为 `""`）
- `url`: `str`（统一目标 URL：`href` 或 `src` 或 `""`）

### 5.2 ARIA 树解析与 URL 过滤状态机 (`aria_reader.py`)

在 `AriaSnapshotReader.extract_snapshot` 中，对 `raw_yaml` 进行单遍扫描与清洗：
1. **状态跟踪**：维护栈或 `parent_ref_stack` 记录当前缩进层级与父级 Ref ID。
2. **识别 `- /url: <url>`**：
   - 提取 `<url>`；
   - 赋值给直接父节点的 `href` 与 `url`：`ref_map[parent_ref]["href"] = url`，`ref_map[parent_ref]["url"] = url`；
   - **该行彻底删除，不输出至清洗后的 YAML**。
3. **剥离父行冗余冒号**：
   - 父行如以 `:` 结尾，在确认其子行被移除后，剥离末尾冒号。
4. **链接名称 URL 精简**：
   - 若 `role == 'link'` 且名称为 URL（匹配 `^https?://`），直接在正文中去除该带引号的 URL 名称，精简为 `- link [ref=...]`（`link` 已自明角色，不附加多余文字），完整 URL 存入 `ref_map[ref]["href"]`。
5. **图片 `src` 并发拉取**：
   - 收集所有待补全 `src` 的图片 Ref ID；
   - 若 `page` 拥有 `locator`，执行 `asyncio.gather` 并发读取 `src` 写入对应 `ref_map` 项。

### 5.3 统一复用 `PageHandler` 查询分发

由于两款 Reader 输出的 `PageSnapshot.ref_map` 字段完全规范统一（均包含 `tag`, `role`, `text`, `alt`, `href`, `src`），`PageHandler.read_page` 现有的结构化 Ref 查询逻辑对两款 Reader 原生完全适用，无需在 Reader 中重复或分散实现任何单独查询逻辑，架构保持最简。

---

## 6. 验证计划 (Verification Plan)

1. **`test_aria_reader_url_filtering_and_href_extraction`**：
   - 验证 ARIA 快照中的 `- /url: ...` 被完全剥离，末尾冒号被清理，正文中无明文 URL。
   - 验证 `ref_map` 中成功解析并包含 `href` 与 `url`。
2. **`test_aria_reader_image_src_extraction`**：
   - 验证 ARIA 快照中的图片元素成功解析 `src` 并存入 `ref_map`。
3. **`test_base_page_reader_query_ref_polymorphism`**：
   - 验证无论由 Markdown 还是 ARIA 阅读器生成的快照，调用 `reader.query_ref(snapshot, ref)` 均能产生一致的结构化输出。
4. **全量回归验证**：
   - 运行全部 223+ 单元测试，确保 100% 通过。
