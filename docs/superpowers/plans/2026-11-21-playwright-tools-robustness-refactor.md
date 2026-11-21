# Playwright Tools 健壮性与架构重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全面重构 Playwright 工具体系，实现字符串 Ref ID 单调递增、密码填表全链路脱敏、BaseActionHandler 统一切面复用、官方 ARIA 原生引擎替换、页面稳定与四重快照失效、上下文创建异常资源回滚、死代码清理与平台合规治理（专属持久化路径与统一 Logger）。

**Architecture:** 提取 `BaseActionHandler` 模板方法收敛鉴权、审计、脱敏、异常与页面就绪等待；重写 `AriaSnapshotReader` 直连 Playwright 原生 `aria_snapshot(mode='ai')` 与 `aria-ref=` 定位；在 `ContextManager` 与 `PageSnapshot` 中内置单调递增 Ref、导航监听、URL 比对与 60s TTL。

**Tech Stack:** Python 3.12, Playwright 1.62.0, Camoufox, AstrBot SDK, unittest.

**Spec:** [`docs/superpowers/specs/2026-11-21-playwright-tools-robustness-refactor-design.md`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-21-playwright-tools-robustness-refactor-design.md)

## Global Constraints

- 日志必须且只能从 `astrbot.api` 导入（`from astrbot.api import logger`），严禁使用 Python 内置 `logging` 模块或其他第三方日志库。
- 持久化数据默认根目录必须为 `data/plugin_data/astrbot_plugin_playwright_tools/`。
- 所有复合工具必须统一维护 `_actions` 字典分发；执行必须包含全局超时保护。
- 保证所有单元测试 100% 通过（`.venv/bin/python -m unittest discover tests`），不引入真实浏览器 e2e 测试。
- 文本与注释表达严谨简洁，不出现绝对化词汇（如“彻底xxx”、“根治xxx”）。

## Review Focus

- 输入包含特殊字符的字符串 Ref ID（如 `"e1"`, `"f0e2"`, `"123"`）在 `pw_interact` 与 `pw_media` 中被正确识别且不触发类型错误。
- 页面含有 `type="password"` 的输入框在 `mask_password_inputs=True` 时，审计记录的 `input_args` 和返回值必须输出 `******`，且错误日志中不能出现真实密码。
- 页面发生内部长轮询或 WebSocket 连接时，`wait_page_stable` 必须在 1.5 秒后超时放行，不得永久阻塞或报错终止。
- `ContextManager._create_new_context` 在 `new_page()` 抛出异常时，底层的 `BrowserContext` 必须被立即调用 `close()` 关闭释放。
- 单元测试在离线环境中无全局 `astrbot` 包时，必须能通过 mock 正确导入所有模块并不依赖标准库 `logging`。

---

### Task 1: 平台合规治理与数据持久化路径迁移

**Files:**
- Modify: `requirements.txt`
- Modify: `_conf_schema.json`
- Modify: `main.py:80-92`
- Modify: `tools/handlers/media_handler.py:10-35`
- Modify: `tools/handlers/page_handler.py:10-16`
- Modify: `tools/handlers/interact_handler.py:10-20`
- Modify: `tools/tools.py:8-14`
- Test: `tests/test_plugin_main.py`
- Test: `tests/test_conf_schema.py`

**Interfaces:**
- Consumes: `astrbot.api.logger`
- Produces: 规范的专属数据路径常量与无 `logging` 回退的清洁导入。

- [ ] **Step 1: 编写合规检查单元测试**

在 `tests/test_conf_schema.py` 与 `tests/test_plugin_main.py` 中添加针对 `data/plugin_data/astrbot_plugin_playwright_tools/` 默认路径以及禁止在 `tools/` 代码中直接 `import logging` 的断言测试：

```python
def test_storage_paths_default_to_plugin_data(self):
    self.assertEqual(
        self.plugin.download_save_path,
        "data/plugin_data/astrbot_plugin_playwright_tools/downloads"
    )
    self.assertEqual(
        self.plugin.screenshot_save_path,
        "data/plugin_data/astrbot_plugin_playwright_tools/screenshots"
    )
    self.assertEqual(
        self.plugin.audit_db_path,
        "data/plugin_data/astrbot_plugin_playwright_tools/audit.db"
    )
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m unittest tests/test_conf_schema.py tests/test_plugin_main.py`
Expected: FAIL（原路径仍为 `data/downloads`、`data/audit.db` 等）。

