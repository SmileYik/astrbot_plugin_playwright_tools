# Playwright Tools Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 AstrBot 自动化浏览器工具插件（astrbot_plugin_playwright_tools），为大模型提供基于 Ref ID 标记与分页的网页浏览交互能力，包含个人/会话上下文隔离、域名与操作白名单守卫、SQLite 审计及 Camoufox 适配器。

**Architecture:** 采用分层服务架构：`adapts/` 封装底层 Playwright/Camoufox 启动与上下文实例化；`core/` 负责多租户上下文隔离路由、域名白名单导航守卫、DOM 精简与 Ref ID 分页及 SQLite 异步审计；`tools/` 暴露给大模型简洁的原子化工具；`main.py` 完成 AstrBot 插件生命周期与指令注册。

**Tech Stack:** Python 3.10+, Playwright, Camoufox, SQLite3, AstrBot Plugin API, unittest

**Spec:** `docs/superpowers/specs/2026-11-19-playwright-tools-design.md`

## Global Constraints

- **代码与注释风格**：严格遵循 `AGENT.md`，文档、注释及返回给 AI 的提示必须做到凝练简洁，不啰嗦。
- **架构哲学**：坚持 Simplicity First，杜绝过渡抽象与投机性特性；坚持 Surgical Changes 与 Goal-Driven 开发。
- **版本与元数据**：`metadata.yaml` 与 `main.py` 中的版本号、描述与作者信息保持同步更新。
- **零凭证泄露**：严禁向大模型返回或暴露任何 Cookie、StorageState 或敏感鉴权数据。
- **零 HTML 倾倒**：严禁将原始网页 HTML 塞给大模型，必须通过 DOM 精简抽取与 Ref ID 编号过滤。

## Review Focus

1. **复杂 URL / 端口与通配符匹配**：形如 `https://sub.domain.com:8443/api?x=1` 命中 `*.domain.com` 且拒绝非 http(s) 协议（如 `javascript:` 或 `file://`）。
2. **页面重定向后的 Ref ID 失效处理**：页面发生跳转后调用旧 Ref ID，必须返回明确的元素过期/页面重载提示，而非抛出未捕获异常。
3. **禁用向 AI 发送截图时的拦截保护**：当 `allow_screenshot_to_ai=False` 且工具收到 `target="ai"` 时，必须直接拒绝并返回明确原因。
4. **子资源放行与顶级导航守卫隔离**：白名单页面加载外部 CDN 脚本/样式不被拦截，但点击链接导致顶层页面跳转至未授权外部域名时必须被实时阻断。
5. **个人模式未受邀用户的权限阻断**：群聊非创建者且未受邀用户调用浏览器工具，必须直接返回无权操作提示，不得越权或隐式新建实例。

---

### Task 1: SQLite 审计系统 (AuditLogger)

**Files:**
- Create: `core/audit_logger.py`
- Test: `tests/test_audit_logger.py`

**Interfaces:**
- Consumes: Standard library `sqlite3`, `pathlib.Path`, `datetime`
- Produces: `AuditLogger(db_path: str = "data/audit.db")`
  - `async def log_action(session_id: str, context_key: str, sender_id: str, tool_name: str, url: str, input_args: dict, output_result: str, is_permitted: bool, deny_reason: str = "", is_error: bool = False, error_message: str = "") -> None`
  - `async def cleanup_expired(retention_days: int) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit_logger.py
import unittest
import tempfile
import os
import asyncio
from core.audit_logger import AuditLogger

class TestAuditLogger(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_audit.db")
        self.logger = AuditLogger(self.db_path)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_log_action_and_query(self):
        await self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="click", url="https://example.com",
            input_args={"ref": 1}, output_result="ok",
            is_permitted=True
        )
        count = await self.logger.get_count()
        self.assertEqual(count, 1)

    async def test_cleanup_expired(self):
        await self.logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="read", url="https://example.com",
            input_args={}, output_result="ok", is_permitted=True,
            custom_timestamp="2020-01-01 00:00:00"
        )
        cleaned = await self.logger.cleanup_expired(retention_days=30)
        self.assertEqual(cleaned, 1)
        count = await self.logger.get_count()
        self.assertEqual(count, 0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_audit_logger.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core'`

