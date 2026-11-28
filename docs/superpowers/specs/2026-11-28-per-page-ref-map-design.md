# 按页面隔离 Ref ID 映射与跨标签页自动寻址设计

## 1. 意图与背景

目前 [`BrowserSessionContext`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/context_manager.py#L21-L57) 在上下文层级全局持有单份 `ref_map`、`current_snapshot` 和 `is_snapshot_dirty`。当 AI 在标签页 1 读取内容后点击打开标签页 2 并读取标签页 2 时，标签页 1 的 `ref_map` 会被覆盖；此外，任何标签页的主帧导航都会清空全局 `ref_map`，[`AriaReader`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/readers/aria_reader.py) 也忽略 `start_ref` 导致不同标签页的 `ref_id` 从 `e1` 起重号。

本次重构的目标是让每个标签页（`Page`）独立维护自己的 `ref_map` 与快照状态，保持上下文级 `ref_id` 单调递增不重号，并支持 AI 在不调用 `switch_tab` 的情况下直接传入任意标签页的 `ref_id` 即可自动切换活动页面并完成操作。

## 2. 目标与非目标

### 目标
1. **每页独立状态**：每个 `Page` 独立维护 `PageState`（`ref_map`、`current_snapshot`、`is_snapshot_dirty`）。
2. **全局单调递增 Ref ID**：上下文级 `next_ref_id` 维持单调递增（达到 `1_000_000` 回滚为 `1`）；[`MarkdownReader`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/readers/markdown_reader.py) 与 [`AriaReader`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/readers/aria_reader.py) 均使用 `start_ref` 生成全局唯一数字 `ref_id`。`AriaReader` 在元素字典中保留原始 `aria_ref`（如 `e1`）用于底层 Locator 定位。
3. **跨标签页自动寻址与激活**：调用任何带 `ref` 参数的工具（`pw_interact`、`pw_media` 下载、`pw_read(ref=...)`）时，优先在当前活动页面查找 `ref`；未命中则遍历同上下文其他存活标签页；命中后自动将该标签页设为 `current_page`（并尝试 `bring_to_front()`），然后执行鉴权与操作。
4. **精准生命周期清理**：主帧导航仅重置发生导航的那个 `Page` 的 `PageState`；`switch_tab` 仅切换 `current_page`，不清空原标签页状态；标签页关闭时移除对应 `PageState` 并在必要时回退 `current_page`。
5. **无历史包袱**：不保留旧的全局 `ctx.ref_map` 等兼容代理，同步更新相关 Handler、单测与项目文档。

### 非目标
- 不支持跨不同 `BrowserSessionContext`（不同用户/会话）的 `ref_id` 寻址。
- 不支持跨标签页 `drag_and_drop`（源 `ref` 与目标 `target_ref` 必须在同一页面内）。

## 3. 备选方案对比

- **方案一（选用）：`BrowserSessionContext` 内按 `id(page)` 维护 `page_states: dict[int, PageState]`（无旧属性兼容代理）**
  - 单一数据源，每个标签页的 `ref_map`、快照与脏标记天然隔离；跨标签页反查只需遍历同上下文内有限个存活标签页，命中后激活该页。无需维护额外倒排索引，避免双写不一致。
- **方案二（弃用）：每页状态 + 上下文级 `ref_to_page` 倒排索引**
  - 虽然反查为 O(1)，但同一上下文标签页数量通常极少，遍历开销可忽略；而额外维护全局倒排表需要在导航、刷新、关闭时同步清理，增加状态不一致风险。

## 4. 详细设计

### 4.1 `core/context_manager.py`
- 新增 `@dataclass class PageState`：
  - `ref_map: dict[str, dict] = field(default_factory=dict)`
  - `current_snapshot: Any = None`
  - `is_snapshot_dirty: bool = False`
- 修改 `BrowserSessionContext`：
  - 移除全局 `ref_map`、`current_snapshot`、`is_snapshot_dirty` 字段。
  - 新增 `page_states: dict[int, PageState] = field(default_factory=dict)`。
  - 保留 `next_ref_id: int = 1`、`ref_lock: asyncio.Lock` 及 `allocate_ref_id()`。
  - 新增页面状态与寻址方法：
    - `get_page_state(self, page: Page | None = None) -> PageState`：获取指定页面（默认 `current_page`）的 `PageState`，不存在时自动初始化。
    - `clear_page_state(self, page: Page | None, reset_snapshot: bool = True) -> None`：清空指定页面的 `ref_map` 并按需重置 `current_snapshot` 与 `is_snapshot_dirty`。
    - `remove_page_state(self, page: Page | None) -> None`：页面关闭时删除其 `page_states` 条目，将其从 `pages` 移除，并在其等于 `current_page` 时切换 `current_page` 至剩余最新存活页面。
    - `resolve_ref(self, ref: str | int) -> tuple[Page | None, dict | None]`：规范化 `ref` 字符串，优先检索 `current_page` 的 `PageState.ref_map`；未命中时按 `browser_context.pages`（回退 `self.pages`）顺序检索其他未关闭标签页的 `PageState.ref_map`，返回 `(target_page, el_info)`。
    - `activate_page(self, page: Page) -> None`：设置 `self.current_page = page`，同步 `self.pages`；若页面具备 `bring_to_front` 且未关闭，尝试安全调用。
- `_create_new_context`：
  - `_on_main_frame_nav(page)` 改为仅重置 `page` 对应的 `PageState`（`clear_page_state(page, reset_snapshot=True)`，并标记 `is_snapshot_dirty = True`）。
  - 通过 `NavigationGuard` 的 `on_page_closed` 回调在页面关闭时调用 `ctx.remove_page_state(page)`。

### 4.2 `core/navigation_guard.py`
- `attach(...)` 与 `_setup_page_listeners(...)` 增加可选回调 `on_page_closed: Callable[[Any], None] | None = None`，在页面 `close` 事件触发时调用，通知 `ContextManager` 清理对应 `PageState`。

### 4.3 `core/readers/aria_reader.py`
- `extract_snapshot(self, page: Any, url: str = "", start_ref: int = 1, **kwargs) -> PageSnapshot`：
  - 解析原生 YAML 得到原始 `aria-ref`（如 `e1`、`f1e2`）后，按 `start_ref` 起步单调递增（达到 `1_000_000` 回滚为 `1`）建立 `raw_ref -> global_ref` 映射。
  - 将 `cleaned_yaml` 中的 `[ref=<raw_ref>]` 替换为 `[ref=<global_ref>]` 后再分块。
  - 重建 `ref_map`，以 `global_ref` 为键，保留原属性并写入 `"ref": global_ref` 与 `"aria_ref": raw_ref`。
  - `_fetch_element_src(page, raw_aria_ref)` 使用原始 `aria_ref` 定位元素，图片 `src` 与父级 `link` 关联逻辑在映射后的 `ref_map` 上生效。
- 更新 `get_tool_metadata()` 中 `ref` 参数示例为数字编号格式。

### 4.4 `tools/handlers/base_handler.py`
- 在 `execute_action` 中：
  - 若 `input_args` 包含非空 `ref`，先调用 `ctx.resolve_ref(clean_ref_str)`；若命中其它标签页且与当前 `page` 不同，则调用 `await ctx.activate_page(target_page)`（若为异步）或 `ctx.activate_page(target_page)`，并将后续鉴权（含单跳授权检查）、`current_url`、审计日志及 `action_coro_fn(ctx, page)` 中的 `page` 统一更新为 `target_page`。
  - 密码输入框探测优先读取 `el_info.get("type") == "password"`；若需调用 `locator.get_attribute("type")`，优先使用 `el_info.get("aria_ref")` 构造 `aria-ref=...` Locator，否则使用 `[data-astr-ref="..."]`。

### 4.5 `tools/handlers/page_handler.py`、`interact_handler.py`、`media_handler.py`
- **`page_handler.py`**：
  - `open_url`：仅清理当前 `page` 的 `PageState`。
  - `read_page`：先根据当前 `cur_page` 的 `PageState` 判断快照是否失效并提取快照写入该页的 `PageState`。当传入 `ref` 查询详情时，通过 `ctx.resolve_ref(clean_ref)` 跨页查找并激活目标页；若目标页快照尚未过期则直接返回详情，必要时支持刷新。
  - `switch_tab`：切换 `ctx.current_page`（并调用 `activate_page`），**不再清空** `ref_map` 与 `current_snapshot`。
- **`interact_handler.py`**：
  - 统一抽取私有辅助方法解析 `ref` 所在页面、获取 `el_info` 与构造 Locator（优先使用 `el_info.get("aria_ref")` 构造 `aria-ref=...`，否则 `[data-astr-ref="..."]`）。
  - 操作完成后仅将当前操作页的 `PageState.is_snapshot_dirty` 设为 `True`。
  - `drag_and_drop`：解析 `ref` 激活目标页后，校验 `target_ref` 是否存在于同一页面的 `PageState.ref_map` 中。
- **`media_handler.py`**：
  - `download` 使用当前操作页的 `PageState.ref_map` 验证 `ref` 并依据 `el_info.get("aria_ref")` 构造 Locator。

## 5. 测试与文档更新
- 更新 `tests/` 中受 `ctx.ref_map` / `ctx.current_snapshot` 移除影响的单元测试，并补充多标签页场景测试（标签页 1 读取 -> 打开并读取标签页 2 -> 不调用 `switch_tab` 直接操作标签页 1 的 `ref_id`、验证活动页自动切回标签页 1、`AriaReader` 全局单调 `ref_id` 映射、后台页导航不误清前台页 `ref_map`、关闭标签页清理状态）。
- 同步更新 `docs/ARCHITECTURE.md`、`CHANGELOG.md` 及 `skills/playwright-tool/` 中关于多标签页与 `ref_id` 机制的描述。
