# `open_url` 非 HTML 资源分流与统一多模态图片返回设计

## 1. 背景与意图

在 `tools/handlers/page_handler.py` 的 `open_url` 中，当前固定调用 `page.goto(url, wait_until="domcontentloaded", timeout=30000)`，而外层 `PwPageTool` 的 `_execute_with_timeout` 默认也是 30 秒硬超时。当目标 URL 为图片等非 HTML 直链资源时，浏览器内核已渲染出内容但 `domcontentloaded` 仍可能长期挂起，最终被外层 30 秒超时强杀，导致 Agent 反复重试。

此外，现有 `media_handler.py` 在 `target='ai'` 时仅返回 `"data:image/...;base64,..."` 纯文本，并未按 AstrBot `ToolExecResult` 规范返回 `mcp.types.CallToolResult`（`ImageContent`），导致多模态模型无法直接看到图片。

本次改造旨在：
1. 解决 `open_url` 打开图片、纯文本等非 HTML 资源时的超时卡死问题，按响应类型提供准确返回与引导。
2. 合并配置项为单一多模态开关，统一 `open_url` 打开图片与 `pw_media` 截图发给 AI 的 `CallToolResult` 返回链路。
3. 对非 HTML 文本资源直接返回正文，并遵循配置中的 `page_chunk_char_limit` 进行分页。

## 2. 目标、非目标与反目标

- **目标**：
  - `open_url` 使用 `wait_until="commit"` 获取响应头后按 `Content-Type` 分流处理 HTML、图片、文本及其他二进制资源。
  - 合并配置为单一多模态开关：开启时，打开图片 URL 与 `pw_media(..., target='ai')` 均通过 `CallToolResult(content=[TextContent(...), ImageContent(...)])` 发送图片给 AI。
  - 非 HTML 文本资源直接按 `page_chunk_char_limit` 分页返回第 1 页，并写入页面快照支持 `pw_read(page=N, keyword=...)` 翻页与检索。
- **非目标**：
  - 不实现 PDF/Office 文档内容解析；对非文本、非图片的二进制资源仅返回元信息与下载提示。
  - 不保留对旧 `data:image/...;base64,...` 字符串返回格式的兼容，也不保留旧测试的兼容包袱。
- **反目标**：
  - 避免为嗅探类型额外发起一次 HTTP `HEAD/GET` 请求（会破坏浏览器 Cookie/指纹一致性并增加双倍请求开销）。
  - 避免让 `page.goto` 内部超时等于或大于外层工具硬超时，导致无法捕获与降级。

## 3. 约束条件

- **AstrBot 工具协议**：`ToolExecResult = str | mcp.types.CallToolResult`。返回图片给大模型必须使用 `mcp.types.CallToolResult` 包含 `ImageContent(type="image", data=base64_str, mimeType=mime)` 与 `TextContent(type="text", text=...)`。
- **编码规范与测试**：遵循 `AGENT.md`，日志仅使用 `from astrbot.api import logger`，异常需记录 traceback；完成后须运行 `python -m unittest discover tests` 全部通过，并同步更新 `skills/playwright-tool/`、`docs/ARCHITECTURE.md`、`CHANGELOG.md` 等文档。

## 4. 方案对比与选型

1. **方案 A（已选定）：`wait_until="commit"` 响应头分流**
   - 先等待响应头抵达（`commit`），再依据 `response.headers["content-type"]` 决定后续等待与数据读取：HTML 继续等 `domcontentloaded`；图片与文本直接读取 `response.body()` / `response.text()`。
   - **优点**：单次请求复用浏览器会话与反爬上下文；图片拿到无黑边原图；避免非 HTML 资源等待 `domcontentloaded` 卡死。
   - **代价**：需处理触发浏览器直接下载（`Content-Disposition: attachment`）时 `page.goto` 抛错的分支。
2. **方案 B（未选）：先发独立 HTTP `HEAD/GET` 预检**
   - **放弃原因**：易被目标站拦截 `HEAD`、丢失浏览器 Cookie/指纹，且资源未进入当前标签页。
3. **方案 C（未选）：仅缩短 `domcontentloaded` 超时并降级**
   - **放弃原因**：每次访问图片仍需白等十余秒超时，响应慢且不可靠。

## 5. 核心设计

### 5.1 统一多模态配置项

- 在 `_conf_schema.json` 的 `media` 分组中，将原 `allow_screenshot_to_ai` 统一改造为单一开关（建议保留键名 `allow_screenshot_to_ai` 或统一命名为 `allow_image_to_ai`，由 builder 确定键名并同步 `main.py`、Web UI 如涉及、文档及测试）：
  - 描述：允许 AI 直接查看图片
  - 提示：开启后视为多模态 AI，访问图片链接或执行 `target='ai'` 截图时将直接把图片发送给 AI 进行视觉分析；关闭时仅返回文本描述或元信息。
- `main.py` 将该开关同时注入 `PageHandler` 与 `MediaHandler`；`PageHandler` 同时接收 `page_chunk_char_limit`（或直接从 `self.reader.chunk_char_limit` 获取）。

### 5.2 统一多模态工具返回链路