- [ ] **Step 3: 移除 `import logging` 回退、更新持久化路径与依赖版本**

1. 在 `requirements.txt` 中将 `playwright` 明确指定为 `playwright>=1.62.0`，锁定对 `mode='ai'` 与 `aria-ref=` 的原生支持。
2. 在 `tools/tools.py`、`tools/handlers/page_handler.py`、`tools/handlers/interact_handler.py`、`tools/handlers/media_handler.py` 中，删除 `try: from astrbot.api import logger except ImportError: import logging...`，改为纯粹的 `from astrbot.api import logger`。
3. 在 `_conf_schema.json` 中将 `download_save_path` 默认值改为 `"data/plugin_data/astrbot_plugin_playwright_tools/downloads"`，`screenshot_save_path` 默认值改为 `"data/plugin_data/astrbot_plugin_playwright_tools/screenshots"`。
4. 在 `main.py` 中将 `download_save_path`、`screenshot_save_path` 与 `audit_db_path` 默认值更新为 `data/plugin_data/astrbot_plugin_playwright_tools/...`。
5. 在 `MediaHandler.__init__` 中将 `audit_screenshots_dir` 默认值更新为 `"data/plugin_data/astrbot_plugin_playwright_tools/audit_screenshots"`。

- [ ] **Step 4: 运行测试验证**

Run: `.venv/bin/python -m unittest tests/test_conf_schema.py tests/test_plugin_main.py`
Expected: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add _conf_schema.json main.py tools/ tests/
git commit -m "fix(compliance): migrate data paths to plugin_data and enforce astrbot.api logger"
```

---

### Task 2: 清理历史废弃的 `PageExtractor` 死代码

**Files:**
- Delete: `core/page_extractor.py`
- Delete: `tests/test_page_extractor.py`
- Modify: `main.py:15,97-100,127`
- Modify: `tools/handlers/page_handler.py:8,26,33-37,199-219`
- Modify: `tests/test_plugin_main.py:314-316`

**Interfaces:**
- Consumes: 现有 `readers` 体系。
- Produces: 彻底移除 `PageExtractor` 及 `search_page` 遗留接口。

- [ ] **Step 1: 检查现有依赖**

运行全量测试确认当前基线通过：
Run: `.venv/bin/python -m unittest discover tests`
Expected: PASS。

- [ ] **Step 2: 删除 `page_extractor.py` 及单测，清理调用点**

1. 删除 `core/page_extractor.py` 与 `tests/test_page_extractor.py`。
2. 在 `main.py` 中移除 `PageExtractor` 导入、实例化及传递给 `PageHandler` 的参数。
3. 在 `tools/handlers/page_handler.py` 中移除 `PageExtractor` 导入、`__init__` 中的参数与属性赋值，移除废弃的 `search_page` 方法。
4. 在 `tests/test_plugin_main.py` 中移除测试 `page_extractor` 的断言。

- [ ] **Step 3: 运行测试验证**

Run: `.venv/bin/python -m unittest discover tests`
Expected: PASS（无 `ModuleNotFoundError` 且所有测试通过）。

- [ ] **Step 4: 提交更改**

```bash
git rm core/page_extractor.py tests/test_page_extractor.py
git add main.py tools/handlers/page_handler.py tests/test_plugin_main.py
git commit -m "refactor: remove obsolete PageExtractor dead code and legacy search_page"
```

---

### Task 3: 上下文管理器资源回滚、单调递增 Ref 计数与路由监听

**Files:**
- Modify: `core/context_manager.py:17-40,210-272`
- Test: `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `BrowserAdapterBase.create_context`, `BrowserSessionContext`.
- Produces: `BrowserSessionContext.next_ref_id: int`, `allocate_ref_id() -> str`, 路由监听自动失效，以及创建异常时释放 `BrowserContext`。

- [ ] **Step 1: 编写创建失败回滚与 Ref ID 递增单测**

在 `tests/test_context_manager.py` 中添加针对创建失败资源自动清理与 `allocate_ref_id` 循环递增溢出回滚的测试：

