# 白名单单跳放行权限、规则精确度优先与 ContextManager 解耦实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `whitelist_rules` 增加“单跳放行”及其落地页权限与重定向控制，升级 [`SecurityManager`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/security_manager.py) 为域名精确度优先匹配并移除旧字段兼容，同时将路由守卫与单跳状态管理解耦至独立的 `NavigationGuard`。

**Architecture:** [`SecurityManager`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/security_manager.py) 负责按域名精确度解析最优白名单规则与单跳策略；新建 [`NavigationGuard`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/navigation_guard.py) 接管 Playwright `route` 拦截、弹窗 `page` 与 `framenavigated` 监听及 `Page` 粒度 `SingleHopGrant` 状态；[`ContextManager`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/context_manager.py) 与 [`BaseHandler`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/tools/handlers/base_handler.py) 分别挂载和查询 `NavigationGuard`。

**Tech Stack:** Python 3.12, Playwright (`async_api`), `unittest` (`IsolatedAsyncioTestCase` / `TestCase`), JSON Schema (`_conf_schema.json`).

**Spec:** [2026-11-28-single-hop-whitelist-and-decoupling-design.md](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-28-single-hop-whitelist-and-decoupling-design.md)

## Global Constraints

- 严禁使用 `import logging`，仅能使用 `from astrbot.api import logger`。
- 移除旧版本单数 `domain` 字段兼容逻辑及对应兼容测试，统一使用 `domains` 列表。
- 仅运行单元测试验证：`python -m unittest discover tests`，保证 100% 通过；不使用端到端测试。
- 管理员（`admin_bypass`）全局放行逻辑与外部插件上下文（`is_external=True`）跳过路由守卫行为保持不变。
- `pw_page(open_url)` 仍严格受白名单约束，不享受单跳豁免。

## Review Focus

1. **单跳落地页与源页面 URL 失配**：单跳落地后目标页发生前端 `hash`/query 变化或 `framenavigated`，`SingleHopGrant.granted_url` 需同步更新（或按同源/当前落地 URL 校验），否则后续 `pw_read` 会被误拒。
2. **弹窗新标签页的 `opener` 异步时序**：`window.open` / `target="_blank"` 打开的新页面在首次 `_route_guard` 触发时可能 `page.url` 尚为 `about:blank`，需在 `browser_ctx.on("page")` 或 `await page.opener()` 中可靠定位来源页面。
3. **非导航子资源与 iframe 子帧误拦截**：页面内的图片、XHR、JS 或第三方 iframe 不应消耗或触发单跳放行判定，仅主帧顶层导航请求（`request.is_navigation_request()` 且为主帧）参与单跳控制。
4. **单跳页面内再次跳出与回到白名单**：单跳落地页本身无白名单规则时，其内部点击跳转必须被拦截；若单跳落地页点击链接回到白名单域名，则应清除 `SingleHopGrant` 并恢复正常白名单权限。
5. **`*.example.com` 与 `search.example.com` 规则顺序无关性**：无论配置列表中通配规则在前还是精确规则在前，`search.example.com` 都必须命中精确规则。

---

### Task 1: 更新配置模式 `_conf_schema.json` 与 Schema 测试

**Files:**
- Modify: `_conf_schema.json:31-81`
- Test: `tests/test_conf_schema.py:54-81`

**Interfaces:**
- Produces: `_conf_schema.json` 中 `whitelist_rules.templates.rule.items` 新增：
  - `allow_single_hop: bool = False`
  - `single_hop_allowed_actions: list[str] = ["read", "screenshot"]`（`condition: {"allow_single_hop": true}`）
  - `single_hop_follow_redirects: bool = True`（`condition: {"allow_single_hop": true}`）

- [ ] **Step 1: 在 `tests/test_conf_schema.py` 中编写新增配置字段的失败测试**

```python
        self.assertEqual(rule_items["allow_single_hop"]["type"], "bool")
        self.assertFalse(rule_items["allow_single_hop"]["default"])

        self.assertEqual(rule_items["single_hop_allowed_actions"]["type"], "list")
        self.assertEqual(
            rule_items["single_hop_allowed_actions"]["default"],
            ["read", "screenshot"],
        )
        self.assertEqual(
            rule_items["single_hop_allowed_actions"]["options"],
            rule_items["allowed_actions"]["options"],
        )
        self.assertEqual(
            rule_items["single_hop_allowed_actions"]["condition"],
            {"allow_single_hop": True},
        )

        self.assertEqual(rule_items["single_hop_follow_redirects"]["type"], "bool")
        self.assertTrue(rule_items["single_hop_follow_redirects"]["default"])
        self.assertEqual(
            rule_items["single_hop_follow_redirects"]["condition"],
            {"allow_single_hop": True},
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests/test_conf_schema.py -v`
Expected: FAIL with `KeyError: 'allow_single_hop'`.

