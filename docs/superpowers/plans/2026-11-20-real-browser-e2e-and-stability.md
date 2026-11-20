# 真实浏览器端到端集成测试与运行时稳定性实现计划 (Real Browser E2E & Stability Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立本地真实的 Camoufox 浏览器端到端（E2E）集成测试套件，修复已有单测导入路径，强化异常调用栈日志输出，固化核心依赖并更新工程开发规范。

**Architecture:** 本地提供包含完备交互元素的静态测试页面，通过轻量级内置 HTTP 服务承载；编写真实无头 Camoufox 驱动的 E2E 测试集，全覆盖 `pw_page`、`pw_interact`、`pw_media` 核心链路；规范化修复旧测试包导入路径；在 Handler 及调度层捕获异常时保全完整 Traceback。

**Tech Stack:** Python 3.12, Playwright, Camoufox, unittest, http.server

**Spec:** `docs/superpowers/specs/2026-11-20-real-browser-e2e-and-stability-design.md`

## Global Constraints

- 严禁在 E2E 测试中使用 Mock 替代真实浏览器或跳过真实页面交互。
- 导入统一采用规范的 Python 包路径（`from astrbot_plugin_playwright_tools...`），不使用过渡性的防御分支。
- 标签页索引在全系统严格统一保持 1-based。
- 本地 E2E 测试必须在无头模式 (`headless=True`) 下于本地 `uv` 环境秒级跑通。

## Review Focus

1. **真实浏览器启动失败或超时**：测试在 Windows 环境下是否能够顺畅启动 Camoufox 并在执行完成后完全退出，无僵尸进程滞留。
2. **多标签页联动识别**：点击 `target="_blank"` 链接后，Playwright 上下文能否正确记录新页，且 `switch_tab` 是否能顺利往返切换。
3. **原生 Alert 弹窗非阻塞应答**：触发原生弹窗时，事件监听器必须自动应答，绝不能导致 `page.evaluate` 或动作调用永久挂起超时。
4. **长截图高度与熔断**：超长页面截图测试能否正确执行并生成有效的 PNG 文件。
5. **单元测试回归**：修复旧测试导入路径后，原有的 61+ 个 Mock 单元测试必须全部通过，无 `ImportError`。

---

### Task 1: 修复已有单元测试导入路径与补充标准依赖声明

