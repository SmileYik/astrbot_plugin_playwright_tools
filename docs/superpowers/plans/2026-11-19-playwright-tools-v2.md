# Playwright Tools v2 Refactoring & Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 AstrBot 浏览器工具插件（astrbot_plugin_playwright_tools），将原子工具收敛为 3 个继承 `FunctionTool` 的类型化复合工具（`pw_page`, `pw_interact`, `pw_media`），补齐悬停/拖拽/按键/聚焦等能力，引入视口/长截图双重熔断、单工具超时中断、动态系统提示词注入与页面关键字查询。

**Architecture:** 采用 `FunctionTool` 门面分发器 + 模块化 Handlers 架构：`tools/handlers/` 负责底层 Playwright 逻辑；`tools/schemas.py` 定义 JSON Schema；`tools/tools.py` 封装 `FunctionTool` 子类并施加 `asyncio.wait_for` 超时熔断；`main.py` 通过 `context.add_llm_tools` 进行类型注册并挂载 `@filter.on_llm_request()` 提示词注入钩子。

**Tech Stack:** Python 3.10+, Playwright/Camoufox, AstrBot FunctionTool API, SQLite3, unittest

**Spec:** `docs/superpowers/specs/2026-11-19-playwright-tools-design.md`

## Global Constraints

- **代码与注释风格**：严格遵循 `AGENT.md`，文档、注释及返回给 AI 的提示必须做到凝练简洁，不啰嗦。
- **架构哲学**：坚持 Simplicity First，杜绝过渡抽象与投机性特性；坚持 Surgical Changes 与 Goal-Driven 开发。
- **类型化注册规范**：必须继承 `FunctionTool[AstrAgentContext]`，通过 `self.context.add_llm_tools(...)` 进行注册。
- **工具命名前缀**：大模型工具名称统一以 `pw_` 为前缀（`pw_page`, `pw_interact`, `pw_media`）。
- **零凭据泄露与零 HTML 倾倒**：严禁向大模型泄露 Cookie / StorageState 或直接返回未过滤的原始 HTML。

## Review Focus

1. **未定义动作的友好拦截**：传入未知的 `action`（如 `pw_page(action="xyz")`）必须返回包含合法动作列表的友好错误提示，不得崩溃。
2. **工具全局超时熔断**：当工具执行耗时超过 `tool_execution_timeout_seconds` 时，必须立即强制终止底层协程并返回明确超时信息。
3. **长截图双重熔断机制**：长截图超过 `screenshot_max_height_px` 像素时自动截断至限制高度；耗时超过 `screenshot_timeout_seconds` 时回退至当前视口截图。
4. **拖拽源/目标元素不存在时的错误处理**：`pw_interact(action="drag", ref=1, target_ref=99)` 中任意 Ref 无效时，必须返回精准的无效引用提示。
5. **系统提示词注入开关控制**：当 `system_prompt_injection` 为空字符串时跳过注入；配置非空时安全追加至 `req.system_prompt`。

---

### Task 1: 页面检索与关键词快速匹配 (PageExtractor.search_snapshot)

**Files:**
- Modify: `core/page_extractor.py`
- Test: `tests/test_page_extractor.py`

**Interfaces:**
- Consumes: Standard library `re`
- Produces: `PageExtractor.search_snapshot(snapshot_text: str, keyword: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_page_extractor.py
def test_search_snapshot_matching(self):
    elements = [
        {"tag": "input", "type": "text", "name": "kw", "placeholder": "搜索文章", "text": "", "value": ""},
        {"tag": "button", "type": "submit", "name": "", "placeholder": "", "text": "立即提交", "value": ""}
    ]
    text_blocks = ["欢迎访问技术文档首页", "这是用户登录指南"]
    text, _ = self.extractor.extract_snapshot("首页", "https://home.com", elements, text_blocks)
    
    # search existing keyword
    search_res = self.extractor.search_snapshot(text, "提交")
    self.assertIn("找到", search_res)
    self.assertIn("[2] [按钮] \"立即提交\"", search_res)

    # search non-existing keyword
    no_res = self.extractor.search_snapshot(text, "不存在的词汇")
    self.assertIn("未找到匹配", no_res)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_page_extractor.py`
Expected: FAIL with `AttributeError: 'PageExtractor' object has no attribute 'search_snapshot'`

- [ ] **Step 3: Implement `search_snapshot` in `core/page_extractor.py`**

