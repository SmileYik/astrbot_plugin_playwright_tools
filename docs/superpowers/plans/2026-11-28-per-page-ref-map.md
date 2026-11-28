# 按页面隔离 Ref ID 映射与跨标签页自动寻址实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `ref_map` 与页面快照状态从上下文全局下沉至每个 `Page` 独立维护，统一 `MarkdownReader` 与 `AriaReader` 的全局单调递增 `ref_id` 映射，并支持不调用 `switch_tab` 直接通过 `ref_id` 自动切换并操作对应标签页。

**Architecture:** 在 `BrowserSessionContext` 中以 `id(page)` 为键维护 `PageState` 字典（不保留旧的全局 `ctx.ref_map` 兼容代理），并在 `BaseActionHandler.execute_action` 中于权限校验前统一通过 `ctx.resolve_ref` 反查目标标签页并激活。`AriaReader` 利用 `start_ref` 将原生 `aria-ref` 重映射为全局单调递增数字编号并在 `ref_map` 中保留 `aria_ref` 字段供 Locator 构造。

**Tech Stack:** Python 3.12, Playwright (async_api), unittest

**Spec:** `docs/superpowers/specs/2026-11-28-per-page-ref-map-design.md`

## Global Constraints

- 所有工具必须统一维护 `_actions` 字典分发，执行必须包含全局超时保护。
- 日志记录严禁使用 `import logging`，仅能使用 `from astrbot.api import logger`；异常时完整记录 traceback。
- 不保留旧的全局 `ctx.ref_map` / `ctx.current_snapshot` / `ctx.is_snapshot_dirty` 兼容代理；同步更新相关测试与文档。
- 每次修改 `tools/`、`core/`、`adapts/` 后必须运行 `.venv/bin/python -m unittest discover tests` 保证 100% 通过。

## Review Focus

- `AriaReader` 重映射 `ref_id` 后，图片 `img` 向父级 `link` 回填 `src`/`alt` 的 `parent_map` 逻辑仍能正确命中映射后的 `global_ref`。
- `AriaReader` 中无障碍名称为 URL 的超链接化简与 `[ref=...]` 替换不破坏缩进、正则匹配或 YAML 分块。
- 后台标签页触发 `framenavigated` 时，仅重置该后台标签页的 `PageState`，不污染当前活动标签页的 `ref_map`。
- 当前活动标签页触发 `close` 事件时，`remove_page_state` 清理其状态并将 `current_page` 安全回退至剩余存活标签页。
- `drag_and_drop(ref, target_ref)` 当 `ref` 与 `target_ref` 分属不同标签页时返回明确失败提示。

---

### Task 1: `PageState`、`BrowserSessionContext` 按页状态管理及 `NavigationGuard` 关闭回调

**Files:**
- Modify: `core/context_manager.py`
- Modify: `core/navigation_guard.py`
- Test: `tests/test_context_manager.py`
- Test: `tests/test_navigation_guard.py`

**Interfaces:**
- Produces:
  - `PageState(ref_map: dict[str, dict], current_snapshot: Any = None, is_snapshot_dirty: bool = False)` in `core/context_manager.py`
  - `BrowserSessionContext.get_page_state(self, page: Page | None = None) -> PageState`
  - `BrowserSessionContext.clear_page_state(self, page: Page | None, reset_snapshot: bool = True) -> None`
  - `BrowserSessionContext.remove_page_state(self, page: Page | None) -> None`
  - `BrowserSessionContext.resolve_ref(self, ref: str | int) -> tuple[Page | None, dict | None]`
  - `async BrowserSessionContext.activate_page(self, page: Page) -> None`
  - `NavigationGuard.attach(..., on_page_closed: Callable[[Any], None] | None = None)`

- [ ] **Step 1: Write failing tests in `tests/test_context_manager.py` and `tests/test_navigation_guard.py`**