- [ ] **Step 3: 更新 `_conf_schema.json`**

在 `security.items.whitelist_rules.templates.rule.items` 中添加 `allow_single_hop`、`single_hop_allowed_actions`（复用 `allowed_actions` 的 12 项 `options` 与 `labels`）和 `single_hop_follow_redirects`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m unittest tests/test_conf_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json tests/test_conf_schema.py
git commit -m "feat(config): add single-hop whitelist options to _conf_schema.json"
```

---

### Task 2: 升级 `SecurityManager` 精确度优先匹配并移除旧兼容逻辑

**Files:**
- Modify: `core/security_manager.py:50-125`
- Test: `tests/test_security_manager.py:15-104`

**Interfaces:**
- Consumes: Task 1 中的 `whitelist_rules` 规则字段 `domains`, `allowed_actions`, `allow_single_hop`, `single_hop_allowed_actions`, `single_hop_follow_redirects`。
- Produces (`SecurityManager`):
  - `get_matched_rule(self, url: str) -> dict | None`
  - `get_single_hop_policy(self, url: str) -> tuple[bool, set[str], bool]`
  - 仅支持 `domains` 列表（移除 `domain` 兼容）。

- [ ] **Step 1: 更新 `tests/test_security_manager.py`（移除兼容测试与 `"domain"` 固件，新增精确度与单跳策略测试）**

移除 `test_whitelist_rules_backward_compatibility_single_domain`，将 `setUp` 中的 `"domain"` 改为 `"domains": [...]`，并新增测试：
```python
    def test_most_specific_rule_wins_regardless_of_order(self):
        rules = [
            {
                "domains": ["*.example.com"],
                "allowed_actions": ["read"],
                "allow_single_hop": False,
            },
            {
                "domains": ["search.example.com"],
                "allowed_actions": ["read", "click"],
                "allow_single_hop": True,
                "single_hop_allowed_actions": ["read", "screenshot"],
                "single_hop_follow_redirects": True,
            },
        ]
        mgr = SecurityManager(admin_only=False, whitelist_rules=rules)
        ok_click, _ = mgr.check_permission("u1", "https://search.example.com/q", "click")
        self.assertTrue(ok_click)
        hop_ok, hop_actions, follow = mgr.get_single_hop_policy("https://search.example.com/q")
        self.assertTrue(hop_ok)
        self.assertEqual(hop_actions, {"read", "screenshot"})
        self.assertTrue(follow)

        # 其余子域名仍只有通配规则权限
        no_click, _ = mgr.check_permission("u1", "https://docs.example.com/a", "click")
        self.assertFalse(no_click)
        hop_sub, _, _ = mgr.get_single_hop_policy("https://docs.example.com/a")
        self.assertFalse(hop_sub)

        # 深度通配 *.sub.example.com 优先于 *.example.com
        rules_nested = [
            {"domains": ["*.example.com"], "allowed_actions": ["read"]},
            {"domains": ["*.sub.example.com"], "allowed_actions": ["read", "click"]},
        ]
        mgr_nested = SecurityManager(admin_only=False, whitelist_rules=rules_nested)
        ok_nested, _ = mgr_nested.check_permission("u1", "https://a.sub.example.com", "click")
        self.assertTrue(ok_nested)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests/test_security_manager.py -v`
Expected: FAIL (`AttributeError: 'SecurityManager' object has no attribute 'get_single_hop_policy'` 及 `test_most_specific_rule_wins_regardless_of_order` 失败)。

- [ ] **Step 3: 实现 `SecurityManager` 精确度评分匹配与单跳策略读取**

在 `core/security_manager.py` 中：
1. 移除 `_is_rule_match` 中的 `rule.get("domain")` 兼容分支，统一只读 `domains` 列表。
2. 实现 `_pattern_specificity(self, host: str, domain_pattern: str) -> tuple[int, int, int] | None`：
   - 精确匹配（不含 `*` 与 `?`）：`(3, len(norm_pat.split(".")), len(norm_pat))`。
   - 纯通配 `*`：`(1, 0, 0)`。
   - 其他通配（含 `*.example.com` 命中 `example.com`）：计算非通配分段数与字面字符总长度，返回 `(2, literal_labels, literal_chars)`。
3. 实现 `get_matched_rule(self, url: str) -> dict | None` 与 `get_single_hop_policy(self, url: str) -> tuple[bool, set[str], bool]`。
4. 让 `is_url_allowed_navigation` 与 `check_permission` 统一调用 `get_matched_rule`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m unittest tests/test_security_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/security_manager.py tests/test_security_manager.py
git commit -m "feat(security): prioritize most-specific domain rule and drop legacy domain compat"
```

