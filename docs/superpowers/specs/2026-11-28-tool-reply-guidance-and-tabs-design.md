# 工具回复引导优化与标签页感知设计

## 1. 意图与背景

目前工具返回给 AI 的消息存在两类信息缺口，容易导致 AI 陷入防御性停滞或重复操作：
1. **权限受限缺乏出路指引**：当目标网页无权执行某项操作（如 `click`、`fill`）时，仅返回 `"{action_desc}失败: {reason}"`，未告知当前页面实际允许哪些操作，AI 容易停止尝试或放弃当前页面。
2. **标签页状态感知缺失**：AI 无法主动查询已打开的所有标签页（标题与链接），且在点击触发新标签页弹出、跨标签页自动切换或 `open_url` 复用当前页时缺乏明确的标签页数量与当前页提示，容易反复调用 `pw_page(action='open')` 试图“重新打开”。

本次重构在 `BaseActionHandler` 统一切面与 `pw_page` 工具中补齐权限可用操作指引、专门的 `list_tabs` 动作，以及新开/切换标签页自动通知，同步清理旧的提示实现、旧测试并更新文档与 SKILL。

## 2. 目标与非目标

### 目标
1. **权限拒绝时列出当前页面可执行操作**：当 `BaseActionHandler.execute_action` 鉴权失败时，汇总当前页实际允许的动作集合（综合白名单规则与单跳临时授权），映射为具体的 `pw_*` 工具调用指引附带在失败回复中；若当前页无任何可用权限，则提示 AI 调用 `pw_page(action='list_tabs')` 查看/切回其他标签页，或打开允许访问的网址。
2. **新增 `pw_page(action='list_tabs')`**：专门返回当前活动标签页标识及所有已打开标签页列表（含序号、是否当前活动、标题、链接）。
3. **标签页打开/切换自动告知**：在 `BaseActionHandler.execute_action` 中对比动作执行前后的标签页列表与活动页；一旦发生新标签页打开或活动标签页切换，自动在返回结果中告知当前标签页总数、当前活动页序号及标题/链接；`open_url` 回复中同样明确当前标签页序号与总数，避免 AI 误以为每次 `open` 都会新建标签页。
4. **无历史包袱**：不保留旧的仅返回裸错误或无标签页提示的兼容逻辑，同步清理并更新相关测试、架构文档与 SKILL。

### 非目标
- 不新增第 5 个顶层工具，继续收敛在四大复合工具（`pw_page`、`pw_read`、`pw_interact`、`pw_media`）内。
- 不暴露内部权限字符串作为唯一提示，统一提供可直接执行的工具调用指引。

## 3. 备选方案对比

- **方案一（选用）：在 `SecurityManager` + `BaseActionHandler.execute_action` 切面统一处理**
  - 权限汇总与工具指引映射、动作前后标签页变更检测均集中在 `BaseActionHandler.execute_action` 切面；`PageHandler` 新增 `list_tabs` 并注册至 `pw_page`。所有工具自动受益，无重复代码，不会在特定交互（如按键弹窗、跨页 `ref` 自动激活）中漏报。
- **方案二（弃用）：在各业务 Handler 内分别检测与拼接提示**
  - 需在 `PageHandler`、`InteractHandler`、`MediaHandler` 多处重复编写标签页对比逻辑，易遗漏且维护成本高。

## 4. 详细设计

### 4.1 `core/security_manager.py`
- 新增 `get_allowed_actions(self, user_id: str, url: str) -> set[str]`：
  - 定义全量已知动作集合 `ALL_KNOWN_ACTIONS = {"read", "click", "fill", "select", "hover", "focus", "drag", "press_key", "scroll", "screenshot", "download", "navigate"}`。
  - 若 `admin_bypass and is_admin(user_id)`，或 `admin_only and is_admin(user_id)`：返回 `set(ALL_KNOWN_ACTIONS)`。
  - 若 `admin_only` 且非管理员，或协议非 `http`/`https`，或无有效域名/未命中白名单规则：返回 `set()`。
  - 否则返回 `set(matched_rule.get("allowed_actions", []))`。