在 `tests/test_context_manager.py` 增加测试：
- `test_per_page_state_isolation_and_resolve_ref`：验证两个标签页各自持有独立 `PageState.ref_map`，在当前页为 `page2` 时调用 `ctx.resolve_ref("1")` 能返回 `(page1, el_info)`，调用 `await ctx.activate_page(page1)` 后 `ctx.current_page is page1`。
- `test_remove_page_state_fallback_current_page`：关闭 `current_page` 后 `page_states` 中对应条目被清理，且 `ctx.current_page` 回退至剩余存活标签页。

在 `tests/test_navigation_guard.py` 增加测试：
- `test_on_page_closed_callback_invoked`：触发页面 `close` 事件时调用 `on_page_closed(page)`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_context_manager tests.test_navigation_guard -v`
Expected: FAIL (`PageState` / `resolve_ref` / `on_page_closed` 未定义)

- [ ] **Step 3: Implement `on_page_closed` in `core/navigation_guard.py`**

在 `NavigationGuard._setup_page_listeners` 和 `NavigationGuard.attach` 增加 `on_page_closed: Callable[[Any], None] | None = None` 参数，在 `_on_close` 中调用 `on_page_closed(page)`。

- [ ] **Step 4: Implement `PageState` and per-page methods in `core/context_manager.py`**

- 新增 `PageState` dataclass。
- 将 `BrowserSessionContext` 的全局 `ref_map`、`current_snapshot`、`is_snapshot_dirty` 替换为 `page_states: dict[int, PageState]`。
- 实现 `get_page_state`、`clear_page_state`、`remove_page_state`、`resolve_ref`、`activate_page`（同步更新 `current_page` 与 `pages`，并安全尝试 `page.bring_to_front()`）。
- 在 `_create_new_context` 中：`_on_main_frame_nav(page)` 仅调用 `ctx.clear_page_state(page, reset_snapshot=True)` 并设置 `ctx.get_page_state(page).is_snapshot_dirty = True`；向 `nav_guard.attach` 传入 `on_page_closed=ctx.remove_page_state`。

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_context_manager tests.test_navigation_guard -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/context_manager.py core/navigation_guard.py tests/test_context_manager.py tests/test_navigation_guard.py
git commit -m "refactor(core): isolate ref_map and snapshot state per page"
```

---

### Task 2: `AriaReader` 全局单调递增 `ref_id` 映射

**Files:**
- Modify: `core/readers/aria_reader.py`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: `start_ref: int = 1` in `AriaReader.extract_snapshot(self, page: Any, url: str = "", start_ref: int = 1, **kwargs) -> PageSnapshot`
- Produces: `PageSnapshot` where `ref_map` keys are monotonic strings starting at `start_ref` (rolling over `1_000_000` -> `1`), each entry contains `"ref": global_ref` and `"aria_ref": raw_aria_ref`, and `raw_content`/`chunks` render `[ref=<global_ref>]`.

- [ ] **Step 1: Write failing tests in `tests/test_readers.py`**

增加测试：
- `test_aria_reader_monotonic_ref_mapping`：传入 `start_ref=50`，验证解析 `e1`、`e2` 后输出文本包含 `[ref=50]`、`[ref=51]`，`snapshot.ref_map["50"]["aria_ref"] == "e1"`、`snapshot.allocated_count == 2`。
- `test_aria_reader_img_parent_link_with_remapped_refs`：验证包含 `link -> img` 的 ARIA 树在 `start_ref=10` 重映射后，图片 `src` 与 `alt` 仍正确回填到父级 `link` 的映射后 `ref_id`。
- `test_aria_reader_ref_rollover`：传入 `start_ref=999_999` 且有 3 个元素，验证编号依次为 `"999999"`、`"1000000"`? 需与 `allocate_ref_id` 一致：达到 `1_000_000` 时下一编号回滚为 `"1"`（即 `999999 -> 1000000 -> 1` 或 `999999 -> 1 -> 2` 与 `allocate_ref_id` 保持一致）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_readers -v`
Expected: FAIL (仍返回 `e1`, `e2`)

- [ ] **Step 3: Implement monotonic `ref_id` mapping in `core/readers/aria_reader.py`**

- 在 `extract_snapshot` 中依据 `start_ref` 为 `_parse_aria_yaml` 提取出的每个 `raw_ref` 分配单调递增数字字符串 `global_ref`（与 `BrowserSessionContext.allocate_ref_id` 保持一致的 `1_000_000` 回滚规则）。
- 在 `ref_map[global_ref]` 中写入 `"ref": global_ref` 与 `"aria_ref": raw_ref`。
- 使用 `raw_ref` 调用 `_fetch_element_src(page, raw_ref)`，并将 `parent_map` 映射后的父子关系用于回填 `src`/`alt`。
- 将 `cleaned_yaml` 中的 `[ref=<raw_ref>]` 替换为 `[ref=<global_ref>]` 后生成 `chunks`。
- 更新 `get_tool_metadata()` 中 `ref` 示例为 `'1', '2'`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_readers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/readers/aria_reader.py tests/test_readers.py
git commit -m "refactor(readers): remap AriaReader refs to global monotonic IDs"
```