---

### Task 3: 新建独立模块 `NavigationGuard` 与完整单测

**Files:**
- Create: `core/navigation_guard.py`
- Test: `tests/test_navigation_guard.py`

**Interfaces:**
- Consumes: `SecurityManager.is_url_allowed_navigation`, `SecurityManager.get_single_hop_policy` (Task 2).
- Produces:
  - `SingleHopGrant(allowed_actions: set[str], follow_redirects: bool, granted_url: str)`
  - `NavigationGuard(security: SecurityManager, get_user_id: Callable[[], str])`
  - `NavigationGuard.attach(browser_ctx, initial_page, on_new_page=None, on_main_frame_navigated=None) -> None` (async)
  - `NavigationGuard.check_single_hop_permission(page, current_url: str, action: str) -> tuple[bool, str]`

- [ ] **Step 1: 编写 `tests/test_navigation_guard.py` 覆盖全部单跳与重定向/弹窗/权限边界场景**

测试覆盖：
1. `test_single_hop_allowed_and_second_hop_blocked`：从有单跳权限的 `search.example.com` 点击跳转到非白名单 `target.com` 放行；再从 `target.com` 跳转到 `other.com` 被 `route.abort()` 拦截。
2. `test_single_hop_disabled_rule_blocks_jump`：从无单跳权限的 `docs.example.com` 跳转到 `target.com` 被拦截。
3. `test_single_hop_follow_redirects_true_and_false`：`follow_redirects=True` 时 `redirected_from` 链放行并更新 `granted_url`；`follow_redirects=False` 时重定向请求被拦截。
4. `test_popup_new_tab_single_hop`：白名单页面通过 `browser_ctx.on("page")` 打开新弹窗 `popup_page`（`url="about:blank"`，`opener=source_page`）跳转到 `target.com` 放行，且新标签页获得 `SingleHopGrant`；再跳 `other.com` 被拦截。
5. `test_single_hop_grant_action_permissions_and_url_update`：落地页 `check_single_hop_permission` 允许 `read`/`screenshot`（并容忍同源 query/hash 变化或 `framenavigated` 更新后的 URL），拒绝 `click`。
6. `test_navigate_back_to_whitelist_clears_grant`：单跳页面跳转到白名单域名后，该页的 `SingleHopGrant` 被清除，恢复白名单规则权限。
7. `test_subresource_requests_bypass_guard`：非导航请求（`is_navigation_request() == False`）或子帧导航请求直接放行，不触发或消耗单跳授权。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m unittest tests/test_navigation_guard.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'astrbot_plugin_playwright_tools.core.navigation_guard'`).

- [ ] **Step 3: 实现 `core/navigation_guard.py`**

核心结构：
- `SingleHopGrant` `@dataclass`：`allowed_actions: set[str]`, `follow_redirects: bool`, `granted_url: str`。
- `NavigationGuard`：
  - 使用 `from astrbot.api import logger`。
  - `_page_grants: dict[int, SingleHopGrant]`、`_page_openers: dict[int, Any]`。
  - `_is_main_frame_nav(request, page)`：判断主帧顶层导航。
  - `_resolve_source_page(page)`：若当前页 URL 为空或 `about:blank`，优先取 `_page_openers` 或 `await page.opener()`，否则返回 `page`。
  - `_route_guard(route, request)`：按白名单放行（清 grant） -> 重定向链（查当前页 grant 与 `follow_redirects`） -> 首次跳出（查 `source_page` 非 grant 状态且 `get_single_hop_policy` 允许）逻辑处理，异常时记录 `logger.warning` 并回退 `route.continue_()`。
  - `check_single_hop_permission(page, current_url, action)`：校验 `page` 存在有效 `SingleHopGrant`，`current_url` 与 `grant.granted_url` 主机/协议一致，且 `action in grant.allowed_actions`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m unittest tests/test_navigation_guard.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/navigation_guard.py tests/test_navigation_guard.py
git commit -m "feat(security): add decoupled NavigationGuard with per-page single-hop grant"
```

---

### Task 4: 解耦 `ContextManager` 并集成 `BaseHandler` 单跳鉴权

