# 工具回复引导优化与标签页感知实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在工具回复中补齐鉴权失败时的当前页可执行操作指引、新增 `pw_page(action='list_tabs')` 查询所有已打开标签页及活动页，并在新开或切换标签页时自动向 AI 告知标签页状态。

**Architecture:** 在 `SecurityManager` 暴露 `get_allowed_actions` 供 `BaseActionHandler.execute_action` 汇总权限（含 `NavigationGuard` 单跳授权）并映射为具体 `pw_*` 工具指引；同时在 `BaseActionHandler.execute_action` 切面对比动作前后的存活标签页与活动页，自动附带新开/切换标签页提示；`PageHandler` 新增 `list_tabs` 并注册到 `pw_page` Schema 与 `_actions` 字典。

**Tech Stack:** Python 3.12, Playwright (async_api), unittest

**Spec:** `docs/superpowers/specs/2026-11-28-tool-reply-guidance-and-tabs-design.md`

## Global Constraints

- 所有工具必须统一维护 `_actions` 字典分发，执行必须包含全局超时保护。
- 日志记录严禁使用 `import logging`，仅能使用 `from astrbot.api import logger`；异常时完整记录 traceback。
- 不保留旧的兼容实现、旧测试与过时文档；同步更新 `skills/playwright-tool/SKILL.md`、`docs/ARCHITECTURE.md`、`CHANGELOG.md`。
- 每次修改 `tools/`、`core/`、`adapts/` 后必须运行 `.venv/bin/python -m unittest discover tests` 保证 100% 通过。

## Review Focus

- 当页面既不在白名单也不持有单跳授权（可执行动作集合为空）时，权限拒绝提示明确引导 AI 调用 `pw_page(action='list_tabs')` 或 `pw_page(action='open')`，而不是给出空列表。
- 单跳落地页仅被授予 `["read", "screenshot"]` 且 AI 尝试 `click` 被拒时，指引中仅列出 `pw_read()` 与 `pw_media(action='screenshot_viewport')` 等实际允许的操作，不泄露未授权操作。
- 点击触发弹窗新开标签页（`len(after_pages) > len(before_pages)`）时，即使 `action_coro_fn` 本身返回“已成功点击”，切面也自动附带新标签页打开及当前第 X/Y 页信息。
- `pw_page(action='switch_tab')` 与跨标签页 `ref` 自动激活切换活动页时，切面自动附带当前标签页位置与总数，且不与 `switch_tab` 自身文案重复啰嗦。
- `pw_page(action='list_tabs')` 在页面 `title()` 为协程或同步属性、或抛出异常时都能安全返回列表而不崩溃。

---

### Task 1: `SecurityManager.get_allowed_actions`

**Files:**
- Modify: `core/security_manager.py`
- Test: `tests/test_security_manager.py`

**Interfaces:**
- Produces:
  - `ALL_KNOWN_ACTIONS: set[str]` in `core/security_manager.py`
  - `SecurityManager.get_allowed_actions(self, user_id: str, url: str) -> set[str]`

- [ ] **Step 1: Write failing tests in `tests/test_security_manager.py`**

增加测试 `test_get_allowed_actions`：
- 命中白名单部分权限规则（如 `["read", "screenshot"]`）时返回 `{"read", "screenshot"}`。
- 未命中白名单或非 `http`/`https` 协议时返回 `set()`。
- `admin_bypass=True` 且为管理员时返回全部 `ALL_KNOWN_ACTIONS`。
- `admin_only=True` 且非管理员时返回 `set()`。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_security_manager -v`
Expected: FAIL (`get_allowed_actions` 未定义)

- [ ] **Step 3: Implement `ALL_KNOWN_ACTIONS` and `get_allowed_actions` in `core/security_manager.py`**

- 定义模块级常量 `ALL_KNOWN_ACTIONS = frozenset({"read", "click", "fill", "select", "hover", "focus", "drag", "press_key", "scroll", "screenshot", "download", "navigate"})`。
- 实现 `get_allowed_actions(self, user_id: str, url: str) -> set[str]`。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_security_manager -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/security_manager.py tests/test_security_manager.py
git commit -m "feat(security): add SecurityManager.get_allowed_actions"
```

