# 白名单单跳放行权限、规则精确度优先与 ContextManager 解耦设计

## 1. 意图与背景

当前插件在非管理员模式下，对所有顶层页面导航和工具操作都执行严格的域名白名单校验：
- **所有页面内跳转受限**：即使一个白名单网站（例如搜索引擎）本身在白名单内，用户在其中点击链接跳转到外部非白名单站点（或弹出新标签页）时，会被路由守卫直接拦截，导致无法查看搜索结果或外链目标页。
- **通配规则遮蔽精确规则**：[`SecurityManager`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/security_manager.py#L6-L125) 目前按配置列表顺序命中第一条规则即返回，导致 `*.example.com`（基础权限集 A）写在 `search.example.com`（权限集 A + 单跳放行）之前时，后者无法生效。
- **`ContextManager` 职责过重**：[`core/context_manager.py`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/context_manager.py) 已达 944 行，同时承担多租户上下文生命周期、路由守卫、页面/弹窗事件监听与审计指标提取。

本设计的目标是在白名单规则中引入可配置的“单跳放行”能力，解决域名匹配优先级问题，并将导航守卫与单跳状态管理从 `ContextManager` 中解耦出来。

---

## 2. 目标、非目标与反目标

### 目标
1. 在 [`_conf_schema.json`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/_conf_schema.json) 的 `whitelist_rules` 每条规则中新增“是否允许单跳放行”开关；开启后可配置“单跳页面允许的行为（多选）”和“是否遵循重定向（开关）”。
2. 有单跳权限的白名单页面通过页面内操作（点击、表单提交、JS 跳转、弹窗新标签页等）跳出到非白名单页面时，放行这一次跳转，并按该规则配置的“单跳页面允许的行为”限制目标页面的后续工具操作（例如仅只读）。
3. 到达单跳目标页面后，若目标页面本身不在白名单（或没有单跳权限），禁止从该目标页面继续跳转到其他非白名单页面（杜绝多跳链式逃逸）。
4. 域名匹配改为**最精确规则优先（Most-Specific Match）**，确保 `search.example.com` 稳定覆盖 `*.example.com`，与规则在列表中的前后顺序无关。
5. 将路由守卫、页面事件监听与单跳授权状态追踪拆分为独立的 [`NavigationGuard`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/navigation_guard.py) 模块，精简 `ContextManager`。
6. 移除旧版本单数 `domain` 字段等历史兼容性代码及对应遗留测试。

### 非目标
- 不支持配置“允许 N 跳（N > 1）”的通用多跳深度。
- 不改变管理员（`admin_bypass`）的全局放行逻辑，也不改变外部插件上下文（`is_external=True`）跳过路由守卫的现有行为。
- 不为 `pw_page(open_url)` 主动传入非白名单 URL 提供单跳豁免——`open_url` 仍严格受白名单约束。

### 反目标
- 不在 `ContextManager` 中继续堆叠路由拦截与状态字典。
- 不保留旧版 `domain` 兼容分支。

---

## 3. 约束条件

- **架构与规范**（见 [AGENT.md](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/AGENT.md) 与 [HOW-TO-CODE.md](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/HOW-TO-CODE.md)）：
  - 严禁使用 `import logging`，仅使用 `from astrbot.api import logger`。
  - 保持实现简洁，不引入不必要的抽象层；所有工具/核心组件变更后需通过 `python -m unittest discover tests`。
  - 变更完成后同步更新 `README.md`、`docs/ARCHITECTURE.md`、`CHANGELOG.md` 等文档。
- **不兼容旧配置**：移除 `SecurityManager._is_rule_match` 中对旧字段 `domain` 的回退兼容逻辑，统一使用 `domains` 列表，并清理对应兼容测试。

---

## 4. 方案选型

### 4.1 域名规则匹配优先级
- **备选方案 A（已选）：按域名精确度优先匹配（Most-Specific Match）**
  遍历所有命中当前 `host` 的规则，按匹配模式精确度评分（精确域名 `search.example.com` > 深层通配 `*.sub.example.com` > 浅层通配 `*.example.com` > 全局 `*`），取得分最高的规则生效。
  - *权衡*：完全不依赖规则排列顺序，且支持对特定子域名单独收紧或放宽权限；缺点是子域名规则需完整勾选自身所需的 `allowed_actions`。
- **备选方案 B（未选）：合并所有命中规则的权限（Union Merge）**
  将命中同一域名的所有规则权限取并集。
  - *权衡*：虽可只写增量权限，但无法对子域名收紧权限，且当布尔配置（如“是否遵循重定向”）冲突时语义模糊。

### 4.2 单跳放行状态与拦截机制
- **备选方案 1（已选）：基于标签页（`Page`）粒度的单跳授权状态**
  由独立的 `NavigationGuard` 为每个 `Page` 维护单跳授权状态 `SingleHopGrant`。同页跳转与弹窗新标签页分别通过 `request.frame.page` 与 `page.opener()` 追溯源页面，在路由守卫与工具鉴权两处协同判定。
  - *权衡*：多标签页互不干扰，能严格区分页面内跳转与 AI 主动 `open_url`；需在弹窗创建及路由回调中正确处理 `opener` 与重定向链。
- **备选方案 2（未选）：基于会话上下文（`Context`）的单次交互令牌**
  在交互前颁发上下文级一次性令牌。
  - *权衡*：多标签页切换、异步延迟跳转或弹窗场景下极易串页或漏判，稳定性不足。

---

## 5. 详细设计

### 5.1 配置模式（`_conf_schema.json`）

在 `security.items.whitelist_rules.templates.rule.items` 中新增以下三项配置：

1. `allow_single_hop`（`bool`，默认 `false`）
   - 描述：`允许单跳放行`
   - 提示：`开启后，允许该规则内的页面通过点击或弹窗等操作跳转到非白名单页面一次`
2. `single_hop_allowed_actions`（`list`，默认 `["read", "screenshot"]`，`condition: {"allow_single_hop": true}`）
   - 描述：`单跳页面允许的行为`
   - 提示：`勾选单跳落地后在目标非白名单页面上允许执行的操作权限`
   - `options` 与 `labels` 复用 `allowed_actions` 的 12 项原子操作。
3. `single_hop_follow_redirects`（`bool`，默认 `true`，`condition: {"allow_single_hop": true}`）
   - 描述：`单跳遵循重定向`
   - 提示：`开启后，单次页面内跳转过程中发生的 HTTP 301/302 重定向链视为同一次跳转并放行；关闭则拦截重定向`

> 注：构建时需确认 AstrBot 的 `template_list` 模板项是否支持 `condition` 动态显隐；若前端不支持，保留字段直接展示并在 `hint` 中标注“仅在开启允许单跳放行时生效”。

### 5.2 规则精确度优先匹配（`core/security_manager.py`）

1. **移除旧字段兼容**：`_is_rule_match` 仅读取 `rule.get("domains", [])`（列表形态），删除 `rule.get("domain")` 兼容分支。
2. **规则精确度评分与匹配**：
   - 新增 `_pattern_specificity(host: str, domain_pattern: str) -> tuple[int, int, int] | None`：
     - 不匹配返回 `None`。
     - 精确匹配（`norm_pat` 不含通配符 `*` / `?`）：返回最高优先级 `(3, len(norm_pat.split(".")), len(norm_pat))`。
     - 通配符匹配（包含 `*.example.com` 命中 apex 根域名 `example.com` 的情况）：计算非通配分段数与字面字符长度，返回 `(2, literal_label_count, literal_char_count)`；纯 `*` 返回 `(1, 0, 0)`。
   - 新增 `get_matched_rule(url: str) -> dict | None`：遍历 `self.whitelist_rules`，对每条规则取所有匹配 `host` 的模式中的最高分，返回得分最高的规则（同分时先配置的规则优先）。
3. **单跳配置读取辅助**：
   - `is_url_allowed_navigation` 与 `check_permission` 统一通过 `get_matched_rule` 获取命中的最精确规则。
   - 新增方法 `get_single_hop_policy(url: str) -> tuple[bool, set[str], bool]`（或返回轻量配置结构）：若 `url` 命中某条白名单规则且 `allow_single_hop` 为真，返回 `(True, set(single_hop_allowed_actions), bool(single_hop_follow_redirects))`；否则返回 `(False, set(), False)`。

### 5.3 独立导航守卫与单跳状态管理（`core/navigation_guard.py`）

新建 `core/navigation_guard.py`，定义：

- **`SingleHopGrant` 数据结构**：
  - `allowed_actions: set[str]`：该落地页允许执行的操作集合。
  - `follow_redirects: bool`：本次跳转是否允许跟随重定向。
  - `granted_url: str`：当前放行的目标 URL（重定向或 `framenavigated` 后同步更新）。
- **`NavigationGuard` 类**：
  - 持有 `security: SecurityManager` 与当前关联上下文的 `user_id` 解析回调（兼容 `personal` 与 `session` 模式获取操作者 ID）。
  - 内部维护：
    - `_page_grants: dict[int, SingleHopGrant]`（以 `id(page)` 为键，并在 `page.on("close")` 时清理）。
    - `_page_openers: dict[int, Any]`（在 `browser_ctx.on("page", ...)` 时记录新弹窗与来源页的关系，辅助 `page.opener()` 判定）。
  - **`attach(browser_ctx, initial_page, on_new_page, on_main_frame_navigated)`**：
    - 挂载 `browser_ctx.route("**/*", _route_guard)`。
    - 挂载 `browser_ctx.on("page", ...)`：记录新页入 `ctx.pages`、切换 `ctx.current_page`、记录 opener 关系并为其挂载页面监听。
    - 为每个页面挂载 `framenavigated`（主帧导航时通知上下文失效快照，若新 URL 已在白名单内则清除该页的 `SingleHopGrant`，若仍持有授权则更新 `granted_url`）与 `close` 清理监听。
  - **`_route_guard(route, request)` 判定流程**：
    1. 仅对顶层主帧导航请求（`request.is_navigation_request()` 且为 main frame）执行校验；静态资源与子请求直接 `route.continue_()`。
    2. 若 `security.is_url_allowed_navigation(user_id, request.url)` 为真：清除目标 `page` 的 `SingleHopGrant`，放行请求。
    3. 若目标 URL 不在白名单内：
       - **重定向链判定**（`request.redirected_from` 不为空）：
         - 检查当前 `page` 是否已持有处于本次跳转流程中的 `SingleHopGrant`。
         - 若持有且 `grant.follow_redirects == True`：更新 `grant.granted_url = request.url` 并放行。
         - 否则（未勾选遵循重定向，或无有效授权）：调用 `route.abort()` 拦截。
       - **首次非白名单跳转判定**（`request.redirected_from` 为空）：
         - 确定来源页面 `source_page`：同标签页导航取 `request.frame.page`；若为新弹窗首跳（当前 `page.url` 为空或 `about:blank`），取已记录的 opener（或 `await page.opener()`）。
         - 若 `source_page` 本身处于 `SingleHopGrant` 状态（即已经跳出白名单一次），拒绝再次跳出，`route.abort()`。
         - 获取 `source_page.url`，调用 `security.get_single_hop_policy(source_page.url)`：
           - 若开启了单跳放行：为目标 `page` 写入 `SingleHopGrant(allowed_actions, follow_redirects, granted_url=request.url)` 并放行。
           - 否则：`route.abort()`。
  - **`check_single_hop_permission(page, current_url: str, action: str) -> tuple[bool, str]`**：
    - 供 `BaseHandler` 在白名单校验未命中时查询当前 `page` 是否持有有效的 `SingleHopGrant`（校验 `current_url` 与 `grant.granted_url` 同源/匹配，且 `action in grant.allowed_actions`）。

### 5.4 `ContextManager` 解耦（`core/context_manager.py`）

- 在 `_create_new_context` 中移除内联的 `_route_guard`、`_setup_page_listeners`、`_on_popup` 闭包实现，改为实例化并挂载 `NavigationGuard`。
- `BrowserSessionContext` 持有 `navigation_guard: NavigationGuard | None = None` 引用，供 `BaseHandler` 查询单跳授权。

### 5.5 工具鉴权集成（`tools/handlers/base_handler.py`）

- `pw_page(open_url)` 与 `required_permission == "navigate"` 保持仅调用 `security_mgr.is_url_allowed_navigation`，不允许 AI 通过 `open_url` 直接打开非白名单 URL。
- 其他操作（`read`、`click`、`screenshot` 等）在 `security_mgr.check_permission(auth_user_id, current_url, required_permission)` 返回拒绝时：
  - 若 `ctx.navigation_guard` 存在，调用 `ctx.navigation_guard.check_single_hop_permission(page, current_url, required_permission)`。
  - 若单跳授权允许该操作，则放行；否则返回拒绝原因并记录审计日志。

### 5.6 清理兼容性代码与测试

- `core/security_manager.py`：删除 `rule.get("domain")` 兼容逻辑。
- `tests/test_security_manager.py`：删除 `test_whitelist_rules_backward_compatibility_single_domain`，将测试固件中的 `"domain"` 统一改为 `"domains"`，补充精确度优先匹配测试（`*.example.com` 与 `search.example.com` 正反序排列均正确生效）。
- `tests/test_conf_schema.py`：补充对 `allow_single_hop`、`single_hop_allowed_actions`、`single_hop_follow_redirects` 的结构断言。
- `tests/test_navigation_guard.py`（新增）：覆盖单跳放行、二跳拦截、`follow_redirects=True/False` 重定向链、弹窗新标签页单跳、落地页操作权限校验（如允许 `read` 拒绝 `click`），以及回到白名单后授权清除。
- `tests/test_context_manager.py`：移除或调整不再适用的旧内联路由测试细节，确保与解耦后的 `NavigationGuard` 一致。

---

## 6. 留给实施者的事项

- 确认 AstrBot WebUI 对 `template_list` 内部 `condition` 字段的支持情况，必要时做平铺降级并保持配置键名不变。
- 设计 `NavigationGuard` 内部对 `page.opener()` 与 `redirected_from` 的 mock 友好接口，保证单元测试无需启动真实浏览器即可覆盖所有分支。
- 完成代码修改并运行 `python -m unittest discover tests` 全部通过后，同步更新 `README.md`、`docs/ARCHITECTURE.md` 与 `CHANGELOG.md`。