Scan snapshot lines; extract lines containing keyword (case-insensitive); format with matching line count and Ref ID highlights.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_page_extractor.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/page_extractor.py tests/test_page_extractor.py
git commit -m "feat(extractor): add search_snapshot keyword query support"
```

---

### Task 2: DOM 与键鼠交互 Handler 扩展 (`tools/handlers/interact_handler.py`)

**Files:**
- Create: `tools/handlers/__init__.py`
- Create: `tools/handlers/interact_handler.py`
- Test: `tests/test_interact_handler.py`

**Interfaces:**
- Consumes: `core.context_manager.ContextManager`, `core.security_manager.SecurityManager`, `core.audit_logger.AuditLogger`
- Produces: `InteractHandler` with methods:
  - `click(session_id, sender_id, ref: int)`
  - `fill_form(session_id, sender_id, ref: int, text: str)`
  - `select_option(session_id, sender_id, ref: int, value: str)`
  - `hover(session_id, sender_id, ref: int)`
  - `focus(session_id, sender_id, ref: int)`
  - `blur(session_id, sender_id, ref: int)`
  - `drag(session_id, sender_id, ref: int, target_ref: int)`
  - `press_key(session_id, sender_id, key: str)`
  - `scroll(session_id, sender_id, direction: str, amount: int)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interact_handler.py