---

### Task 3: `BaseActionHandler` 跨标签页 `ref` 寻址、自动激活与密码探测

**Files:**
- Modify: `tools/handlers/base_handler.py`
- Test: `tests/test_base_handler.py`

**Interfaces:**
- Consumes: `ctx.resolve_ref`, `ctx.activate_page`, `ctx.get_page_state`
- Produces: `BaseActionHandler.execute_action` resolves `ref` in `input_args` before permission checking, activates `target_page` if different from `ctx.current_page`, runs password detection & `action_coro_fn(ctx, target_page)` on `target_page`.

- [ ] **Step 1: Write failing tests in `tests/test_base_handler.py`**

增加测试：
- `test_execute_action_resolves_ref_across_tabs_and_activates_page`：构造两个标签页 `page1`、`page2`，`ctx.current_page = page2`，`page1` 的 `PageState.ref_map` 含有 `"5"`。调用 `execute_action(..., input_args={"ref": "5"}, ...)`，验证 `ctx.current_page` 切换为 `page1`，且传给 `action_coro_fn` 的 `page` 为 `page1`、权限校验使用的 `current_url` 为 `page1.url`。
- `test_execute_action_password_detection_with_aria_ref`：验证 `el_info` 含 `"aria_ref": "e3"` 时，回退探测构造 `page.locator("aria-ref=e3")` 并正确脱敏。

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_base_handler -v`
Expected: FAIL

- [ ] **Step 3: Update `BaseActionHandler.execute_action` in `tools/handlers/base_handler.py`**

- 若 `clean_ref_str` 非空且 `ctx` 具备 `resolve_ref`，先调用 `target_page, el_info = ctx.resolve_ref(clean_ref_str)`；若命中 `target_page` 且 `target_page is not page`，调用 `await ctx.activate_page(target_page)` 并更新局部变量 `page = target_page` 及 `current_url = target_resource or getattr(page, "url", "")`。
- 密码探测优先使用 `el_info`，回退 `locator` 探测时优先依据 `el_info.get("aria_ref")` 构造 `aria-ref=...`，否则使用 `[data-astr-ref="..."]`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_base_handler -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/base_handler.py tests/test_base_handler.py
git commit -m "refactor(handlers): resolve cross-tab ref and activate target page in BaseActionHandler"
```

---

### Task 4: `PageHandler`、`InteractHandler`、`MediaHandler` 适配每页 `PageState` 与 `aria_ref` Locator