---

### Task 2: `BaseActionHandler` 权限指引与标签页变更自动感知

**Files:**
- Modify: `tools/handlers/base_handler.py`
- Test: `tests/test_base_handler.py`

**Interfaces:**
- Consumes: `SecurityManager.get_allowed_actions(user_id, url)`
- Produces:
  - `ACTION_GUIDANCE_MAP: dict[str, str]` in `tools/handlers/base_handler.py`
  - `BaseActionHandler._format_allowed_actions_guidance(self, ctx, page, auth_user_id, current_url) -> str`
  - `BaseActionHandler._get_alive_pages(ctx) -> list[Any]`
  - `BaseActionHandler._format_tab_change_notice(...) -> str`

- [ ] **Step 1: Write failing tests in `tests/test_base_handler.py`**

增加测试：
- `test_permission_denied_lists_allowed_actions_guidance`：白名单仅允许 `["read", "screenshot"]` 时，尝试 `click` 被拒，返回包含 `"当前页面可执行操作"`、`"pw_read()"`、`"pw_media(action='screenshot_viewport')"` 且不包含 `"pw_interact"`。
- `test_permission_denied_single_hop_lists_hop_actions`：单跳落地页仅允许 `["read"]` 时，尝试 `click` 被拒，返回列出 `pw_read()`。
- `test_permission_denied_empty_actions_guides_list_tabs`：当前页没有任何可执行权限时，提示调用 `pw_page(action='list_tabs')` 或 `pw_page(action='open')`。
- `test_execute_action_notifies_when_new_tab_opened`：动作执行前 1 个标签页，执行中 `browser_context.pages` 新增第 2 个标签页并切换 `current_page` 后，返回结果包含新开标签页提示及 `2/2`、标题和 URL。
- `test_execute_action_notifies_when_active_tab_switched_by_ref`：执行前 `current_page` 为 `page2`，传入 `page1` 的 `ref` 自动激活 `page1` 后，返回结果包含切换至第 `1/2` 个标签页提示。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_base_handler -v`
Expected: FAIL

- [ ] **Step 3: Implement permission guidance and tab-change notice in `tools/handlers/base_handler.py`**

- 定义 `ACTION_GUIDANCE_MAP`（按固定展示顺序排列，映射内部权限动作到具体 `pw_*` 调用示例）。
- 实现 `_format_allowed_actions_guidance`，综合 `security_mgr.get_allowed_actions`（若 mock 未提供则安全回退空集）与 `navigation_guard._page_grants` 中的有效单跳授权；在 `execute_action` 鉴权失败返回处追加指引。
- 实现 `_get_alive_pages(ctx)`、`_safe_page_title(page)` 与 `_format_tab_change_notice(...)`：在 `execute_action` 执行前记录 `(before_page_ids, before_active_page)`，执行后对比 `(after_pages, after_active_page)`；若出现新开标签页或活动页变更（`action_name != "list_tabs"`），在返回字符串末尾追加标签页变更摘要。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_base_handler -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/base_handler.py tests/test_base_handler.py
git commit -m "feat(handlers): add allowed-actions guidance and tab-change notice in BaseActionHandler"
```

---

### Task 3: `PageHandler.list_tabs`、`open_url` 标签页信息与 `pw_page` 工具注册

**Files:**
- Modify: `tools/handlers/page_handler.py`
- Modify: `tools/schemas.py`
- Modify: `tools/tools.py`
- Test: `tests/test_page_handler.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_interact_handler.py`

