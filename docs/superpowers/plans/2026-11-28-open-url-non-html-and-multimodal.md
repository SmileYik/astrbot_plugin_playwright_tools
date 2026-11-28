# `open_url` 非 HTML 响应分流与统一多模态返回 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `open_url` 打开图片等非 HTML 直链资源时等待 `domcontentloaded` 导致的 30 秒超时问题，实现基于 `wait_until="commit"` 与 `Content-Type` 的响应分流（HTML / 图片 / 分页纯文本 / 二进制），并统一图片发往多模态 AI 的 `CallToolResult` 返回链路与单开关配置。

**Architecture:** 在 `PageHandler.open_url` 中改用 `wait_until="commit"` 获取响应头后按 MIME 类型分流；新增 `PlainTextReader(BasePageReader)` 遵循 `page_chunk_char_limit` 对纯文本响应分页并接入 `page_state.current_snapshot`；在 `BaseActionHandler` 与 `tools.py` 中统一 `CallToolResult(TextContent + ImageContent)` 的构造、审计摘要提取与透传，并让 `MediaHandler` 的 `target='ai'` 截图复用同一机制。

**Tech Stack:** Python 3.12, Playwright / Camoufox async API, `mcp.types` (`CallToolResult`, `TextContent`, `ImageContent`, 带本地单测轻量 fallback), `unittest`

**Spec:** [2026-11-28-open-url-non-html-and-multimodal-design.md](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-28-open-url-non-html-and-multimodal-design.md)

## Global Constraints

- 日志仅允许使用 `from astrbot.api import logger`，严禁 `import logging`；异常分支需记录完整 traceback。
- 每次修改 `tools/`、`core/`、`adapts/` 后必须运行 `.venv/bin/python -m unittest discover tests` 确保基础单测通过。
- 文档、注释与提示文本需简洁实事求是，不使用“彻底/完全/杜绝”等绝对化措辞，并同步更新 `skills/playwright-tool/`、`docs/ARCHITECTURE.md`、`CHANGELOG.md`。
- 不需要兼容旧的 `"data:image/...;base64,..."` 字符串返回格式或旧测试代码。

## Review Focus

1. **大体积单行纯文本（如压缩后的 minified JSON）**：`PlainTextReader` 遇到单行超过 `page_chunk_char_limit` 时不能死循环或超限，必须按字符预算安全切分。
2. **非 UTF-8 编码文本响应（如 GBK/GB18030 或无 charset 头）**：解码需优先读取响应头 `charset`，依次回退 `utf-8` 与 `gb18030`（`errors="replace"`），不能抛 `UnicodeDecodeError`。
3. **触发直接下载的 URL（`Content-Disposition: attachment`）**：`page.goto` 抛出 `"Download is starting"` 时需捕获并返回下载引导，而不是当作未预期异常崩溃。
4. **`CallToolResult` 经过 `BaseActionHandler.execute_action` 切面**：`execute_action` 不得对 `CallToolResult` 调用 `str(res)` 破坏 `ImageContent`，同时必须提取 `TextContent` 文本写入审计日志并追加 `hint` / `tab_notice`。
5. **`PwMediaTool.call` 透传 `CallToolResult`**：当 `target='ai'` 返回 `CallToolResult` 时不得误触发 `res.startswith("[IMAGE_PATH:")` 报错。

---

### Task 1: 统一多模态配置与 `CallToolResult` 基础链路

**Files:**
- Modify: `_conf_schema.json:388-393`
- Modify: `tools/handlers/base_handler.py`
- Modify: `tools/tools.py`
- Test: `tests/test_base_handler.py`
- Test: `tests/test_conf_schema.py`

**Interfaces:**
- Produces:
  - `build_image_tool_result(text: str, image_bytes: bytes, mime_type: str) -> CallToolResult` in `tools/handlers/base_handler.py`
  - `extract_tool_result_text(result: str | CallToolResult) -> str` in `tools/handlers/base_handler.py`
  - `append_tool_result_text(result: str | CallToolResult, prefix: str = "", suffix: str = "") -> str | CallToolResult` in `tools/handlers/base_handler.py`
  - `ToolExecResult = str | CallToolResult` in `tools/tools.py`

- [ ] **Step 1: Write failing tests for `build_image_tool_result` and `BaseActionHandler.execute_action` with `CallToolResult`**

