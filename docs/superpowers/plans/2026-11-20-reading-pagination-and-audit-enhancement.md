# 网页阅读排版、独立分页检索与审计系统增强实施计划 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底重构网页正文结构化排版与元素单行化提炼，实现 `target: all | text | elements` 独立分页与检索；精简 Playwright 异常并注入操作建议；全面升级审计系统以记录真实输出文本与截图，并修复 WebUI 审计分页与静态截图服务。

**Architecture:** 
- `PageExtractor` 保持纯无状态单例，以 Markdown 标题与段落层级提取正文，以可配 `element_multiline_separator` 规整元素换行，在 `ManagedContext` 中持久化快照并支持按 `all/text/elements` 独立分页与检索；
- `interact_handler` 等拦截 Playwright 底层调用栈并剥离 Call log，提炼简明阻碍原因并向大模型追加 `[推荐操作: ...]`；
- `tools.py` 调度层与 Handlers 统一上报真实 `output_result`，受 `audit_max_output_chars`（默认 0 不限）约束；`MediaHandler` 仅在显式截图时根据 `audit_save_screenshots`（默认 true）落盘至 `data/audit_screenshots/` 并存索引；
- `api/audit_api.py` 多层探测 `query/args/query_params` 修复 Web 端翻页，并挂载安全的静态截图拉取路由；前端重构构建至 `views/audit/`。

**Tech Stack:** Python 3.12, Playwright (`playwright.async_api`), SQLite3, React 18, TypeScript, Vite.

**Spec:** `docs/superpowers/specs/2026-11-20-reading-pagination-and-audit-enhancement-design.md`

## Global Constraints

- 运行环境为 Python 3.12，测试命令统一为 `.venv\Scripts\python -m unittest discover tests`。
- 严禁在交互操作中使用裸 JS `document.querySelector().click()`，100% 遵循 Playwright 原生 Locator 体系。
- 严禁向大模型工具返回暴露底层 Playwright `Call log:` 及重复重试日志。
- 严禁在 SQLite 中存储 Base64 截图图片，截图必须独立落盘至 `data/audit_screenshots/`。
- 允许自由调整数据契约与接口设计，无需兼容历史旧写法。

## Review Focus

1. **元素换行分隔符异常输入**：当 `element_multiline_separator` 为空串或特殊符号时，不能抛出异常且必须有效消除断行。
2. **长篇无标题正文页面提取**：面对缺失 `h1~h6` 的页面，提炼器仍能按段落层级完整输出 Markdown 正文，不丢失内容。
3. **`audit_max_output_chars = 0` 边界**：当配置为 0 时，确保输出文本 100% 全量保存，绝不被误截断。
4. **截图文件路由路径穿越防御**：当调用 `/audit/screenshot` 传入 `../../` 或绝对路径时，严格返回 403/400 阻断。
5. **Web API 参数容错**：当 `req` 为 None 或环境不支持代理时，`extract_query_param` 优雅回退到默认值，不引发 500。

---

### Task 1: 配置项定义与核心依赖注入

**Files:**
- Modify: `_conf_schema.json`
- Modify: `metadata.yaml`
- Modify: `main.py:35-115`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: AstrBot 插件配置读取机制
- Produces: `audit_max_output_chars: int = 0`, `audit_save_screenshots: bool = True`, `element_multiline_separator: str = " | "`

- [ ] **Step 1: Write the failing test**

在 `tests/test_plugin_main.py` 中添加测试用例，断言 `PlaywrightToolPlugin` 正确读取并挂载新配置：

```python
def test_plugin_config_initialization_with_new_audit_and_extractor_settings(self):
    cfg = {
        "audit_max_output_chars": 5000,
        "audit_save_screenshots": False,
        "element_multiline_separator": " / "
    }
    plugin = PlaywrightToolPlugin(self.mock_context, config=cfg)
    self.assertEqual(plugin.page_extractor.multiline_separator, " / ")
    self.assertEqual(plugin.audit_logger.max_output_chars, 5000)
    self.assertFalse(plugin.media_handler.audit_save_screenshots)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m unittest tests/test_plugin_main.py`
Expected: FAIL with `AttributeError` or missing attribute

- [ ] **Step 3: Implement config schema and initialization in `_conf_schema.json`, `metadata.yaml`, `main.py`**