- 在 `tools/handlers/base_handler.py`（或公共辅助模块）提供统一构造方法，例如 `build_image_tool_result(text: str, image_bytes: bytes, mime_type: str) -> CallToolResult`：
  - 将 `image_bytes` 转为 base64，构造 `CallToolResult(content=[TextContent(type="text", text=text), ImageContent(type="image", data=b64, mimeType=mime_type)])`。
- 更新 `tools/tools.py`：
  - `_execute_with_timeout`、`_invoke_handler`、`PwPageTool.call`、`PwMediaTool.call` 返回类型标注更新为 `str | CallToolResult`（`ToolExecResult`）。
  - `PwMediaTool.call` 中仅当 `res` 为 `str` 且以 `"[IMAGE_PATH:"` 开头时执行自动发往聊天窗口的逻辑；若为 `CallToolResult` 则直接透传返回给 AstrBot。
- 更新 `tools/handlers/base_handler.py` 中的 `execute_action`：
  - 支持 `action_coro_fn` 返回 `CallToolResult` 或 `(CallToolResult, extra_audit)`。
  - 若返回结果为 `CallToolResult`，提取其中的 `TextContent` 文本拼接用于提示词追加（`hint`、`tab_notice`）与 `audit_logger.log_action(..., output_result=...)`，保留 `ImageContent` 不被 `str(res)` 破坏。
- 更新 `tools/handlers/media_handler.py`：
  - `screenshot_viewport` 与 `screenshot_full` 在 `target.lower() == "ai"` 且允许向 AI 发送图片时，统一调用上述辅助方法返回 `CallToolResult`（附带简要文本说明，不再返回裸 `data:image/...;base64,...` 字符串）。

### 5.3 `open_url` 响应分流逻辑（`tools/handlers/page_handler.py`）

1. **导航与超时控制**：
   - `page.goto(url, wait_until="commit", timeout=commit_timeout_ms)`，其中 `commit_timeout_ms` 需小于外层 `tool_execution_timeout_seconds`（例如默认 `20000`ms 或 `max(5000, (tool_timeout - 5) * 1000)`）。
   - 若因 `Content-Disposition: attachment` 等触发下载导致 `page.goto` 抛出 `"Download is starting"` 类异常，直接返回文件下载提示并引导使用 `pw_media(action='download')` 或浏览器下载，不视作未预期崩溃。
2. **提取响应类型**：
   - 从 `response.headers.get("content-type", "")` 解析主 MIME 类型（去掉 `; charset=...` 参数）。若 `response` 为空（如某些前端路由/about:blank），按 HTML 处理。
3. **按 MIME 分流**：
   - **图片类型（`mime.startswith("image/")`）**：
     - 通过 `await response.body()` 获取图片字节（失败或空字节时降级尝试 `page.screenshot()`）。
     - 若开启审计截图（`audit_save_screenshots`），可按需落盘审计图或记录元信息。
     - **多模态开关开启**：调用统一构造方法返回 `CallToolResult`，附带文本说明（URL、MIME、字节大小、标签页位置）及 `ImageContent`。
     - **多模态开关关闭**：返回文本结果，包含 URL、MIME、字节大小，并提示管理员未开启“允许 AI 直接查看图片”，若需发给用户可调用 `pw_media(action='screenshot_viewport', target='chat')`。
   - **纯文本类型（`mime.startswith("text/")` 且非 `text/html`，或 `application/json`、`application/xml`、`application/javascript`、`application/x-yaml` 等常见文本 MIME）**：
     - 读取文本内容（`await response.text()` 或 `response.body()` 解码，优先使用 header 中的 `charset`，回退 `utf-8` / `gb18030` replace）。
     - 通过新增的纯文本分页阅读器 `PlainTextReader`（继承 `BasePageReader`，位于 `core/readers/plain_text_reader.py`）按 `page_chunk_char_limit` 切分为分页片段，生成统一的页眉/页脚提示（总页数、当前页、`pw_read(page=...)` 翻页指引），并支持 `search()` 关键词检索。
     - 将生成的 `PageSnapshot`（`url=getattr(page, "url", url)`、`chunks=...`、`total_pages=...`）存入 `ctx.get_page_state(page).current_snapshot` 并置 `is_snapshot_dirty = False`，直接返回第 1 页内容。
   - **HTML 类型（`text/html`、`application/xhtml+xml` 或空响应）**：
     - 继续执行 `await page.wait_for_load_state("domcontentloaded", timeout=10000)`（若超时仅记录 debug/warning 并继续，避免整页阻塞）。
     - 提取 `title`、清空旧快照并按原格式返回成功提示与 `pw_read()` 引导。
   - **其他非文本二进制类型（如 `application/pdf`、`application/octet-stream`、`video/*`、`audio/*`）**：
     - 直接返回资源 URL、MIME 类型、`Content-Length`（若有）及标签页信息，提示该链接为非网页二进制资源，不建议调用 `pw_read()`。

## 6. 留给实现者决定的细节

- 配置键名是否沿用 `allow_screenshot_to_ai`（仅更新 schema 文案）或重命名为 `allow_image_to_ai`（同步全局替换）。
- 图片响应头中 `image/svg+xml` 的归类：可按文本或图片处理（若视作图片需注意多模态模型对 SVG 的支持度，通常 `image/svg+xml` 归为文本或按 PNG 截图转换更稳妥，交由实现者根据实际链路选择）。