In `tests/test_base_handler.py`, add tests:
- `test_build_image_tool_result_contains_text_and_image`: calls `build_image_tool_result("ok", b"\x89PNG", "image/png")` and asserts `res.content[0].type == "text"`, `res.content[0].text == "ok"`, `res.content[1].type == "image"`, `res.content[1].mimeType == "image/png"`, and base64 decodes back to `b"\x89PNG"`.
- `test_execute_action_preserves_call_tool_result_and_logs_text`: `action_coro_fn` returns `(build_image_tool_result("loaded", b"img", "image/png"), {"screenshot_path": "a.png"})`; assert `execute_action` returns a `CallToolResult` whose `ImageContent` is intact, `TextContent` includes `"loaded"`, and `audit_logger.log_action` received `output_result="loaded"` and `screenshot_path="a.png"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests/test_base_handler.py -v`
Expected: FAIL (`ImportError` for `build_image_tool_result`)

- [ ] **Step 3: Update `_conf_schema.json` and implement multimodal helpers in `tools/handlers/base_handler.py` and `tools/tools.py`**

- In `_conf_schema.json` (`media.allow_screenshot_to_ai`), update `description` to `"允许 AI 直接查看图片"` and `hint` to `"开启后视为多模态 AI，访问图片链接或执行 target='ai' 截图时将直接把图片发送给 AI 进行视觉分析；关闭时仅返回文本描述或元信息"`.
- In `tools/handlers/base_handler.py`:
  - Import `CallToolResult, TextContent, ImageContent` from `mcp.types` with `@dataclass` fallback classes (`TextContent(type, text)`, `ImageContent(type, data, mimeType)`, `CallToolResult(content, isError=False)`) when `mcp` is absent in local test venv.
  - Implement `build_image_tool_result(text: str, image_bytes: bytes, mime_type: str) -> CallToolResult`, `extract_tool_result_text(result: Any) -> str`, and `append_tool_result_text(result: Any, prefix: str = "", suffix: str = "") -> Any`.
  - Update `BaseActionHandler.execute_action` so when `res` is a `CallToolResult`, it appends `hint`/`tab_notice` and applies password masking to `TextContent` items, logs `extract_tool_result_text(res)` to `audit_logger`, and returns the `CallToolResult` intact.
- In `tools/tools.py`:
  - Update `_execute_with_timeout`, `_invoke_handler`, `PwPageTool.call`, `PwMediaTool.call` to support `str | CallToolResult` (`ToolExecResult`).
  - In `PwMediaTool.call`, guard `res.startswith("[IMAGE_PATH:")` with `isinstance(res, str)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests/test_base_handler.py tests/test_conf_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json tools/handlers/base_handler.py tools/tools.py tests/test_base_handler.py
git commit -m "feat(tools): unify multimodal CallToolResult support and config description"
```

---

### Task 2: 统一 `MediaHandler` 截图发往 AI 链路

**Files:**
- Modify: `tools/handlers/media_handler.py`
- Test: `tests/test_media_handler.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `build_image_tool_result(text: str, image_bytes: bytes, mime_type: str) -> CallToolResult` from `tools/handlers/base_handler.py`

- [ ] **Step 1: Write failing tests in `tests/test_media_handler.py` and `tests/test_tools.py`**

- Update/add test in `tests/test_media_handler.py`: when `allow_screenshot_to_ai=True` and `target="ai"`, `screenshot_viewport` and `screenshot_full` return a `CallToolResult` containing `TextContent` and `ImageContent` (with `mimeType` `"image/png"` or `"image/jpeg"` and valid base64 `data`), instead of a `"data:image/..."` string.
- Add test in `tests/test_tools.py`: `PwMediaTool.call` with `action="screenshot_viewport"`, `target="ai"` returns `CallToolResult` directly without calling `event.send` or raising `AttributeError` on `.startswith`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests/test_media_handler.py tests/test_tools.py -v`
Expected: FAIL (returns string `"data:image/..."` instead of `CallToolResult`)

- [ ] **Step 3: Update `MediaHandler._save_or_encode` in `tools/handlers/media_handler.py`**

- When `target.lower() == "ai"`, call `build_image_tool_result(text=note or "已截取当前页面图像，请直接分析。", image_bytes=image_bytes, mime_type=mime)` and return the `CallToolResult`.
- Update `screenshot_viewport` / `screenshot_full` return type hints (`str | CallToolResult`) and pass descriptive `note` (e.g. URL / viewport or full-page note).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests/test_media_handler.py tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/media_handler.py tests/test_media_handler.py tests/test_tools.py
git commit -m "feat(media): return CallToolResult ImageContent when target=ai"
```

---

### Task 3: 实现纯文本分页阅读器 `PlainTextReader`

**Files:**
- Create: `core/readers/plain_text_reader.py`
- Modify: `core/readers/__init__.py` (if present, export `PlainTextReader`)
- Test: `tests/test_readers.py`

**Interfaces:**
- Produces:
  - `PlainTextReader(BasePageReader)`:
    - `__init__(self, chunk_char_limit: int = 4000, mask_passwords: bool = True)`
    - `build_snapshot(self, text: str, url: str = "", title: str = "", mime_type: str = "text/plain") -> PageSnapshot`
    - `async extract_snapshot(self, page: Any, url: str = "", start_ref: int = 1) -> PageSnapshot`
    - `format_chunk(self, snapshot: PageSnapshot, page_index: int) -> str`
    - `search(self, snapshot: PageSnapshot, keyword: str) -> str`
    - `get_tool_metadata(self) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests in `tests/test_readers.py`**