**Files:**
- Create: `requirements.txt`
- Modify: `tests/test_context_manager.py:1-25`
- Modify: `tests/test_interact_handler.py:1-25`
- Modify: `tests/test_media_handler.py:1-25`
- Modify: `tests/test_page_handler.py:1-25`
- Modify: `tests/test_tools.py:1-25`
- Test: `tests/test_context_manager.py`, `tests/test_interact_handler.py`, `tests/test_media_handler.py`, `tests/test_page_handler.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: `astrbot_plugin_playwright_tools.core.*`, `astrbot_plugin_playwright_tools.tools.*`
- Produces: 绿色的单元测试套件

- [ ] **Step 1: 创建标准 requirements.txt**
  写入项目核心依赖：
  ```text
  camoufox[geoip]
  playwright
  pyyaml
  ```

- [ ] **Step 2: 规范化修正 5 个测试文件的导入路径**
  在 `tests/test_context_manager.py`、`test_interact_handler.py`、`test_media_handler.py`、`test_page_handler.py`、`test_tools.py` 中：
  确保将 `parent_dir` 设置为包含 `astrbot_plugin_playwright_tools` 的目录，并将 `from core...` 和 `from tools...` 统一更新为 `from astrbot_plugin_playwright_tools.core...` 和 `from astrbot_plugin_playwright_tools.tools...`。

- [ ] **Step 3: 运行全量单元测试验证**
  执行：`.venv\Scripts\python -m unittest discover tests`
  预期：所有测试全部通过（Ran 60+ tests ... OK），无任何 `ImportError`。

- [ ] **Step 4: 提交代码**
  ```bash
  git add requirements.txt tests/
  git commit -m "fix(test): normalize test import paths and add requirements.txt"
  ```

---

### Task 2: 建立本地 E2E 测试页面夹具与轻量 HTTP 测试服务

**Files:**
- Create: `tests/e2e/fixtures/test_page.html`
- Create: `tests/e2e/fixtures/newtab.html`
- Create: `tests/e2e/server.py`
- Test: `tests/e2e/test_server.py`

**Interfaces:**
- Consumes: Python 标准库 `http.server`, `threading`, `socket`
- Produces: `LocalTestServer` 类（提供 `start()`、`stop()`、`get_url(path: str) -> str`）

- [ ] **Step 1: 编写轻量 HTTP 服务管理器的单测 `tests/e2e/test_server.py`**
  ```python
  import unittest
  import urllib.request
  from tests.e2e.server import LocalTestServer

  class TestLocalTestServer(unittest.TestCase):
      def test_server_serves_fixtures(self):
          server = LocalTestServer()
          server.start()
          try:
              url = server.get_url("/test_page.html")
              with urllib.request.urlopen(url) as response:
                  self.assertEqual(response.status, 200)
                  content = response.read().decode("utf-8")
                  self.assertIn("Playwright Tools E2E Test Page", content)
          finally:
              server.stop()
  ```

- [ ] **Step 2: 运行测试验证失败**
  执行：`.venv\Scripts\python -m unittest tests/e2e/test_server.py`
  预期：FAIL（`ModuleNotFoundError: No module named 'tests.e2e.server'`）。

- [ ] **Step 3: 创建测试 HTML 页面**
  - 创建 `tests/e2e/fixtures/test_page.html`：包含标题、文本、`<input id="test-input">`、`<select id="test-select">`、点击变文案的 `<button id="test-btn">`、`<button id="btn-alert" onclick="alert('测试弹窗内容')">`、`<a id="link-new-tab" href="/newtab.html" target="_blank">打开新标签页</a>`，以及高度超过 2500px 的长内容块。
  - 创建 `tests/e2e/fixtures/newtab.html`：包含 `<title>Sub Page New Tab</title>` 和说明文本。

- [ ] **Step 4: 实现 `LocalTestServer` (`tests/e2e/server.py`)**
  使用 `http.server.SimpleHTTPRequestHandler` 与 `ThreadingHTTPServer`，绑定 `127.0.0.1:0`（自动分配空闲端口），根目录指向 `tests/e2e/fixtures`，提供优雅启动与退出接口。

- [ ] **Step 5: 运行测试验证通过**
  执行：`.venv\Scripts\python -m unittest tests/e2e/test_server.py`
  预期：PASS。

- [ ] **Step 6: 提交代码**
  ```bash
  git add tests/e2e/
  git commit -m "feat(test): add local html test fixtures and lightweight test server"
  ```

---

### Task 3: 优化异常调用栈日志保全与修复标签页默认索引

**Files:**
- Modify: `tools/tools.py:100-225`
- Modify: `tools/handlers/page_handler.py:70-130,200-240`
- Modify: `tools/handlers/interact_handler.py:60-120`
- Modify: `tools/handlers/media_handler.py:70-130`
- Test: `tests/test_tools_v2.py`

**Interfaces:**
- Consumes: Python 标准库 `traceback`, `logging`
- Produces: 捕获异常时自动将 `traceback.format_exc()` 记录入日志；`_action_switch_tab` 缺省索引修复为 `1`。

- [ ] **Step 1: 编写标签页缺省参数与异常日志测试用例**
  在 `tests/test_tools_v2.py` 中补充测试：
  - 测试 `_action_switch_tab` 在不传 `tab_index` 参数时默认使用 `1`。
  - 测试 `_execute_with_timeout` 在捕获未预期异常时调用 `logger.error` 且保留完整的 Traceback。

- [ ] **Step 2: 运行测试验证失败**
  执行：`.venv\Scripts\python -m unittest tests/test_tools_v2.py`
  预期：FAIL。

- [ ] **Step 3: 修复 `tools/tools.py`**
  - 在 `_action_switch_tab` 中将 `kwargs.get("tab_index", 0)` 改为 `int(kwargs.get("tab_index", 1) or 1)`。
  - 在 `_execute_with_timeout` 的异常捕获中加入：
    ```python
    tb_str = traceback.format_exc()
    logger.error(f"[PlaywrightTool] 工具执行未预期异常: {e}\n{tb_str}")
    ```

- [ ] **Step 4: 在各个 Handlers 的异常分支中加入 Traceback 记录**
  在 `PageHandler`、`InteractHandler`、`MediaHandler` 各个动作的 `except Exception as e:` 块中，统一记录 `logger.error(f"[PlaywrightTool] <action> 异常: {e}\n{traceback.format_exc()}")`。

- [ ] **Step 5: 运行测试验证通过**
  执行：`.venv\Scripts\python -m unittest tests/test_tools_v2.py`
  预期：PASS。

- [ ] **Step 6: 提交代码**
  ```bash
  git add tools/
  git commit -m "fix(tools): preserve exception traceback in logs and default switch_tab to 1"
  ```

---

### Task 4: 实现真实 Camoufox 浏览器端到端集成测试集

**Files:**
- Create: `tests/e2e/test_real_browser.py`
- Test: `tests/e2e/test_real_browser.py`

**Interfaces:**
- Consumes: `CamoufoxAdapter`, `ContextManager`, `SecurityManager`, `AuditLogger`, `PageExtractor`, `PwPageTool`, `PwInteractTool`, `PwMediaTool`, `LocalTestServer`
- Produces: 覆盖全部核心工具链路的真实 E2E 自动化测试套件

- [ ] **Step 1: 编写端到端集成测试 `tests/e2e/test_real_browser.py`**
  构建端到端异步测试类 `TestRealBrowserE2E`，按顺序真实执行：
  1. `setUpClass` / `tearDownClass`：启动与停止 `LocalTestServer`。
  2. 初始化 `CamoufoxAdapter(headless=True)` 及核心管理器。
  3. `test_01_page_open_read_search`：调用 `pw_page(action='open', url=...)` 校验标题；调用 `read` 校验元素编号；调用 `search` 校验关键词。
  4. `test_02_interact_fill_click_select_scroll`：调用 `pw_interact(action='fill')` 输入文本；调用 `click` 点击按钮验证 DOM 状态更新；调用 `select` 选择选项；调用 `scroll` 滚动页面。
  5. `test_03_dialog_handling`：调用 `pw_page(action='dialog', dialog_action='accept')`，点击 Alert 按钮，验证弹窗自动接受且调用未阻塞。
  6. `test_04_multi_tabs`：点击 `target="_blank"` 链接，调用 `pw_page(action='switch_tab', tab_index=2)` 切换至新标签页并验证新页面标题；调用 `switch_tab(tab_index=1)` 切回主页。
  7. `test_05_media_screenshots`：调用 `pw_media(action='screenshot_viewport')` 和 `screenshot_full`，验证图片文件已真实保存至磁盘。
  8. `test_06_close_browser`：调用 `pw_page(action='close')`，验证浏览器上下文完全释放。
  9. `tearDownClass` 中调用 `await adapter.stop()` 彻底关闭底层浏览器进程。

- [ ] **Step 2: 在本机真实环境中执行 E2E 测试**
  执行：`.venv\Scripts\python -m unittest tests/e2e/test_real_browser.py -v`
  预期：全部 6 个测试点全部通过（OK），且控制台可见 Camoufox 浏览器内核真实拉起和关闭。

- [ ] **Step 3: 提交代码**
  ```bash
  git add tests/e2e/test_real_browser.py
  git commit -m "test(e2e): add comprehensive real Camoufox end-to-end integration test suite"
  ```

---

### Task 5: 更新工程规范与版本变更文档

**Files:**
- Modify: `AGENT.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: 本计划中已验证的工程成果
- Produces: 更新后的开发指引与变更日志

- [ ] **Step 1: 更新 `AGENT.md`**
  在 `## 环境` 与 `## 测试规范` 章节增加明确约束：
  - “任何对 `tools/`、`core/` 或 `adapts/` 的修改，除了跑通 Mock 单测外，必须在本机运行 `python -m unittest tests/e2e/test_real_browser.py -v`，确保真实 Camoufox 浏览器操作完全正常后方可交付。”

- [ ] **Step 2: 更新 `CHANGELOG.md`**
  记录 v2.1.2 稳定性与端到端测试更新内容。

- [ ] **Step 3: 整体回归测试验证**
  执行：
  1. `.venv\Scripts\python -m unittest discover tests`
  2. `.venv\Scripts\python -m unittest tests/e2e/test_real_browser.py -v`
  预期：全套单测与 E2E 测试 100% 绿色通过。

- [ ] **Step 4: 提交代码**
  ```bash
  git add AGENT.md CHANGELOG.md
  git commit -m "docs: enforce real browser e2e testing rule in AGENT.md and update changelog"
  ```