- [ ] **Step 3: Implement `AuditLogger` in `core/audit_logger.py`**

Implement SQLite connection, auto-create table `tool_audit_logs`, async write via `asyncio.to_thread` or standard lock to keep it simple and thread-safe.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_audit_logger.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/audit_logger.py tests/test_audit_logger.py
git commit -m "feat(audit): implement SQLite AuditLogger with retention cleanup"
```

---

### Task 2: 权限与白名单守卫 (SecurityManager)

**Files:**
- Create: `core/security_manager.py`
- Test: `tests/test_security_manager.py`

**Interfaces:**
- Consumes: Standard library `fnmatch`, `urllib.parse`
- Produces: `SecurityManager(admin_only: bool, admin_uids: list[str], whitelist_rules: list[dict], admin_bypass: bool = True)`
  - `def is_admin(user_id: str) -> bool`
  - `def check_permission(user_id: str, url: str, action: str) -> tuple[bool, str]`
  - `def is_url_allowed_navigation(user_id: str, target_url: str) -> tuple[bool, str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_security_manager.py
import unittest
from core.security_manager import SecurityManager

class TestSecurityManager(unittest.TestCase):
    def setUp(self):
        rules = [
            {"domain": "*.github.com", "allowed_actions": ["read", "click", "scroll"]},
            {"domain": "example.com", "allowed_actions": ["read", "click", "fill", "screenshot"]}
        ]
        self.sec = SecurityManager(
            admin_only=False,
            admin_uids=["admin_1"],
            whitelist_rules=rules,
            admin_bypass=True
        )

    def test_admin_bypass(self):
        allowed, reason = self.sec.check_permission("admin_1", "https://danger.com", "fill")
        self.assertTrue(allowed)

    def test_whitelist_domain_matching_and_actions(self):
        # Allowed action on wildcard subdomain
        allowed, _ = self.sec.check_permission("user_1", "https://gist.github.com/test", "read")
        self.assertTrue(allowed)

        # Denied action on allowed domain
        allowed, reason = self.sec.check_permission("user_1", "https://gist.github.com/test", "fill")
        self.assertFalse(allowed)
        self.assertIn("fill", reason)

        # Disallowed domain
        allowed, reason = self.sec.check_permission("user_1", "https://bilibili.com", "read")
        self.assertFalse(allowed)

    def test_navigation_security_non_http(self):
        allowed, reason = self.sec.is_url_allowed_navigation("user_1", "javascript:alert(1)")
        self.assertFalse(allowed)

    def test_admin_only_mode(self):
        sec_admin_only = SecurityManager(admin_only=True, admin_uids=["admin_1"], whitelist_rules=[])
        allowed, _ = sec_admin_only.check_permission("admin_1", "https://anything.com", "read")
        self.assertTrue(allowed)
        allowed, _ = sec_admin_only.check_permission("user_1", "https://anything.com", "read")
        self.assertFalse(allowed)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_security_manager.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.security_manager'`

- [ ] **Step 3: Implement `SecurityManager` in `core/security_manager.py`**

Parse URLs with `urllib.parse`, validate scheme in `{"http", "https"}`, match hostnames using lowercase `fnmatch.fnmatch`, inspect `allowed_actions`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_security_manager.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/security_manager.py tests/test_security_manager.py
git commit -m "feat(security): implement SecurityManager with wildcard domain rules and action check"
```

---

### Task 3: 页面精简抽取与 Ref ID 分页 (PageExtractor)

**Files:**
- Create: `core/page_extractor.py`
- Test: `tests/test_page_extractor.py`

**Interfaces:**
- Consumes: Standard library `dataclasses`, `re`, `json`
- Produces: `PageExtractor(max_page_char_length: int = 2500)`
  - `def extract_snapshot(page_title: str, url: str, raw_elements: list[dict], text_blocks: list[str]) -> tuple[str, dict[int, dict]]`
  - `def format_page_chunk(snapshot_text: str, page_index: int) -> str`
  - `def get_js_extractor_script() -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_page_extractor.py
import unittest
from core.page_extractor import PageExtractor

class TestPageExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = PageExtractor(max_page_char_length=200)

    def test_extract_and_format_elements(self):
        elements = [
            {"tag": "input", "type": "text", "name": "kw", "placeholder": "search", "text": ""},
            {"tag": "button", "type": "submit", "name": "", "placeholder": "", "text": "Search Now"}
        ]
        text_blocks = ["Welcome to Search Engine"]
        text, ref_map = self.extractor.extract_snapshot("Search Home", "https://s.com", elements, text_blocks)
        
        self.assertIn("[1] [输入框]", text)
        self.assertIn("[2] [按钮] \"Search Now\"", text)
        self.assertEqual(len(ref_map), 2)
        self.assertEqual(ref_map[1]["tag"], "input")

    def test_pagination_when_length_exceeded(self):
        long_blocks = ["Paragraph " + str(i) * 50 for i in range(10)]
        text, _ = self.extractor.extract_snapshot("Big Page", "https://big.com", [], long_blocks)
        formatted = self.extractor.format_page_chunk(text, page_index=1)
        self.assertIn("分页: 1/", formatted)
        self.assertIn("read_page(page=2)", formatted)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_page_extractor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.page_extractor'`

- [ ] **Step 3: Implement `PageExtractor` in `core/page_extractor.py`**

Provide compact element rendering, sequential Ref ID indexing, pagination string slicing, and the companion lightweight client-side JavaScript snippet to traverse DOM and extract visible interactive nodes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_page_extractor.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/page_extractor.py tests/test_page_extractor.py
git commit -m "feat(extractor): implement PageExtractor with Ref ID mapping and chunk pagination"
```

---

### Task 4: 浏览器适配器抽象与 Camoufox 适配器 (BrowserAdapter)

**Files:**
- Create: `adapts/base.py`
- Create: `adapts/camoufox_adapter.py`
- Test: `tests/test_browser_adapter.py`

**Interfaces:**
- Consumes: Playwright / Camoufox async API
- Produces: `BrowserAdapterBase(ABC)` & `CamoufoxAdapter(BrowserAdapterBase)`
  - `async def start() -> None`
  - `async def stop() -> None`
  - `async def create_context(storage_state_path: str | None = None) -> Any`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_browser_adapter.py
import unittest
from unittest.mock import AsyncMock, patch
from adapts.base import BrowserAdapterBase
from adapts.camoufox_adapter import CamoufoxAdapter

class TestBrowserAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_interface(self):
        adapter = CamoufoxAdapter(headless=True)
        self.assertIsInstance(adapter, BrowserAdapterBase)

    @patch("adapts.camoufox_adapter.AsyncCamoufox")
    async def test_start_and_create_context(self, mock_camoufox):
        mock_instance = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        mock_instance.__aenter__.return_value = mock_browser
        mock_camoufox.return_value = mock_instance

        adapter = CamoufoxAdapter(headless=True)
        await adapter.start()
        ctx = await adapter.create_context(storage_state_path="test_state.json")
        self.assertIsNotNone(ctx)
        await adapter.stop()

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_browser_adapter.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapts.base'`

- [ ] **Step 3: Implement `adapts/base.py` and `adapts/camoufox_adapter.py`**

Define `BrowserAdapterBase` abstract class with async lifecycle methods. Implement `CamoufoxAdapter` with lazy import of `camoufox` / standard Playwright fallback if camoufox is not yet installed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_browser_adapter.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapts/base.py adapts/camoufox_adapter.py tests/test_browser_adapter.py
git commit -m "feat(adapter): add BrowserAdapterBase and CamoufoxAdapter implementation"
```

---

### Task 5: 上下文管理器与多租户路由 (ContextManager)

**Files:**
- Create: `core/context_manager.py`
- Test: `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `adapts.base.BrowserAdapterBase`, `core.security_manager.SecurityManager`
- Produces: `BrowserSessionContext(dataclass)` & `ContextManager`
  - `def __init__(adapter: BrowserAdapterBase, security: SecurityManager, mode: str = "personal", idle_timeout_minutes: int = 10, storage_state_path: str = "")`
  - `async def resolve_context(session_id: str, sender_id: str) -> tuple[BrowserSessionContext | None, str]`
  - `def invite_user(session_id: str, owner_id: str, target_user_id: str) -> tuple[bool, str]`
  - `def switch_user_context(session_id: str, sender_id: str, target_owner_id: str) -> tuple[bool, str]`
  - `async def close_user_context(session_id: str, sender_id: str) -> tuple[bool, str]`
  - `async def cleanup_idle_contexts() -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context_manager.py
import unittest
from unittest.mock import AsyncMock
from core.context_manager import ContextManager
from core.security_manager import SecurityManager

class TestContextManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_adapter = AsyncMock()
        self.mock_ctx = AsyncMock()
        self.mock_page = AsyncMock()
        self.mock_ctx.new_page.return_value = self.mock_page
        self.mock_adapter.create_context.return_value = self.mock_ctx
        self.security = SecurityManager(admin_only=False, admin_uids=["admin_1"], whitelist_rules=[])
        self.mgr = ContextManager(
            adapter=self.mock_adapter,
            security=self.security,
            mode="personal",
            idle_timeout_minutes=10
        )

    async def test_personal_mode_isolation_and_invite(self):
        ctx_a, msg = await self.mgr.resolve_context(session_id="s1", sender_id="user_a")
        self.assertIsNotNone(ctx_a)
        self.assertEqual(ctx_a.owner_id, "user_a")

        # user_b tries to access before invitation
        ctx_b, msg_b = await self.mgr.resolve_context(session_id="s1", sender_id="user_b")
        # Should not have access to user_a context
        self.assertNotEqual(ctx_b.owner_id, "user_a")

        # user_a invites user_b
        ok, _ = self.mgr.invite_user(session_id="s1", owner_id="user_a", target_user_id="user_b")
        self.assertTrue(ok)

        # user_b now routes to user_a's context if user_b has no personal context
        await self.mgr.close_user_context(session_id="s1", sender_id="user_b")
        ctx_resolved, _ = self.mgr.resolve_context(session_id="s1", sender_id="user_b")
        self.assertEqual(ctx_resolved.owner_id, "user_a")

    async def test_close_context(self):
        await self.mgr.resolve_context(session_id="s1", sender_id="user_a")
        ok, _ = await self.mgr.close_user_context(session_id="s1", sender_id="user_a")
        self.assertTrue(ok)
        self.mock_ctx.close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_context_manager.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.context_manager'`

- [ ] **Step 3: Implement `ContextManager` in `core/context_manager.py`**

Implement routing algorithm: check active pointer -> check own context -> check invited contexts (latest active) -> lazy-create own context. Add idle timer tracking. Enforce storage_state injection only when `security.is_admin(owner_id)` is true.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_context_manager.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/context_manager.py tests/test_context_manager.py
git commit -m "feat(context): implement ContextManager with personal/session isolation and invite routing"
```

---

### Task 6: 大模型工具集实现 (Tools Suite)

**Files:**
- Create: `tools/browse_tools.py`
- Create: `tools/action_tools.py`
- Create: `tools/media_tools.py`
- Create: `tools/dialog_tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `core.context_manager.ContextManager`, `core.security_manager.SecurityManager`, `core.page_extractor.PageExtractor`, `core.audit_logger.AuditLogger`
- Produces: Tool functions with docstrings compatible with AstrBot tool discovery:
  - `open_url(url: str)`
  - `read_page(page: int = 1)`
  - `click(ref: int)`
  - `fill_form(ref: int, text: str)`
  - `select_option(ref: int, value: str)`
  - `scroll(direction: str = "down", amount: int = 500)`
  - `switch_tab(tab_index: int)`
  - `take_screenshot(target: str = "chat")`
  - `download_file(ref: int)`
  - `handle_dialog(action: str = "accept", prompt_text: str | None = None)`
  - `close_browser()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools.py
import unittest
from unittest.mock import AsyncMock, MagicMock
from tools.browse_tools import BrowseTools
from tools.media_tools import MediaTools

class TestTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_mgr = AsyncMock()
        self.mock_sec = MagicMock()
        self.mock_audit = AsyncMock()
        self.mock_extractor = MagicMock()
        self.browse_tools = BrowseTools(self.mock_mgr, self.mock_sec, self.mock_audit, self.mock_extractor)
        self.media_tools = MediaTools(self.mock_mgr, self.mock_sec, self.mock_audit, allow_screenshot_to_ai=False)

    async def test_screenshot_rejected_when_ai_target_disabled(self):
        res = await self.media_tools.take_screenshot(
            session_id="s1", sender_id="u1", target="ai"
        )
        self.assertIn("未开启将截图发送给大模型", res)

    async def test_navigation_guard_blocks_unauthorized_url(self):
        self.mock_sec.is_url_allowed_navigation.return_value = (False, "域名不在白名单中")
        res = await self.browse_tools.open_url(
            session_id="s1", sender_id="u1", url="https://forbidden.com"
        )
        self.assertIn("域名不在白名单中", res)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_tools.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.browse_tools'`

- [ ] **Step 3: Implement `tools/` modules**

Implement:
- `browse_tools.py`: URL opening, page reading with `PageExtractor`, tab switching, explicit browser close.
- `action_tools.py`: element lookup via `ref_map`, `click`, `fill_form`, `select_option`, `scroll`.
- `media_tools.py`: `take_screenshot` (with `allow_screenshot_to_ai` validation and chat delivery), `download_file` with `data/downloads/` storage.
- `dialog_tools.py`: `handle_dialog` configuration.
Attach AuditLogger calls to every tool execution.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_tools.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/*.py tests/test_tools.py
git commit -m "feat(tools): implement LLM tools suite with guard checks and audit logging"
```

---

### Task 7: 插件入口、指令系统与配置 (_conf_schema.json, main.py, metadata.yaml)

**Files:**
- Create: `_conf_schema.json`
- Modify: `main.py`
- Modify: `metadata.yaml`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: AstrBot `Star`, `filter`, `Context`, `AstrMessageEvent`, `AstrBotConfig`
- Produces: Complete AstrBot plugin class registering commands (`/browser invite`, `/browser use`, `/browser close`, `/browser status`) and injecting LLM tools.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plugin_main.py
import unittest
import json
from pathlib import Path

class TestPluginMain(unittest.TestCase):
    def test_conf_schema_valid_json(self):
        schema_path = Path("_conf_schema.json")
        self.assertTrue(schema_path.exists())
        with open(schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("admin_only", data)
        self.assertIn("allow_screenshot_to_ai", data)
        self.assertIn("whitelist_rules", data)

    def test_metadata_synced(self):
        import yaml
        with open("metadata.yaml", "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f)
        self.assertEqual(meta["name"], "astrbot_plugin_playwright_tools")
        self.assertEqual(meta["display_name"], "PlaywrightTool")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_plugin_main.py`
Expected: FAIL with `AssertionError: False is not true` (`_conf_schema.json` does not exist)

- [ ] **Step 3: Implement `_conf_schema.json`, `main.py`, and `metadata.yaml`**

- `_conf_schema.json`: config inputs for `admin_only`, `extra_admin_uids`, `context_mode`, `idle_timeout_minutes`, `allow_screenshot_to_ai`, `whitelist_rules`, `audit_retention_days`.
- `main.py`: Update plugin class to initialize `AuditLogger`, `SecurityManager`, `BrowserAdapter`, `ContextManager`, register tools via `context.add_llm_tools` or `@filter.llm_tool`, and implement commands `/browser invite`, `/browser use`, `/browser close`, `/browser status`.
- `metadata.yaml`: Ensure version is `v1.0.0` and description is concise.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_plugin_main.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json main.py metadata.yaml tests/test_plugin_main.py
git commit -m "feat(plugin): wire plugin entrypoint, config schema, commands, and tool registrations"
```

---

### Task 8: 全量端到端验证与文档同步 (End-to-End Verification & Docs)

**Files:**
- Modify: `docs/README.md` or create user guide
- Test: `tests/` full test suite

- [ ] **Step 1: Run full test suite to verify no regressions**

Run: `python -m unittest discover -s tests -p "test_*.py"`
Expected: ALL TESTS PASS

- [ ] **Step 2: Verify Review Focus items are covered by unit tests**

Check:
1. Complex URL & non-http scheme -> `test_security_manager.py`
2. Ref ID stale handling -> `test_tools.py`
3. Screenshot to AI disabled -> `test_tools.py`
4. Subresource vs top-level navigation -> `test_security_manager.py`
5. Non-invited user rejection -> `test_context_manager.py`

- [ ] **Step 3: Commit end-to-end milestone**

```bash
git add .
git commit -m "test(e2e): complete full test suite verification and user documentation"
```