**Interfaces:**
- Consumes: `BaseActionHandler._get_alive_pages`, `BaseActionHandler._safe_page_title`
- Produces:
  - `PageHandler.list_tabs(self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = "") -> str`
  - `PW_PAGE_SCHEMA["properties"]["action"]["enum"]` includes `"list_tabs"`
  - `PageTool._actions["list_tabs"]`

- [ ] **Step 1: Write failing tests in `tests/test_page_handler.py` and `tests/test_tools.py`**

在 `tests/test_page_handler.py` 增加/更新测试：
- `test_list_tabs_returns_active_and_all_tabs_with_titles_and_urls`：两个标签页时调用 `list_tabs`，验证输出包含当前活动标签页序号与总数、每个标签页的 `[当前活动]` 标记、标题与 URL。
- `test_list_tabs_handles_title_error_gracefully`：`page.title()` 抛异常时仍正常返回标签页列表。
- `test_open_url_includes_tab_position_and_total`：验证 `open_url` 返回中包含当前第 `1/1` 个标签页提示。

在 `tests/test_tools.py` 更新/增加测试：
- 更新 `pw_page` 支持的动作列表断言为 `["open", "switch_tab", "list_tabs", "dialog", "close"]`（或包含 `"list_tabs"`）。
- 增加 `test_page_tool_dispatch_list_tabs`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_page_handler tests.test_tools -v`
Expected: FAIL

- [ ] **Step 3: Implement `list_tabs` and update `open_url` / `switch_tab` / `schemas.py` / `tools.py`**

- `tools/handlers/page_handler.py`：
  - 新增 `list_tabs` 方法，调用 `self.execute_action(..., action_name="list_tabs", required_permission="", ...)`，列出所有存活标签页序号、活动标记、标题与 URL，并给出 `switch_tab` / `pw_read` 指引。
  - `open_url` 返回中附带当前标签页位置（如 `当前位于第 {idx}/{total} 个标签页`）。
  - `switch_tab` 保持简洁提示，避免与 `BaseActionHandler` 自动附加的标签页切换通知冲突重复。
- `tools/schemas.py`：在 `PW_PAGE_SCHEMA` 的 `action` enum 与 description 中加入 `list_tabs`。
- `tools/tools.py`：在 `PageTool._actions` 注册 `"list_tabs": self._action_list_tabs`，更新未知动作报错文案。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_page_handler tests.test_tools tests.test_interact_handler -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/page_handler.py tools/schemas.py tools/tools.py tests/test_page_handler.py tests/test_tools.py tests/test_interact_handler.py
git commit -m "feat(tools): add pw_page list_tabs action and tab-position feedback"
```

---

### Task 4: 更新 `skills/playwright-tool/SKILL.md`、`docs/ARCHITECTURE.md`、`CHANGELOG.md` 并运行全量测试

**Files:**
- Modify: `skills/playwright-tool/SKILL.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update documentation and SKILL**

- `skills/playwright-tool/SKILL.md`：
  - 在 `pw_page` 职责与步骤五中补充 `pw_page(action='list_tabs')` 用法，引导 AI 在不确定当前打开了多少标签页时先查看列表、复用已有标签页而非盲目 `open`。
  - 在“常见场景处理策略”中补充：收到新开/切换标签页提示时直接读取或交互；遇到操作权限受限时依据工具返回的 `[当前页面可执行操作: ...]` 调整下一步策略。
- `docs/ARCHITECTURE.md`：补充 `BaseActionHandler` 鉴权失败可执行操作指引与标签页变更自动感知、以及 `pw_page(action='list_tabs')` 说明。
- `CHANGELOG.md`：在 `## [Unreleased]` 下补充本次优化条目。

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/python -m unittest discover tests`
Expected: All tests PASS (100% pass rate)

- [ ] **Step 3: Commit**

```bash
git add skills/playwright-tool/SKILL.md docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: update SKILL, architecture, and changelog for reply guidance and list_tabs"
```