**Files:**
- Modify: `tools/handlers/page_handler.py`
- Modify: `tools/handlers/interact_handler.py`
- Modify: `tools/handlers/media_handler.py`
- Test: `tests/test_page_handler.py`
- Test: `tests/test_interact_handler.py`
- Test: `tests/test_media_handler.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `ctx.get_page_state(page)`, `ctx.clear_page_state(page)`, `ctx.resolve_ref(ref)`, `ctx.activate_page(page)`

- [ ] **Step 1: Update and add tests in `tests/test_page_handler.py`, `tests/test_interact_handler.py`, `tests/test_media_handler.py`, `tests/test_tools.py`**

- 更新原有直接读写 `ctx.ref_map` / `ctx.current_snapshot` 的测试断言为 `ctx.get_page_state(page)`。
- 新增多标签页端到端单测：
  - `test_switch_tab_preserves_page_states`：切换标签页后原标签页 `ref_map` 与 `current_snapshot` 保留。
  - `test_click_page1_ref_while_on_page2_switches_active_page`：标签页 1 读取、打开并读取标签页 2 后，不调用 `switch_tab` 直接 `click(ref="1")`，操作落在 `page1` 且 `ctx.current_page` 变为 `page1`。
  - `test_drag_and_drop_cross_tab_target_ref_rejected`：`ref` 在标签页 1、`target_ref` 在标签页 2 时返回失败提示。
  - `test_aria_ref_locator_used_for_remapped_ref`：`ref_map["12"]["aria_ref"] == "e2"` 时，Locator 使用 `aria-ref=e2`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_page_handler tests.test_interact_handler tests.test_media_handler tests.test_tools -v`
Expected: FAIL

- [ ] **Step 3: Update `page_handler.py`, `interact_handler.py`, `media_handler.py`**

- `page_handler.py`:
  - `open_url`：调用 `ctx.clear_page_state(page, reset_snapshot=True)` 并标记 `is_snapshot_dirty = True`。
  - `read_page`：读写 `ctx.get_page_state(cur_page)`；当传入 `clean_ref` 查询详情时，通过 `ctx.resolve_ref(clean_ref)` 查找到对应页与 `el_info`（若来自其他页则激活）。
  - `switch_tab`：调用 `await ctx.activate_page(pages[tab_index - 1])`，**不再清空** `ref_map` 和 `current_snapshot`。
- `interact_handler.py`:
  - 新增 `_resolve_page_ref(ctx, page, ref) -> tuple[dict | None, str | None]` 与 `_get_locator(page, ref, el_info=None)` 辅助方法（`el_info` 含 `aria_ref` 时使用 `aria-ref={aria_ref}`，否则 `[data-astr-ref="{ref_str}"]`）。
  - 操作后仅设置 `ctx.get_page_state(page).is_snapshot_dirty = True`。
  - `drag_and_drop` 校验 `target_ref` 必须在当前解析出的 `page` 的 `PageState.ref_map` 中。
- `media_handler.py`:
  - `download` 使用 `ctx.get_page_state(page).ref_map` 验证 `ref`，并依据 `el_info.get("aria_ref")` 构造 Locator。

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_page_handler tests.test_interact_handler tests.test_media_handler tests.test_tools -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/page_handler.py tools/handlers/interact_handler.py tools/handlers/media_handler.py tests/test_page_handler.py tests/test_interact_handler.py tests/test_media_handler.py tests/test_tools.py
git commit -m "refactor(handlers): migrate handlers to per-page PageState and aria_ref locators"
```

---

### Task 5: 更新架构文档、SKILL、Changelog 并运行全量测试

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Modify: `skills/playwright-tool/SKILL.md`

- [ ] **Step 1: Update documentation**

- `docs/ARCHITECTURE.md`：更新 `BrowserSessionContext` 按页面维护 `PageState`、`AriaReader` 全局单调 `ref_id` 重映射以及跨标签页 `ref_id` 自动寻址激活机制说明。
- `skills/playwright-tool/SKILL.md`：精简补充说明跨标签页时旧页面 `ref_id` 依然有效，可直接传入原 `ref_id` 操作并自动切回对应标签页。
- `CHANGELOG.md`：记录本次多标签页 `ref_map` 隔离与自动寻址变更。

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/python -m unittest discover tests`
Expected: All tests PASS (100% pass rate)

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md CHANGELOG.md skills/playwright-tool/SKILL.md
git commit -m "docs: document per-page ref_map isolation and cross-tab ref resolution"
```