import unittest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.handlers.interact_handler import InteractHandler

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestInteractHandler(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_audit = MagicMock()

        self.mock_page = MagicMock()
        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.ref_map = {1: {"tag": "div", "text": "card1"}, 2: {"tag": "div", "text": "target_bin"}}

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = InteractHandler(self.mock_mgr, self.mock_sec, self.mock_audit)

    def test_hover_element(self):
        async def mock_eval(script):
            return True
        self.mock_page.evaluate = mock_eval
        res = run_coro(self.handler.hover("s1", "u1", ref=1))
        self.assertIn("已成功悬停", res)

    def test_drag_element_missing_target(self):
        res = run_coro(self.handler.drag("s1", "u1", ref=1, target_ref=99))
        self.assertIn("无效的拖拽目标", res)

    def test_press_key(self):
        async def mock_key(key):
            return None
        self.mock_page.keyboard = MagicMock()
        self.mock_page.keyboard.press = mock_key
        res = run_coro(self.handler.press_key("s1", "u1", key="Enter"))
        self.assertIn("已成功向页面发送按键", res)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_interact_handler.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.handlers'`

- [ ] **Step 3: Implement `tools/handlers/interact_handler.py`**

Migrate and expand from `ActionTools`: implement `hover` (dispatch mouseover/mouseenter and `hover()`), `focus` (`target.focus()`), `blur` (`target.blur()`), `drag` (drag & drop simulation via data-astr-ref), `press_key` (`page.keyboard.press`), `scroll`, `click`, `fill_form`, `select_option`. Record audit logs for all actions.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_interact_handler.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/ tests/test_interact_handler.py
git commit -m "feat(interact): implement InteractHandler with hover, drag, focus, blur and press_key"
```

---

### Task 3: 页面导航与检索 Handler (`tools/handlers/page_handler.py`)

**Files:**
- Create: `tools/handlers/page_handler.py`
- Test: `tests/test_page_handler.py`

**Interfaces:**
- Consumes: `core.context_manager.ContextManager`, `core.security_manager.SecurityManager`, `core.audit_logger.AuditLogger`, `core.page_extractor.PageExtractor`
- Produces: `PageHandler` with methods:
  - `open_url(session_id, sender_id, url: str)`
  - `read_page(session_id, sender_id, page: int)`
  - `search_page(session_id, sender_id, keyword: str)`
  - `switch_tab(session_id, sender_id, tab_index: int)`
  - `handle_dialog(session_id, sender_id, action: str, prompt_text: str | None)`
  - `close_browser(session_id, sender_id)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_page_handler.py
import unittest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.handlers.page_handler import PageHandler
from core.page_extractor import PageExtractor

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestPageHandler(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_audit = MagicMock()
        self.extractor = PageExtractor()

        self.mock_page = MagicMock()
        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.ref_map = {}
        self.mock_context.pages = [self.mock_page]

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = PageHandler(self.mock_mgr, self.mock_sec, self.mock_audit, self.extractor)

    def test_search_page_action(self):
        async def mock_eval(script):
            return {"title": "Test Page", "url": "https://test.com", "elements": [], "text_blocks": ["这里包含重要搜索关键词内容"]}
        self.mock_page.evaluate = mock_eval

        res = run_coro(self.handler.search_page("s1", "u1", keyword="搜索关键词"))
        self.assertIn("找到", res)
        self.assertIn("重要搜索关键词内容", res)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_page_handler.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.handlers.page_handler'`

- [ ] **Step 3: Implement `tools/handlers/page_handler.py`**

Consolidate `browse_tools.py` and `dialog_tools.py` into `PageHandler`, adding `search_page` which evaluates DOM snapshot and calls `page_extractor.search_snapshot`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_page_handler.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/page_handler.py tests/test_page_handler.py
git commit -m "feat(page): implement PageHandler with keyword search and unified dialog support"
```

---

### Task 4: 媒体与截图双重熔断 Handler (`tools/handlers/media_handler.py`)

**Files:**
- Create: `tools/handlers/media_handler.py`
- Test: `tests/test_media_handler.py`

**Interfaces:**
- Consumes: `core.context_manager.ContextManager`, `core.security_manager.SecurityManager`, `core.audit_logger.AuditLogger`
- Produces: `MediaHandler` with methods:
  - `screenshot_viewport(session_id, sender_id, target: str)`
  - `screenshot_full(session_id, sender_id, target: str, max_height_px: int, timeout_sec: int)`
  - `download_file(session_id, sender_id, ref: int)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_media_handler.py
import unittest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.handlers.media_handler import MediaHandler

TEMP_DIR = Path(tempfile.gettempdir()) / "astrbot_test_media_v2"

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestMediaHandler(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_audit = MagicMock()

        self.mock_page = MagicMock()
        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.pages = [self.mock_page]

        async def mock_resolve(session_id, sender_id):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = MediaHandler(
            self.mock_mgr, self.mock_sec, self.mock_audit,
            allow_screenshot_to_ai=True,
            download_dir=str(TEMP_DIR / "downloads")
        )

    def test_screenshot_full_height_clipped(self):
        # mock page height > max_height_px (e.g. 15000 > 8000)
        async def mock_eval(script):
            return 15000
        async def mock_screenshot(**kwargs):
            return b"fake_png_full"
        self.mock_page.evaluate = mock_eval
        self.mock_page.screenshot = mock_screenshot

        res = run_coro(self.handler.screenshot_full(
            "s1", "u1", target="chat", max_height_px=8000, timeout_sec=15
        ))
        self.assertTrue(res.startswith("[IMAGE_PATH:"))
        self.assertIn("已自动截断", res)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_media_handler.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.handlers.media_handler'`

- [ ] **Step 3: Implement `tools/handlers/media_handler.py`**

Implement `screenshot_viewport(full_page=False)`, `screenshot_full(full_page=True)` with height inspection. If height exceeds `max_height_px`, use clip/viewport restriction or note truncation; wrap with `screenshot_timeout_seconds` fallback; implement `download_file` using `data-astr-ref`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_media_handler.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/media_handler.py tests/test_media_handler.py
git commit -m "feat(media): implement MediaHandler with viewport and fullpage fused screenshot"
```

---

### Task 5: 参数 Schema 与复合 `FunctionTool` 门面及超时保护 (`tools/schemas.py`, `tools/tools.py`)

**Files:**
- Create: `tools/schemas.py`
- Create: `tools/tools.py`
- Test: `tests/test_tools_v2.py`

**Interfaces:**
- Consumes: `astrbot.api.FunctionTool`, `tools.handlers.*`
- Produces:
  - `@dataclass class PwPageTool(FunctionTool[AstrAgentContext])`
  - `@dataclass class PwInteractTool(FunctionTool[AstrAgentContext])`
  - `@dataclass class PwMediaTool(FunctionTool[AstrAgentContext])`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools_v2.py
import unittest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.tools import PwPageTool, PwInteractTool, PwMediaTool

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

class TestToolsV2(unittest.TestCase):
    def setUp(self):
        self.mock_page_handler = MagicMock()
        self.mock_interact_handler = MagicMock()
        self.mock_media_handler = MagicMock()

        self.mock_context_wrapper = MagicMock()
        self.mock_context_wrapper.event.session_id = "s1"
        self.mock_context_wrapper.event.get_sender_id.return_value = "u1"

        self.page_tool = PwPageTool(self.mock_page_handler, timeout_seconds=5)
        self.interact_tool = PwInteractTool(self.mock_interact_handler, timeout_seconds=5)
        self.media_tool = PwMediaTool(self.mock_media_handler, timeout_seconds=5)

    def test_invalid_action_rejected(self):
        res = run_coro(self.page_tool.call(self.mock_context_wrapper, action="unknown_action"))
        self.assertIn("未知的动作", res)

    def test_interact_tool_dispatch_click(self):
        async def mock_click(s_id, u_id, ref):
            return "点击成功"
        self.mock_interact_handler.click = mock_click

        res = run_coro(self.interact_tool.call(self.mock_context_wrapper, action="click", ref=1))
        self.assertEqual(res, "点击成功")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_tools_v2.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.tools'`

- [ ] **Step 3: Implement `tools/schemas.py` and `tools/tools.py`**

- `tools/schemas.py`: Define JSON Schema objects for `pw_page`, `pw_interact`, and `pw_media`.
- `tools/tools.py`: Implement the 3 `FunctionTool` classes with `@dataclass`, wrapping `asyncio.wait_for(..., timeout=self.timeout_seconds)` to catch `asyncio.TimeoutError` and return `"操作超时：执行超过 {timeout} 秒限制，已强制终止。"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_tools_v2.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/schemas.py tools/tools.py tests/test_tools_v2.py
git commit -m "feat(tools): add PwPageTool, PwInteractTool, PwMediaTool with timeout protection"
```

---

### Task 6: 插件入口重构、提示词注入与配置扩展 (`_conf_schema.json`, `main.py`)

**Files:**
- Modify: `_conf_schema.json`
- Modify: `main.py`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: AstrBot `context.add_llm_tools`, `@filter.on_llm_request()`, `ProviderRequest`
- Produces: Updated `PlaywrightToolPlugin` registering the 3 `FunctionTool` classes and injecting system prompt.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_plugin_main.py
def test_conf_schema_v2_fields(self):
    with open("_conf_schema.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    self.assertIn("tool_execution_timeout_seconds", data)
    self.assertIn("screenshot_max_height_px", data)
    self.assertIn("screenshot_timeout_seconds", data)
    self.assertIn("system_prompt_injection", data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_plugin_main.py`
Expected: FAIL with `AssertionError: 'tool_execution_timeout_seconds' not found in data`

- [ ] **Step 3: Implement `_conf_schema.json` and `main.py`**

- Update `_conf_schema.json` with new configuration options.
- Update `main.py`: Instantiate `PwPageTool`, `PwInteractTool`, `PwMediaTool` and register via `self.context.add_llm_tools(...)`. Remove legacy `@filter.llm_tool` methods. Add `@filter.on_llm_request()` hook injecting `self.system_prompt_injection` when non-empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_plugin_main.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json main.py tests/test_plugin_main.py
git commit -m "feat(plugin): wire v2 tools registration and system prompt injection"
```

---

### Task 7: 补全文档与全量端到端验证 (`docs/README.md`, `docs/ARCHITECTURE.md`)

**Files:**
- Create: `docs/README.md`
- Create: `docs/ARCHITECTURE.md`
- Modify: `README.md`
- Test: Full test suite in `tests/`

- [ ] **Step 1: Write comprehensive project documentation in `docs/` according to `AGENT.md`**

Concise, succinct, structured guide for users and developers:
- `docs/README.md`: User manual with commands, tool schema, config descriptions, examples.
- `docs/ARCHITECTURE.md`: Architecture diagrams and layer explanations (`adapts`, `core`, `tools/handlers`, `tools/tools`).

- [ ] **Step 2: Run full test suite across the entire project**

Run: `python -m unittest discover -s tests -p "test_*.py"`
Expected: ALL TESTS PASS

- [ ] **Step 3: Verify all 5 Review Focus items are covered by unit tests**

Check:
1. Unknown action handling -> `test_tools_v2.py::test_invalid_action_rejected`
2. Tool timeout -> `test_tools_v2.py`
3. Screenshot height clipping & timeout -> `test_media_handler.py::test_screenshot_full_height_clipped`
4. Drag missing target -> `test_interact_handler.py::test_drag_element_missing_target`
5. Prompt injection toggle -> `test_plugin_main.py`

- [ ] **Step 4: Commit all milestone changes**

```bash
git add docs/ README.md
git commit -m "docs: complete v2 documentation and verify full test suite"
```