- 在 `_conf_schema.json` 和 `metadata.yaml` 中新增 `audit_max_output_chars`, `audit_save_screenshots`, `element_multiline_separator` 的字段 schema 与默认值；
- 在 `main.py` 的 `__init__` 中提取并传给 `PageExtractor`, `AuditLogger`, `MediaHandler`。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m unittest tests/test_plugin_main.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json metadata.yaml main.py tests/test_plugin_main.py
git commit -m "feat(config): add audit_max_output_chars, audit_save_screenshots and element_multiline_separator"
```

---

### Task 2: 页面正文结构化提取、元素单行化清洗与方案 A 独立分页

**Files:**
- Modify: `core/page_extractor.py`
- Test: `tests/test_page_extractor.py`

**Interfaces:**
- Consumes: `multiline_separator: str = " | "`
- Produces:
  - `PageExtractor.extract_snapshot(page_title, url, raw_elements, markdown_text) -> tuple[dict[str, str], dict[int, dict]]`
  - `PageExtractor.format_page_chunk(snapshot_data, target="all", page_index=1) -> str`
  - `PageExtractor.search_snapshot(snapshot_data, keyword, target="all") -> str`

- [ ] **Step 1: Write the failing test**

在 `tests/test_page_extractor.py` 中编写针对 Markdown 正文排版、元素换行规整及三种 `target` 分页与检索的测试：

```python
def test_markdown_and_multiline_element_extraction(self):
    extractor = PageExtractor(max_page_char_length=300, multiline_separator=" | ")
    raw_elements = [
        {"tag": "button", "type": "button", "text": "搜索GTNH中文维基\nCtrl K", "ref": 1},
        {"tag": "a", "type": "", "text": "发电线路\n教程指南", "ref": 2}
    ]
    markdown_text = "# GTNH 维基\n\n这是关于蒸汽时代的指南介绍。\n\n## 锅炉\n高压锅炉效率更高。"
    snapshot, ref_map = extractor.extract_snapshot("GTNH", "https://gtnh.com", raw_elements, markdown_text)

    # 1. 验证元素换行被正确替换为 ' | '
    self.assertIn('[1] [按钮] "搜索GTNH中文维基 | Ctrl K"', snapshot["elements_text"])
    self.assertIn('[2] [链接] "发电线路 | 教程指南"', snapshot["elements_text"])

    # 2. 验证 target='text' 仅返回正文 Markdown，且页脚包含正确引导
    text_view = extractor.format_page_chunk(snapshot, target="text", page_index=1)
    self.assertIn("# GTNH 维基", text_view)
    self.assertNotIn("【可操作元素】", text_view)

    # 3. 验证 target='elements' 仅返回操作元素
    el_view = extractor.format_page_chunk(snapshot, target="elements", page_index=1)
    self.assertIn("【可操作元素】", el_view)
    self.assertNotIn("# GTNH 维基", el_view)

    # 4. 验证 target='text' 的目标域精准检索
    search_text = extractor.search_snapshot(snapshot, keyword="锅炉", target="text")
    self.assertIn("高压锅炉效率更高", search_text)
    self.assertNotIn("[按钮]", search_text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m unittest tests/test_page_extractor.py`
Expected: FAIL with `TypeError` or missing dict keys

- [ ] **Step 3: Implement structured extraction, element normalization, and target pagination in `core/page_extractor.py`**

- 更新 `get_js_extractor_script()`：遍历正文主容器输出 Markdown 标题与段落，剔除无意义的 `[文本]` 前缀；读取节点 innerText 并由 Python 端规整；
- 改造 `extract_snapshot()`：无状态返回包含 `title`, `url`, `markdown_text`, `elements_text`, `full_text` 的快照字典；
- 实现 `format_page_chunk()`：支持 `target='all' | 'text' | 'elements'`，根据各目标域长度独立切片，并在页脚生成智能后续操作提示；
- 实现 `search_snapshot()`：在指定目标域中按行检索并返回上下文。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m unittest tests/test_page_extractor.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/page_extractor.py tests/test_page_extractor.py
git commit -m "feat(extractor): implement markdown structure, multiline normalization and target pagination"
```

---

### Task 3: 异常堆栈精简清洗、操作建议追加与 Tool Schemas 升级

**Files:**
- Modify: `tools/schemas.py`
- Modify: `tools/handlers/interact_handler.py`
- Modify: `tools/handlers/page_handler.py`
- Modify: `tools/tools.py`
- Test: `tests/test_interact_handler.py`
- Test: `tests/test_page_handler.py`

**Interfaces:**
- Consumes: `PW_PAGE_SCHEMA`
- Produces:
  - `clean_playwright_error(e: Exception) -> str`
  - `PageHandler.read_page(session_id, sender_id, target="all", page=1) -> str`
  - `PageHandler.search_page(session_id, sender_id, keyword="", target="all") -> str`

- [ ] **Step 1: Write the failing test**

在 `tests/test_interact_handler.py` 和 `tests/test_page_handler.py` 中编写测试：

```python
def test_clean_playwright_error_strips_call_log(self):
    raw_error = Exception(
        "Locator.click: Timeout 10000ms exceeded.\n"
        "Call log:\n"
        "  - waiting for locator(\"[data-astr-ref=\\\"311\\\"]\")\n"
        "  - <dialog open=\"\" role=\"dialog\"> intercepts pointer events\n"
    )
    cleaned = clean_playwright_error(raw_error)
    self.assertNotIn("Call log:", cleaned)
    self.assertIn("页面弹层遮挡", cleaned)
    self.assertIn("[推荐操作:", cleaned)

def test_page_handler_read_with_target_param(self):
    res = run_coro(self.handler.read_page("s1", "u1", target="text", page=1))
    self.assertIn("[推荐操作:", res)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m unittest tests/test_interact_handler.py tests/test_page_handler.py`
Expected: FAIL

- [ ] **Step 3: Implement error cleaning, suggestions, and schema updates in `tools/`**

- 在 `tools/schemas.py` 的 `PW_PAGE_SCHEMA` 中，为 `read` 和 `search` 添加 `target`（枚举 `["all", "text", "elements"]`，默认 `"all"`）；
- 在 `tools/handlers/interact_handler.py` 中编写 `clean_playwright_error`，将拦截、超时、失联等错误精简为一句话并附带关闭遮挡或刷新的指引；
- 在 `page_handler.py` 中将 `ManagedContext` 维护的快照结构体适配至 `read_page` 与 `search_page`，并追加下一步操作提示；
- 在 `tools/tools.py` 的 `_action_read` 与 `_action_search` 中接收 `target` 并透传。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m unittest tests/test_interact_handler.py tests/test_page_handler.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/schemas.py tools/handlers/interact_handler.py tools/handlers/page_handler.py tools/tools.py tests/test_interact_handler.py tests/test_page_handler.py
git commit -m "feat(tools): sanitize playwright errors, inject next-action hints and support target in schema"
```

---

### Task 4: 审计系统真实输出记录、截图落盘与 Web API 分页修复

**Files:**
- Modify: `core/audit_logger.py`
- Modify: `tools/handlers/media_handler.py`
- Modify: `tools/tools.py`
- Modify: `api/audit_api.py`
- Test: `tests/test_audit_logger.py`
- Test: `tests/test_audit_api.py`

**Interfaces:**
- Consumes: `audit_max_output_chars: int`, `audit_save_screenshots: bool`
- Produces:
  - `extract_query_param(req: Any, key: str, default: Any = None) -> Any`
  - `GET /{plugin_name}/audit/screenshot`
  - 审计表中真实 `output_result` 与 `screenshot_path` 记录

- [ ] **Step 1: Write the failing test**

在 `tests/test_audit_logger.py` 与 `tests/test_audit_api.py` 中编写测试：

```python
def test_audit_records_real_output_and_truncates_when_limit_set(self):
    self.logger.max_output_chars = 20
    run_coro(self.logger.log_action(
        session_id="s1", context_key="c1", sender_id="u1",
        tool_name="pw_page:read", url="https://example.com",
        output_result="12345678901234567890EXTRA_TEXT"
    ))
    items, _ = run_coro(self.logger.query_logs(page=1, page_size=1))
    self.assertTrue(items[0]["output_result"].startswith("12345678901234567890"))
    self.assertIn("[审计日志已截断", items[0]["output_result"])

def test_extract_query_param_multi_source_support(self):
    # 测试兼容 DashboardRequest.args
    class FakeDashboardReq:
        def __init__(self):
            self.args = {"page": "3", "keyword": "wiki"}
    req = FakeDashboardReq()
    self.assertEqual(extract_query_param(req, "page", 1), 3)
    self.assertEqual(extract_query_param(req, "keyword", ""), "wiki")

def test_screenshot_route_blocks_directory_traversal(self):
    res = run_coro(self.api_handler.api_audit_screenshot(path="../../etc/passwd"))
    self.assertEqual(res["status_code"], 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m unittest tests/test_audit_logger.py tests/test_audit_api.py`
Expected: FAIL

- [ ] **Step 3: Implement real output recording, screenshot saving, and robust API param parsing**

- 在 `core/audit_logger.py` 中增加 `screenshot_path` 列支持，并在 `log_action` 中根据 `max_output_chars`（0 则不截断）截取真实的 `output_result`；
- 在 `tools/handlers/media_handler.py` 中：当显式截图调用且 `audit_save_screenshots=True` 时，保存图片至 `data/audit_screenshots/` 并记录路径，避免存储 Base64；各 handler 传出真实输出；
- 在 `api/audit_api.py` 中实现 `extract_query_param` 支持 `query / args / query_params`，彻底修复分页停留在第 1 页的缺陷；
- 在 `api/audit_api.py` 中注册 `GET /{plugin_name}/audit/screenshot` 安全接口，校验 `data/audit_screenshots/` 目录范围，提供文件下载与预览。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m unittest tests/test_audit_logger.py tests/test_audit_api.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/audit_logger.py tools/handlers/media_handler.py tools/tools.py api/audit_api.py tests/test_audit_logger.py tests/test_audit_api.py
git commit -m "fix(audit): record real output, persist screenshots and fix query pagination in web api"
```

---

### Task 5: Web UI 前端展示长文本与截图渲染，重新打包构建

**Files:**
- Modify: `web-src/src/types.ts`
- Modify: `web-src/src/App.tsx`
- Modify: `web-src/src/components/AuditCard.tsx`
- Modify: `web-src/src/components/SideDrawer.tsx`
- Modify: `views/audit/` (构建产物)

**Interfaces:**
- Consumes: `/audit/logs` 返回的 `screenshot_path`, `output_result`，以及 `/audit/screenshot` 接口
- Produces: 编译至 `views/audit/` 的静态单页应用

- [ ] **Step 1: Update TypeScript types in `web-src/src/types.ts`**

增加 `screenshot_path?: string` 属性至 `AuditLogItem` 接口。

- [ ] **Step 2: Update `AuditCard.tsx` and `SideDrawer.tsx` for real output and screenshot previews**

- 卡片与抽屉展示真实的 `output_result` 长文本，提供格式化排版、全量复制与长文本折叠；
- 若存在 `screenshot_path`，在卡片上展示图片徽标，在侧边栏抽屉内通过 `api/screenshot` 接口渲染图片预览与全屏大图查看。

- [ ] **Step 3: Fix pagination in `App.tsx` and ensure offline preview works**

- 确保翻页时正确向 Bridge 传递当前 `page` 与 `pageSize`；
- 离线/预览模式下补充 `filtered.slice((page - 1) * pageSize, page * pageSize)`，保证无后端时分页按钮与页码计算同样工作。

- [ ] **Step 4: Build frontend assets to `views/audit/`**

Run: `cd web-src && npm run build` (或 `yarn build` / `pnpm build`)
验证产物正确输出至 `views/audit/`。

- [ ] **Step 5: Commit**

```bash
git add web-src/ views/
git commit -m "feat(web-src): support real output inspection, screenshot previews and build updated views"
```

---

### Task 6: 文档维护、SKILL 指引更新与全链路单测回归

**Files:**
- Modify: `skills/playwright-tool/SKILL.md`
- Modify: `AGENT.md`
- Modify: `CHANGELOG.md`
- Test: `tests/` 全部单测

**Interfaces:**
- Consumes: 全模块新规范与 API
- Produces: 更新后的开发者与大模型文档，100% 通过的单元测试

- [ ] **Step 1: Update `skills/playwright-tool/SKILL.md`**

在 SKILL 文档中说明大模型使用 `pw_page(action='read', target='text')` 阅读正文、`target='elements'` 获取控件的方法，并补充遇到页面弹窗遮挡时的处理策略。

- [ ] **Step 2: Update `AGENT.md` and `CHANGELOG.md`**

记录本次版本变更内容（正文 Markdown 排版、独立分页与检索、Playwright 异常精炼、审计真实输出与截图、WebUI 分页修复）。

- [ ] **Step 3: Run full unit test suite**

Run: `.venv\Scripts\python -m unittest discover tests`
Expected: 所有单元测试 100% PASS（0 failures, 0 errors）。

- [ ] **Step 4: Commit**

```bash
git add skills/playwright-tool/SKILL.md AGENT.md CHANGELOG.md
git commit -m "docs: update skill guide, architecture changelog and verify full test suite"
```