```python
def test_allocate_ref_id_monotonic_and_rollover(self):
    ctx = BrowserSessionContext(session_id="s1", owner_id="u1", browser_context=MagicMock(), current_page=MagicMock())
    self.assertEqual(ctx.allocate_ref_id(), "1")
    ctx.next_ref_id = 1_000_000
    self.assertEqual(ctx.allocate_ref_id(), "1000000")
    self.assertEqual(ctx.allocate_ref_id(), "0")

async def test_create_context_cleans_up_on_failure(self):
    mock_adapter = MagicMock()
    mock_browser_ctx = AsyncMock()
    mock_adapter.create_context = AsyncMock(return_value=mock_browser_ctx)
    mock_browser_ctx.new_page = AsyncMock(side_effect=RuntimeError("New page failed"))
    mgr = ContextManager(adapter=mock_adapter, security=MagicMock())
    with self.assertRaises(RuntimeError):
        await mgr._create_new_context("s1", "u1")
    mock_browser_ctx.close.assert_awaited_once()
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m unittest tests/test_context_manager.py`
Expected: FAIL（`allocate_ref_id` 不存在，异常时未触发 `close`）。

- [ ] **Step 3: 实现异常回滚、`allocate_ref_id` 与路由监听**

1. 在 `BrowserSessionContext` 中添加 `next_ref_id: int = 1` 与方法：
```python
def allocate_ref_id(self) -> str:
    current = self.next_ref_id
    if current >= 1_000_000:
        self.next_ref_id = 0
    else:
        self.next_ref_id += 1
    return str(current)
```
2. 在 `_create_new_context` 中使用 `try...except` 保护：若任何后续步骤报错，立即调用 `await browser_ctx.close()` 并重新抛出异常。
3. 在首个 page 及 `_on_popup` 的新 page 上挂载 `page.on("framenavigated", _on_frame_nav)`：仅当主 frame 发生导航时，将 `ctx.is_snapshot_dirty = True`、`ctx.current_snapshot = None`、`ctx.ref_map = {}`。

- [ ] **Step 4: 运行测试验证**

Run: `.venv/bin/python -m unittest tests/test_context_manager.py`
Expected: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/context_manager.py tests/test_context_manager.py
git commit -m "feat(context): add context creation rollback, monotonic ref counter, and navigation invalidation"
```

---

### Task 4: 官方 ARIA 快照与字符串 Ref 映射重构

**Files:**
- Modify: `core/readers/base.py:6-16`
- Modify: `core/readers/aria_reader.py`
- Modify: `core/readers/markdown_reader.py`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: Playwright `page.locator(':root').aria_snapshot(mode='ai')`, `PageSnapshot`.
- Produces: 官方 ARIA YAML 解析与字符串 Ref Map 映射。

- [ ] **Step 1: 编写官方 ARIA 原生快照与字符串 Ref 单测**

在 `tests/test_readers.py` 中更新单测，测试：
1. `PageSnapshot` 的 `timestamp` 属性与字符串键 `ref_map: dict[str, dict]`；
2. `InlineMarkdownReader` 分配字符串形式 Ref ID；
3. `AriaSnapshotReader.extract_snapshot` 调用 `page.locator(":root").aria_snapshot(mode="ai")`，并从输出的 YAML 中抽取 `[ref=e1]` 等 Ref ID 写入 `ref_map`。

```python
async def test_aria_snapshot_reader_official_mode(self):
    mock_page = MagicMock()
    mock_root = AsyncMock()
    mock_root.aria_snapshot = AsyncMock(return_value='- heading "Title" [level=1]\n- button "Submit" [ref=e1]')
    mock_page.locator.return_value = mock_root
    mock_page.url = "https://example.com"
    reader = AriaSnapshotReader()
    snapshot = await reader.extract_snapshot(mock_page, "https://example.com")
    self.assertIn("e1", snapshot.ref_map)
    self.assertIn('button "Submit" [ref=e1]', snapshot.raw_content)
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m unittest tests/test_readers.py`
Expected: FAIL。

- [ ] **Step 3: 重构 `AriaSnapshotReader` 与 `base.py`**

1. 在 `core/readers/base.py` 中，为 `PageSnapshot` 添加 `timestamp: float = field(default_factory=time.time)`，`ref_map: dict[str, dict]`。
2. 在 `core/readers/aria_reader.py` 中：
   - 移除全部 JavaScript DOM 遍历注入长文本脚本与 `AriaNode` 冗余代码；
   - `extract_snapshot` 中调用 `await page.locator(':root').aria_snapshot(mode='ai')`；
   - 使用正则匹配 `\[ref=([a-zA-Z0-9_\-]+)\]` 提取所有引用的元素标识，填充 `ref_map[ref] = {"ref": ref}`；
   - 按块切分并保持搜索与分页能力。
3. 在 `core/readers/markdown_reader.py` 中：
   - 提取时接收外部上下文的起始 `ref_id` 或将分配结果规整为字符串键 `str(ref)`。

- [ ] **Step 4: 运行测试验证**

Run: `.venv/bin/python -m unittest tests/test_readers.py`
Expected: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/ tests/test_readers.py
git commit -m "feat(readers): replace custom ARIA with official aria_snapshot and support string ref_map"
```