### 4.2 `tools/handlers/base_handler.py`
- **动作-工具指引映射**：定义统一映射表 `ACTION_GUIDANCE_MAP`（将内部权限动作 `read`、`click`、`fill`、`select`、`hover`、`focus`、`drag`、`press_key`、`scroll`、`screenshot`、`download`、`navigate` 映射为简洁的 `pw_*` 调用示例），并新增辅助方法 `_format_allowed_actions_guidance(self, ctx, page, auth_user_id, current_url) -> str`：
  - 从 `self.security_mgr.get_allowed_actions(auth_user_id, current_url)` 获取白名单允许动作，若 `NavigationGuard` 对当前 `page` 持有有效单跳授权，则并入 `grant.allowed_actions`。
  - 若非空，输出 `[当前页面可执行操作: ...]`（列出对应 `pw_*` 工具调用指引）；若为空，输出 `[当前页面无可用操作权限，可调用 pw_page(action='list_tabs') 查看并切换其他标签页，或调用 pw_page(action='open') 访问允许的网址]`。
  - 在 `execute_action` 鉴权失败返回处追加该指引。
- **标签页变更自动感知**：
  - 定义辅助方法 `_snapshot_tabs(ctx)` 记录执行前的 `(page_ids, active_page)`，并在执行 `action_coro_fn` 后再次获取当前存活 `pages`（优先 `ctx.browser_context.pages`，回退 `ctx.pages`）与 `ctx.current_page`。
  - 若检测到**新标签页打开**（出现未在 `before_page_ids` 中的新 `Page`）或**活动标签页切换**（`after_active is not before_active` 且均非空），自动在返回文本末尾追加标签页状态摘要（说明新开了标签页或已切换至第 `idx/total` 页，附当前页标题与 URL，并提示可用 `pw_page(action='list_tabs')` 查看全部标签页）。

### 4.3 `tools/handlers/page_handler.py`、`tools/schemas.py`、`tools/tools.py`
- **`PageHandler.list_tabs`**：
  - 收集当前上下文所有存活标签页，标注当前活动页（`[当前活动]`）、序号（从 1 开始）、标题（安全异步/同步提取）与 URL，返回结构化列表与操作提示（`pw_page(action='switch_tab', tab_index=N)` 或直接操作目标页 `ref`）。
- **`PageHandler.open_url`**：
  - 返回文本中明确当前标签页位置（如 `当前位于第 {idx}/{total} 个标签页`），引导 AI 后续调用 `pw_read()` 或按需复用当前标签页。
- **`PageHandler.switch_tab`**：
  - 保留简洁的切换成功提示（`BaseActionHandler` 切面或本方法统一呈现当前标签页序号、总数、标题与 URL，避免重复拼接）。
- **`tools/schemas.py` & `tools/tools.py`**：
  - `PW_PAGE_SCHEMA` 的 `action.enum` 新增 `"list_tabs"`，更新描述。
  - `PageTool._actions` 注册 `"list_tabs": self._action_list_tabs`。

### 4.4 测试、文档与 SKILL 更新
- 更新 `tests/test_security_manager.py`、`tests/test_base_handler.py`、`tests/test_page_handler.py`、`tests/test_interact_handler.py`、`tests/test_tools.py`，覆盖：
  - 权限被拒时列出可执行操作指引（白名单部分授权、单跳临时授权、无任何权限三种场景）。
  - `pw_page(action='list_tabs')` 返回活动页与全部标签页标题/URL。
  - 点击触发新标签页打开、跨标签页 `ref` 自动切换、`switch_tab` 时自动告知标签页数量与当前页。
- 更新 `skills/playwright-tool/SKILL.md`、`docs/ARCHITECTURE.md`、`CHANGELOG.md`。