Add tests for `PlainTextReader`:
- `test_plain_text_reader_paginates_by_chunk_limit`: multi-line text exceeding `chunk_char_limit=100` splits into multiple chunks, each chunk includes header (`第 X/Y 页`) and `pw_read(page=...)` guidance, and `format_chunk(snapshot, 2)` returns page 2 (clamped within `1..total_pages`).
- `test_plain_text_reader_splits_long_single_line`: a single 500-char line (like minified JSON) with `chunk_char_limit=120` splits cleanly into multiple chunks without exceeding budget or infinite looping.
- `test_plain_text_reader_search_returns_matching_lines`: `search(snapshot, "target")` returns matching line numbers and context, and handles no-match gracefully.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests/test_readers.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named '...plain_text_reader'`)

- [ ] **Step 3: Implement `PlainTextReader` in `core/readers/plain_text_reader.py`**

Implement `PlainTextReader(BasePageReader)` with line-aware + long-line character-slice pagination obeying `self.chunk_char_limit`, `build_snapshot(text, url, title, mime_type)`, `extract_snapshot` (reading `page.inner_text("body")` or `page.content()` as fallback if called via `pw_read(refresh=True)`), `format_chunk`, `search`, and `get_tool_metadata`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests/test_readers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/readers/plain_text_reader.py core/readers/__init__.py tests/test_readers.py
git commit -m "feat(readers): add PlainTextReader for paginated non-html text responses"
```

---

### Task 4: `PageHandler.open_url` 非 HTML 响应分流与 `main.py` 接线

**Files:**
- Modify: `tools/handlers/page_handler.py`
- Modify: `main.py`
- Test: `tests/test_page_handler.py`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes:
  - `build_image_tool_result` from `tools/handlers/base_handler.py`
  - `PlainTextReader` from `core/readers/plain_text_reader.py`
- Produces:
  - `PageHandler(..., allow_image_to_ai: bool = False, audit_save_screenshots: bool = True, audit_screenshots_dir: str = ..., commit_timeout_ms: int = 20000)`
  - `PageHandler.open_url(...) -> str | CallToolResult`

- [ ] **Step 1: Write failing tests in `tests/test_page_handler.py` and `tests/test_plugin_main.py`**

Add tests in `tests/test_page_handler.py`:
- `test_open_url_image_with_multimodal_enabled_returns_call_tool_result`: mock `page.goto` returning `response` with `headers={"content-type": "image/png"}` and `body()` returning PNG bytes; assert `page.goto` was called with `wait_until="commit"`, `wait_for_load_state("domcontentloaded")` was NOT called, and `open_url` returns `CallToolResult` with `ImageContent`.
- `test_open_url_image_with_multimodal_disabled_returns_metadata`: `allow_image_to_ai=False`; assert `open_url` returns string with MIME type, byte size, and guidance without `ImageContent`.
- `test_open_url_text_json_returns_paginated_content_and_caches_snapshot`: `headers={"content-type": "application/json; charset=utf-8"}` with multi-line JSON exceeding `chunk_char_limit`; assert `open_url` returns page 1 directly and `read_page(page=2)` returns page 2 from cached `PageSnapshot`.
- `test_open_url_gbk_text_decodes_without_error`: `headers={"content-type": "text/plain; charset=gbk"}` with GBK bytes; assert decoded Chinese text appears in result.
- `test_open_url_binary_pdf_returns_metadata_without_domcontentloaded`: `headers={"content-type": "application/pdf", "content-length": "10240"}`; assert returns metadata and non-HTML guidance without calling `domcontentloaded`.
- `test_open_url_download_starting_returns_guidance`: `page.goto` raises `Exception("Page.goto: Download is starting")`; assert returns friendly download guidance string instead of unhandled error.
- `test_open_url_html_waits_domcontentloaded_gracefully`: `headers={"content-type": "text/html; charset=utf-8"}`; assert calls `wait_for_load_state("domcontentloaded", timeout=10000)` and returns standard HTML open message with `pw_read()` recommendation.