---

### Task 5: 提取 `BaseActionHandler` 统一切面与密码脱敏

**Files:**
- Create: `tools/handlers/base_handler.py`
- Test: `tests/test_base_handler.py`

**Interfaces:**
- Consumes: `ContextManager`, `SecurityManager`, `AuditLogger`.
- Produces: `BaseActionHandler.execute_action()`, `BaseActionHandler.wait_page_stable()`.

- [ ] **Step 1: 编写 `BaseActionHandler` 独立单元测试**

在 `tests/test_base_handler.py` 中编写单测，覆盖：
1. 鉴权失败时记录拒绝审计并返回错误提示；
2. 正常执行时记录成功审计；
3. 执行抛出异常时记录错误审计并调用 `clean_playwright_error`；
4. 密码输入脱敏：当 `mask_password_inputs=True` 且检测到 password 类型时，审计 `input_args` 和日志中的密码值为 `******`；
5. `wait_page_stable` 正常与超时熔断容错。

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m unittest tests/test_base_handler.py`
Expected: FAIL（`base_handler.py` 尚未创建）。

- [ ] **Step 3: 实现 `BaseActionHandler`**

创建 `tools/handlers/base_handler.py`：
1. 包含 `clean_playwright_error` 清洗逻辑；
2. 实现 `wait_page_stable(page, timeout=1.5)`：等待 `domcontentloaded` + `networkidle`，超时不抛异常平滑放行；
3. 实现 `execute_action(...)`：统一上下文寻址、权限检查、密码脱敏、执行调度、错误清洗与审计上报。

- [ ] **Step 4: 运行测试验证**

Run: `.venv/bin/python -m unittest tests/test_base_handler.py`
Expected: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add tools/handlers/base_handler.py tests/test_base_handler.py
git commit -m "feat(handlers): add BaseActionHandler with unified execution and password masking"
```

---

### Task 6: 重构具体 Handlers 接入 `BaseActionHandler` 并支持字符串 Ref

**Files:**
- Modify: `tools/handlers/page_handler.py`
- Modify: `tools/handlers/interact_handler.py`
- Modify: `tools/handlers/media_handler.py`
- Test: `tests/test_page_handler.py`
- Test: `tests/test_interact_handler.py`
- Test: `tests/test_media_handler.py`

**Interfaces:**
- Consumes: `BaseActionHandler`.
- Produces: 继承基类的 `PageHandler`, `InteractHandler`, `MediaHandler`，支持字符串 `ref` 及原生 `aria-ref=` 定位。

- [ ] **Step 1: 更新 Handlers 单元测试**

更新 `tests/test_page_handler.py`、`tests/test_interact_handler.py` 与 `tests/test_media_handler.py`：
1. 传入字符串形式的 `ref`（如 `"1"`, `"e1"`）；
2. 验证 `interact_handler` 针对 `e1` 时调用 `page.locator("aria-ref=e1")`，针对 `"1"` 时调用 `page.locator('[data-astr-ref="1"]')`；
3. 验证 `page_handler.read_page` 具备四重失效（`snapshot.timestamp` 超过 60s 或 URL 变化时自动刷新）。

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m unittest tests/test_page_handler.py tests/test_interact_handler.py tests/test_media_handler.py`
Expected: FAIL。

- [ ] **Step 3: 重构 Handlers 继承 `BaseActionHandler`**

1. 让 `PageHandler`、`InteractHandler`、`MediaHandler` 继承 `BaseActionHandler`。
2. 将所有方法的鉴权、审计、上下文解析和异常捕获剥离，委托给 `self.execute_action()`。
3. 在 `InteractHandler` 中：
   - 入参类型变为 `ref: str`；
   - 编写定位辅助方法：若 `str(ref).startswith("e")` 或匹配 `(f\d+)?e\d+`，则定位 `aria-ref={ref}`，否则定位 `[data-astr-ref="{ref}"]`；
   - 在 `fill_form` 中增加对目标 input 组件 `type == 'password'` 的探测。
4. 在 `PageHandler.read_page` 中：
   - 增加四重失效判定：`ctx.is_snapshot_dirty` 或 `time.time() - snapshot.timestamp > 60` 或 `current_url != snapshot.url`；
   - 提取快照前调用 `await self.wait_page_stable(ctx.current_page)`。
5. 在 `MediaHandler.download_file` 中：入参类型变为 `ref: str`。

- [ ] **Step 4: 运行测试验证**

Run: `.venv/bin/python -m unittest tests/test_page_handler.py tests/test_interact_handler.py tests/test_media_handler.py`
Expected: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add tools/handlers/ tests/
git commit -m "refactor(handlers): migrate PageHandler, InteractHandler and MediaHandler to BaseActionHandler"
```