**Files:**
- Modify: `core/context_manager.py:20-56,400-510`
- Modify: `tools/handlers/base_handler.py:242-269`
- Test: `tests/test_context_manager.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: `NavigationGuard` (Task 3).
- Produces:
  - `BrowserSessionContext.navigation_guard: NavigationGuard | None = None`
  - `ContextManager._create_new_context` 委托 `NavigationGuard.attach(...)` 管理非外部上下文路由守卫与页面监听。
  - `BaseHandler.execute_action` 在 `security_mgr.check_permission` 拒绝时，回退检查 `ctx.navigation_guard.check_single_hop_permission`。

- [ ] **Step 1: 在 `tests/test_context_manager.py` 和 `tests/test_tools.py` 中补充集成测试**

1. 在 `tests/test_context_manager.py` 验证 `_create_new_context` 为 `ctx.navigation_guard` 挂载 `NavigationGuard` 实例且原有弹窗/主帧快照失效行为保持正常。
2. 在 `tests/test_tools.py`（或 `tests/test_page_handler.py`）验证：当 `security_mgr.check_permission` 返回拒绝、但 `ctx.navigation_guard.check_single_hop_permission` 返回允许时，`BaseHandler.execute_action` 放行 `read`；而 `open_url` 仍只走 `is_url_allowed_navigation` 并被拒绝。

- [ ] **Step 2: 运行测试确认新集成断言失败**

Run: `.venv/bin/python -m unittest tests/test_context_manager.py tests/test_tools.py -v`
Expected: FAIL (`BrowserSessionContext` 无 `navigation_guard` 或 `BaseHandler` 未回退检查单跳权限)。

- [ ] **Step 3: 重构 `core/context_manager.py` 与更新 `tools/handlers/base_handler.py`**

1. 在 `BrowserSessionContext` 中新增 `navigation_guard: Any = None`。
2. 在 `ContextManager._create_new_context` 中：
   - 实例化 `ctx`（或先创建 `NavigationGuard` 传入动态 `get_user_id` 闭包），对非外部上下文调用 `await nav_guard.attach(browser_ctx, first_page, on_new_page=..., on_main_frame_navigated=...)`，移除原内联 `_route_guard`、`_setup_page_listeners`、`_on_popup`。
   - 保留 `is_external=True` 的保活事件监听与跳过路由守卫行为。
3. 在 `BaseHandler.execute_action` 中：
   - 当 `required_permission != "navigate" and action_name != "open_url"` 且 `security_mgr.check_permission(...)` 返回 `False` 时，若 `getattr(ctx, "navigation_guard", None)` 存在，调用 `ctx.navigation_guard.check_single_hop_permission(page, current_url, required_permission)`；若放行则置 `allowed = True`。

- [ ] **Step 4: 运行全量单元测试确认通过**

Run: `.venv/bin/python -m unittest discover tests -v`
Expected: 全部测试 PASS。

- [ ] **Step 5: Commit**

```bash
git add core/context_manager.py tools/handlers/base_handler.py tests/test_context_manager.py tests/test_tools.py
git commit -m "refactor(context): decouple route guard into NavigationGuard and integrate single-hop check"
```

---

### Task 5: 文档与变更记录同步

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新 `README.md` 与 `docs/ARCHITECTURE.md`**

- 在 `README.md` 中补充 `whitelist_rules` 新增的 `allow_single_hop`、`single_hop_allowed_actions`、`single_hop_follow_redirects` 说明及规则精确度优先匹配说明。
- 在 `docs/ARCHITECTURE.md` 中补充 `core/navigation_guard.py` 模块职责及单跳放行机制架构描述。
- 在 `CHANGELOG.md` 中记录本次新增功能与解耦重构（语言凝练准确，不使用绝对化措辞）。

- [ ] **Step 2: 运行全量单元测试做最终验证**

Run: `.venv/bin/python -m unittest discover tests`
Expected: `OK`，无失败与跳过。

- [ ] **Step 3: Commit**

```bash
git add README.md docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: document single-hop whitelist permission and NavigationGuard architecture"
```

---

## Self-Review Check

- **Spec coverage:**
  - `_conf_schema.json` 三项新字段 -> Task 1
  - 精确度优先匹配 & 移除 `domain` 兼容 -> Task 2
  - 独立 `NavigationGuard` 与 `Page` 粒度单跳/重定向/弹窗 -> Task 3
  - `ContextManager` 解耦 & `BaseHandler` 集成 & 遗留测试清理 -> Task 2 & Task 4
  - 文档同步 -> Task 5
- **Type & signature consistency:** `SecurityManager.get_matched_rule`, `SecurityManager.get_single_hop_policy`, `NavigationGuard.attach`, `NavigationGuard.check_single_hop_permission` 在各任务间签名完全一致。
- **Review focus:** 5 项边界场景均已在 Task 2 和 Task 3 的测试步骤中明确覆盖。