Add test in `tests/test_plugin_main.py` verifying `allow_screenshot_to_ai` is passed to `PageHandler` as `allow_image_to_ai` and `commit_timeout_ms` is bounded below `tool_execution_timeout_seconds`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests/test_page_handler.py tests/test_plugin_main.py -v`
Expected: FAIL (`open_url` still calls `wait_until="domcontentloaded"` and returns HTML string)

- [ ] **Step 3: Implement `open_url` routing in `tools/handlers/page_handler.py` and wire in `main.py`**

- In `PageHandler.__init__`: accept `allow_image_to_ai: bool = False`, `audit_save_screenshots: bool = True`, `audit_screenshots_dir: str = "data/plugin_data/astrbot_plugin_playwright_tools/audit_screenshots"`, `commit_timeout_ms: int = 20000`, `plain_text_reader: PlainTextReader | None = None` (defaulting `chunk_char_limit` from `getattr(self.reader, "chunk_char_limit", 4000)`).
- Extract small cohesive helpers in `PageHandler`:
  - `_parse_content_type(headers: dict[str, str] | None) -> tuple[str, str]` (returns `(mime, charset)`).
  - `_decode_text_body(body: bytes, charset: str) -> str` (tries `charset`, `utf-8`, `gb18030` with `errors="replace"`).
  - `_is_text_mime(mime: str) -> bool` (handles `text/*` except `text/html`, plus `application/json`, `application/xml`, `application/javascript`, `application/ecmascript`, `application/x-yaml`, `application/yaml`, `image/svg+xml`, and `+json`/`+xml` suffixes).
- Update `open_url`:
  - `response = await page.goto(url, wait_until="commit", timeout=self.commit_timeout_ms)` (catching `"Download is starting"`).
  - Route by MIME: image (`image/*` except `image/svg+xml`) -> `response.body()` (fallback `page.screenshot()`), audit screenshot if enabled, `build_image_tool_result` if `allow_image_to_ai` else metadata text; text -> decode & `PlainTextReader.build_snapshot`, store in `page_state.current_snapshot` (`is_snapshot_dirty = False`), return page 1; HTML (`text/html`, `application/xhtml+xml`, or `response is None`) -> `wait_for_load_state("domcontentloaded", timeout=10000)` (catch timeout gracefully), extract title, clear state, return HTML message; other binary -> return resource metadata.
- Update `main.py` to pass `allow_image_to_ai=allow_screenshot_to_ai`, `audit_save_screenshots=audit_save_screenshots`, `commit_timeout_ms=max(5000, (tool_timeout - 5) * 1000)` to `PageHandler`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests/test_page_handler.py tests/test_plugin_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/page_handler.py main.py tests/test_page_handler.py tests/test_plugin_main.py
git commit -m "feat(page): route non-html responses in open_url with multimodal and text pagination"
```

---

### Task 5: 同步文档、SKILL 与全量测试验证

**Files:**
- Modify: `skills/playwright-tool/SKILL.md` (and any subfiles in `skills/playwright-tool/` if applicable)
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md` (if `allow_screenshot_to_ai` description is documented there)

- [ ] **Step 1: Update `skills/playwright-tool/`**

Describe concisely for the AI user: `pw_page(action='open')` handles image URLs (directly returning the image when multimodal viewing is enabled), plain-text/JSON URLs (returning paginated text that can be paged with `pw_read(page=...)`), and binary URLs without timing out; `pw_media(..., target='ai')` shares the unified multimodal image return. Avoid internal class/method names.

- [ ] **Step 2: Update `docs/ARCHITECTURE.md`, `CHANGELOG.md`, and `README.md`**

Document `PlainTextReader`, `open_url` `wait_until="commit"` response routing, unified `CallToolResult` multimodal pipeline, and record the change in `CHANGELOG.md`.

- [ ] **Step 3: Run full unit test suite**

Run: `.venv/bin/python -m unittest discover tests`
Expected: All tests pass (note: check if `test_release_script.py` had a pre-existing failure unrelated to our changes and verify all `test_base_handler`, `test_media_handler`, `test_page_handler`, `test_readers`, `test_tools`, `test_conf_schema`, `test_plugin_main` pass 100%).

- [ ] **Step 4: Commit documentation updates**

```bash
git add skills/ docs/ARCHITECTURE.md CHANGELOG.md README.md
git commit -m "docs: update skill, architecture, and changelog for non-html open_url and multimodal support"
```