---

### Task 7: 更新工具 Schema、门面调用与主入口连接

**Files:**
- Modify: `tools/schemas.py`
- Modify: `tools/tools.py`
- Modify: `main.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: 重构后的 Handlers 与字符串 Ref。
- Produces: 面向大模型的纯字符串 `ref` 工具定义与无错误运转的主入口。

- [ ] **Step 1: 编写工具门面与 Schema 单元测试**

在 `tests/test_tools.py` 中更新用例，验证 `pw_interact` 与 `pw_media` 的入参 schema 中 `ref` 为 `type: string`，且传入字符串参数（如 `ref="e2"`）能正确派发给 handler。

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m unittest tests/test_tools.py`
Expected: FAIL（Schema 中 `ref` 仍限制为 `integer`）。

- [ ] **Step 3: 更新 Schema 与门面**

1. 在 `tools/schemas.py` 中：
   - `PW_INTERACT_SCHEMA`: `ref` 属性修改为 `{"type": "string", "description": "目标操作元素的 Ref 编号或标识符（如 '1', 'e2'）"}`；
   - `PW_MEDIA_SCHEMA`: `download` 动作中的 `ref` 修改为 `{"type": "string", "description": "触发下载操作的目标元素 Ref 编号（如 '1', 'e2'）"}`。
2. 在 `tools/tools.py` 中：
   - 保持字符串 `ref` 传递；
   - 清理所有旧参数转换。
3. 在 `main.py` 中：
   - 传递 `mask_password_inputs` 给 Handler 初始化。

- [ ] **Step 4: 运行测试验证**

Run: `.venv/bin/python -m unittest tests/test_tools.py tests/test_plugin_main.py`
Expected: PASS。

- [ ] **Step 5: 提交更改**

```bash
git add tools/ main.py tests/
git commit -m "feat(tools): update schemas and facade to support string ref IDs and password desensitization"
```

---

### Task 8: 更新 SKILL、文档与变更日志

**Files:**
- Modify: `skills/playwright-tool/SKILL.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: 重构完成后的完整系统架构。
- Produces: 与实现 100% 同步的高质量文档。

- [ ] **Step 1: 更新 `skills/playwright-tool/SKILL.md`**

1. 将所有示例中的 `ref=1` 改为字符串形式（如 `ref='1'` 或 `ref='e1'`）；
2. 说明 Ref ID 由阅读器生成，可能为数字编号（Markdown 模式）或语义标识（ARIA 模式）；
3. 强调支持字符串格式。

- [ ] **Step 2: 更新 `docs/ARCHITECTURE.md`**

1. 在架构图中引入 `BaseActionHandler` 切面层；
2. 描述官方 `aria_snapshot(mode='ai')` 原生实现与 `aria-ref=` 选择器；
3. 记录页面就绪等待与四重快照失效机制；
4. 记录平台合规专属路径 `data/plugin_data/astrbot_plugin_playwright_tools/` 与 Logger 规范。

- [ ] **Step 3: 更新 `CHANGELOG.md`**

在 `CHANGELOG.md` 顶部添加新版本变更条目，总结 8 项核心重构与 2 项合规改进。

- [ ] **Step 4: 运行全量单元测试做最终验收**

Run: `.venv/bin/python -m unittest discover tests`
Expected: 100% 全部通过，无任何 warning 或 error。

- [ ] **Step 5: 提交更改**

```bash
git add skills/ docs/ CHANGELOG.md
git commit -m "docs: update SKILL, architecture doc, and changelog for robustness refactor"
```
