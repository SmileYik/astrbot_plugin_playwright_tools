# 变更日志 (CHANGELOG)

本项目遵循语义化版本规范。

---

## [v1.6.0] - 2026-11-28

### 非 HTML 资源分流与统一多模态返回
- **`open_url` 基于 `wait_until="commit"` 与 `Content-Type` 分流**：
  - 避免图片、纯文本、PDF 等非 HTML 资源因等待 `domcontentloaded` 挂起至 30 秒超时。
  - 图片直链在开启“允许 AI 直接查看图片”（`allow_image_to_ai`）时直接通过 `CallToolResult`（`TextContent` + `ImageContent`）发往多模态大模型分析，未开启时返回元信息提示。
  - 新增 `PlainTextReader`，对非 HTML 纯文本/JSON/XML 响应遵循 `page_chunk_char_limit` 分页并缓存快照，支持 `open_url` 直出第 1 页及后续 `pw_read(page=...)` 翻页与关键词检索。
  - 统一 `MediaHandler`（`target='ai'` 截图）与 `PageHandler` 的多模态 `CallToolResult` 返回链路，并合并为单一 `allow_image_to_ai`（允许 AI 直接查看图片）配置开关。

---

## [v1.5.0] - 2026-11-28

### 配置体验与文档体系完善
- **现代大上下文默认值调优与控件精简**：
  - 将 `page_chunk_char_limit`、`browser_window_width/height`、`screenshot_max_height_px`、`file_retention_days`、`audit_retention_days`、`high_watermark`、`low_watermark`、`compress_max_input_chars` 从滑块改为直接数值输入；
  - 将默认值调优为均衡大上下文配置（`tool_execution_timeout_seconds=45`、`page_chunk_char_limit=4000`、`browser_window_height=800`、`screenshot_timeout_seconds=20`、`audit_retention_days=14`、`high_watermark=24000`、`low_watermark=10000`），并将副 AI 默认 `compress_prompt` 长度上限放宽至 `1000` 字，同步对齐 `main.py` 与 `core/history_cleaner.py` 兜底值。
- **文档分层与新版 README**：
  - 新增面向项目整体工具能力与技术约定的 [docs/AI_TOOLS.md](docs/AI_TOOLS.md)，并结合控制台截图重新排版 [README.md](README.md)。

### 工具回复引导优化与标签页状态感知
- **权限拒绝时列出可执行操作指引**：
  - 在 `SecurityManager` 新增 `get_allowed_actions(user_id, url)`，结合 `NavigationGuard` 单跳授权，在 `BaseActionHandler.execute_action` 鉴权失败时将当前页面允许的动作直接映射为具体 `pw_*` 工具调用指引（无可用权限时引导调用 `pw_page(action='list_tabs')` 或 `open`）。
- **新增 `pw_page(action='list_tabs')` 与标签页变更自动通知**：
  - `pw_page` 新增 `list_tabs` 动作，返回当前活动标签页及所有已打开标签页的序号、标题与链接；`open_url` 明确展示当前标签页位置与总数。
  - `BaseActionHandler.execute_action` 在执行前后自动对比存活标签页与活动页，检测到新标签页打开或活动页切换时自动附带 `[标签页通知: ...]`，减少 AI 重复 `open` 新标签页。

### 按页面隔离 `ref_map` 与跨标签页自动寻址
- **按标签页独立维护状态 (`PageState`)**：
  - 在 `BrowserSessionContext` 中移除全局 `ref_map`、`current_snapshot` 与 `is_snapshot_dirty`，改为按 `id(page)` 为每个标签页独立维护 `PageState`；`switch_tab` 不再清空原标签页快照与引用映射，主帧导航及页面关闭仅精准清理对应标签页状态。
- **`AriaSnapshotReader` 全局单调递增 `ref_id` 映射**：
  - `AriaSnapshotReader` 按上下文 `start_ref` 将原生 `aria-ref` 重映射为全局单调递增数字 `ref_id`，并在 `ref_map` 中保留 `aria_ref` 字段供底层 Locator 定位，消除多标签页重号冲突。
- **跨标签页 `ref_id` 自动寻址与激活**：
  - 在 `BaseActionHandler.execute_action` 中统一按 `ref` 优先检索当前活动页并支持跨标签页反查；命中其他标签页时自动将其切换为当前活动页并执行鉴权与操作。

### Markdown 阅读器 `@r` Ref 前缀与行内排版优化
- **Ref ID `@r` 前缀规范**：
  - `InlineMarkdownReader` 提取的 Ref ID 统一采用 `@r` 前缀（如 `@r1`、`@r2`），同步写入 `data-astr-ref` 与 `ref_map`，下游工具调用保持精确匹配（需传入完整 `@rN`）。
- **行内空白压缩与元素分隔**：
  - 在 `core/readers/markdown_extractor.js` 中压缩文本节点的连续空白字符（保留 `<br>` 换行），并在相邻交互控件边界自动补充空格分隔，避免 `[xxx][@r1][yyy][@r2]` 粘连。
- **文档与技能说明同步**：
  - 更新 `skills/playwright-tool/SKILL.md`、`README.md`、`docs/ARCHITECTURE.md` 及工具元数据中的 Ref 示例与说明。

### 白名单单跳放行、域名精确度优先匹配与导航守卫解耦
- **白名单单跳放行配置 (`whitelist_rules`)**：
  - 在 `_conf_schema.json` 的 `whitelist_rules` 规则模板中新增 `allow_single_hop`、`single_hop_allowed_actions` 与 `single_hop_follow_redirects` 配置项，支持为特定白名单站点开启单次页面内跳转/弹窗放行，并限制落地页可执行的操作权限与重定向链处理策略。
- **域名精确度优先匹配 (`SecurityManager`)**：
  - 将规则匹配升级为按域名精确度评分优先（精确域名 > 深层通配 > 浅层通配 > 全局通配），解决通配规则遮蔽子域名独立规则的问题；移除旧版单数 `domain` 字段兼容逻辑。
- **独立导航守卫解耦 (`NavigationGuard`)**：
  - 将路由守卫、主帧/弹窗监听与 `Page` 粒度单跳授权状态从 `ContextManager` 拆出至 `core/navigation_guard.py`，并与 `BaseActionHandler` 动作鉴权集成。

---

## [v1.4.5] - 2026-11-27

### 副 AI 压缩提示词用户意图动态占位符 (Dynamic {{user_input}} Placeholder in Compress Prompt)
- **`{{user_input}}` 动态占位符支持**：
  - 在副 AI 压缩提示词（`history_cleanup.items.compress_prompt`）中引入 `{{user_input}}` 占位符支持，使副 AI 能够获知用户当前核心问题与目标，执行目标导向的聚焦摘要（Query-Focused Summarization），避免盲目压缩丢失关键业务事实。
- **多态上下文逆序意图提取 (`_extract_user_input`)**：
  - 支持从当前上下文列表（`contexts`）中逆序检索最近一条 `role == "user"` 消息，自动解构多部件内容（兼容纯字符串 `str` 与 `TextPart` 列表）；
  - 若上下文中无用户消息，自动平滑回退至从当前事件（`event.message_str` / `event.get_message_str()`）提取；若均无则安全回退为 `""`，避免异常或残留占位符。
- **100% 向后兼容与配置模式引导**：
  - 未使用 `{{user_input}}` 的静态系统提示词保持原有行为不变；
  - 更新 `_conf_schema.json` 中 `compress_prompt` 的配置说明与提示，引导用户配置针对性提炼模板。

---

## [v1.4.4] - 2026-11-27

### 历史消减全量原始输入审计与专属对比视图 (Full History Audit Input Recording & Dedicated SideDrawer View)
- **消减前全量原始输入落盘 (`original_input`)**：
  - 在 `HistoryCleaner` 执行副 AI 压缩（`pw_history:compress`）与直接删除（`pw_history:delete`）时，将候选批次中所有工具调用与前序历史摘要拼装为全量文本完整存入 `input_args["original_input"]`，去除原有 200 字符 preview 截断限制。
  - 无论副 AI 压缩成功、副 AI 报错降级删除还是直接删除策略，均 100% 完整留存消减前原始输入，审计回溯完整可靠。
- **WebUI 抽屉专属长文本排版与对比卡片**：
  - 在前端控制台审计详情侧边抽屉（`SideDrawer.tsx`）中，对 `pw_history:*` 工具自动将超长 `original_input` 从入参 JSON 区域解耦剥离；
  - 入参 JSON 区域仅展示结构化元数据（批次大小、包含工具、原始/释放字符数），紧凑清爽；
  - 新增专属“消减前完整输入”（根据动作动态标为“压缩前完整输入”或“删除前完整输入”）多行文本卡片，带字符数统计与独立“复制完整输入”按钮；配合“压缩后结构化摘要”或“清理执行结果”卡片，实现消减前后效果清晰可视。

---

## [v1.4.3] - 2026-11-27

### 单批次聚合消减与水位配置演进 (Single-Pass Batch Compression & Watermark Option)
- **单批次聚合压缩机制 (Single-Pass Batch Compression)**：
  - 重构 `HistoryCleaner` 处理逻辑，废弃逐组循环请求副 AI 的旧机制。
  - 当本插件历史工具消息总字符数超过高水位阈值时，按先进先出（FIFO）队列贪心收集候选条目，一次性消减至低水位以下，仅向副 AI 发起 1 次结构化压缩请求，显著降低多轮工具调用下的端到端响应延迟。
  - 压缩成功后，前 N-1 个消息原位写入 `[已并入本轮浏览摘要]`，末尾消息写入 `[历史浏览摘要]:\n{summary}`；压缩失败或直接删除模式下，候选条目全部原位替换为删除占位符。
- **历史摘要计入水位配置项 (`include_compressed_in_watermark`)**：
  - 新增 `history_cleanup.include_compressed_in_watermark` 配置项（默认为 `false`）。
  - 为 `false` 时，已生成的 `[历史浏览摘要]` 不计入水位统计，亦不参与后续重压缩；
  - 为 `true` 时，已生成的 `[历史浏览摘要]` 计入水位统计，超限时在提示词中拼装为 `【前序历史摘要】` 参与新一轮滚动聚合压缩。
- **代码与测试清理**：
  - 移除原逐组切分方法 `group_tool_calls` 及旧版循环压缩实现，同步清理过时的单测用例，维持代码简洁。

---

## [v1.4.2] - 2026-11-27

### 工具执行切面消减机制与全场景支持 (Pre-Tool Execution History Cleanup & Subagent Support)
- **切面注入至四大复合工具 (`FunctionTool.call`)**：将 `self.history_cleaner` 直接注入至 `pw_page`、`pw_read`、`pw_interact`、`pw_media` 四大复合工具中，在工具执行前通过前置切面检查并就地消减上下文历史。
- **全场景代理运行支持（主代理与子代理一致性）**：全面支持 AstrBot 子代理编排（如 `transfer_to_researcher`、`SpawnAgentTool` 等）。由于子代理内部工具调用由 `ToolLoopAgentRunner` 直接驱动工具 `call(context, **kwargs)`，切面拦截直接获取并操作子代理运行时的 `run_context.messages`，在子代理多步读取网页累积长上下文时，于下次工具执行前及时压缩释放。
- **架构极简收敛**：移除 `main.py` 中过渡性的 `@filter.on_using_llm_tool`、`@filter.on_agent_begin` 与 `@filter.on_agent_done` 监听钩子及 `event.set_extra` 依赖，消减器仅专注于本插件核心工具，主入口代码高度精简。
- **多态上下文与 ContentPart 支持**：`HistoryCleaner.process_contexts` 多态兼容 `list[Message]`、`run_context` 与 `req.contexts`；`_get_content` 支持多部件（`ContentPart` / `TextPart`）文本提取。

---

## [v1.4.1] - 2026-11-27

### 历史清理实时运行日志与双重审计持久化 (History Cleanup Real-Time Logging & Dual-Audit Persistence)
- **全流程实时运行日志**：`HistoryCleaner` 在执行高低双水位线历史消减全过程中，全程输出标准 `logger.info` 与 `logger.warning` 规范化日志，包含高水位超标触发、逐组消减进度、副 AI 压缩调用与字符节省率统计、副 AI 失败平滑降级提示以及上下文最终字符消减汇总。
- **双重审计落盘体系与数据持久化**：
  - **工具调用审计 (`tool_audit_logs`)**：通过 `AuditLogger.log_action` 记录 `pw_history:compress` 或 `pw_history:delete` 动作，记录消减组索引、工具调用数量、原始字符、压缩后字符及执行耗时。
  - **生命周期审计 (`context_lifecycle_logs`)**：通过 `AuditLogger.log_lifecycle` 记录 `history_compress` 或 `history_cleanup` 事件，将消减策略、水位线阈值、节省字符数、副 AI 提供商等结构化元数据持久化落盘，与会话生命周期审计深度对齐。

---

## [v1.4.0] - 2026-11-27

### 纯双水位线工具历史消减与副 AI 压缩 (Double Watermark Tool History Cleanup & Compression)
- **纯高低双水位线上下文消减**：新增 `history_cleanup` 配置组（`high_watermark` 与 `low_watermark`），在 `@filter.on_llm_request` 请求前拦截，当本插件历史工具调用累计字符超过高水位时，从最旧记录按 FIFO 逐组消减直至回落至低水位以内，最新完成的工具调用自然位于队尾完整保留 100% 原始明文。
- **严格 API 协议兼容（防 400 报错）**：保留 OpenAI/Gemini/Claude 等厂商要求的 `assistant(tool_calls)` 与 `tool(tool_call_id)` 结构配对，保留消息骨架并替换 `content` 内容，消除孤立消息与丢失 ID 引发的 400 异常。
- **两种消减策略与智能折叠**：
  - **直接删除模式 (`delete`)**：将历史工具消息正文原位替换为精炼占位符 `"[该历史工具调用结果已按策略清理]"`，零额外 Token 开销。
  - **副 AI 压缩模式 (`compress`)**：通过 `_special: "select_provider"` 选取模型生成紧凑摘要，组内非末尾工具填入 `"[已并入本轮浏览摘要]"`，末尾工具写入结构化摘要，因果链清晰。
- **副 AI 输入上限控制与直接截断**：新增 WebUI 配置项 `compress_max_input_chars`（默认为 0 代表不限制长度）；大于 0 时若超长直接截断并附加提示，防止副 AI 上下文膨胀。
- **人设面具融合与安全降级**：副 AI 支持配置人设面具注入（`compress_use_persona` 与 `_special: "select_persona"`，未指定时自动回退继承系统默认人设）；当副 AI 超时或抛出异常时，平滑降级为直接删除占位策略，保障主会话稳定。
- **事件流自动回写持久化**：深度契合 AstrBot 内部 `context_observer("plugin")` 触发机制，在钩子完成时自动调用 `stage_history()` 将变更持久化回写至会话数据库，避免未来轮次重复计算。

---

## [v1.3.0] - 2026-11-26

### 阅读器 Ref 规范化与按需 URL 查询 (Reader Ref Standardization & On-Demand URL Query)
- **普通图片 Ref ID 分配与 URL 隐藏**：`InlineMarkdownReader` 将页面上的普通图片（`<img>`）纳入统一的 Ref 编号管理，隐藏长图片 URL 并内联渲染为 `![图片: alt][Ref]`，防止 Token 膨胀并实现图片精准定位。
- **内联控件 Markdown 引用风排版与 JS 独立脚本解耦**：将内联交互控件与超链接升级为原生 Markdown 引用脚注风格（`[文本][Ref]`、`![图片: 描述][Ref]`、`[按钮: 文本][Ref]`），精简元素语法骨架，密集链接区域字符冗余减少约 30%；将 300+ 行 JS DOM 提取逻辑解耦抽离为独立的 `core/readers/markdown_extractor.js` 脚本。
- **表格感知智能跨页切分与表头自动回填**：`_chunk_blocks` 引入 Markdown 表格结构识别与逐行装箱机制，多行表格跨页时在后续切片首部自动注入表头行与分隔行，确保每个分页都是列语义清晰、语法自闭合的合法表格。
- **单页字符预算防膨胀与行级兜底微切分**：对超大列表、代码块与极端长文本实施行级与字符级装箱微切分兜底，防范单页快照数万字符膨胀，确保单页总字符严格受控于 `page_chunk_char_limit`（默认 2000）。
- **ARIA 语义树 URL 剥离与脱敏**：`AriaSnapshotReader` 过滤 YAML 语义树中的 `- /url: <url>` 子行与末尾多余冒号，对超链接无障碍名称本身为 URL 的情况自动化简为 `link [ref=...]`，正文大幅降低 Token 开销。
- **两款阅读器 ref_map 契约标准化**：统一 `InlineMarkdownReader` 与 `AriaSnapshotReader` 的元素映射字段（`ref`, `tag`, `role`, `type`, `name`, `text`, `alt`, `href`, `src`, `url`），ARIA 模式异步并发提取图片真实 `src`，并自动关联父级嵌套超链接。
- **`pw_read` 结构化 `ref` 详情查询**：工具 Schema 与 Handler 扩展 `ref` 参数，支持通过 Ref ID 结构化查询指定元素的类型（超链接、图片、含图链接、普通控件）、文本描述与完整目标/图片 URL，两款阅读器共享通用的分发逻辑。
- **动作执行切面空 Ref 防死等与短超时保护**：修复 `BaseActionHandler.execute_action` 在空 Ref 且无敏感输入项时误触发 DOM Locator 探测导致操作挂死 30 秒的缺陷；增加仅在存在敏感输入（`text`/`value`/`password`）且 Ref 有效时探测，并为探测添加 500ms 快速超时保护。

---

## [v1.2.0] - 2026-11-22

### 浏览器生命周期与进程空闲回收 (Browser Lifecycle & Process Reclamation)
- **底层浏览器进程智能空闲回收**：新增 `runtime.browser_idle_timeout_minutes` 配置项（默认 5 分钟），无活跃上下文超过设定时间后自动关闭底层 Chromium/Camoufox 进程（`adapter.stop()`），释放系统常驻内存；后续请求透明按需重新拉起。
- **底层浏览器失联崩溃感知与自愈**：通过 Adapter 监听 Playwright 底层 `disconnected` 事件，在外部信号强杀或进程崩溃时触发断开回调，主动清理僵尸上下文映射，记录 `terminate (reason="browser_crash")` 审计，保障后续调用透明重启服务。
- **四大关键生命周期全覆盖审计与规范日志**：
  - 对“主动释放（`close`）”、“超时回收（`timeout`）”、“强制杀死（`kill`）”与“插件终止（`terminate`）”四大流转环节实现审计记录全覆盖与日志记录；
  - 审计详情结构化记录上下文存活时长（`duration_seconds`）、标签页数量（`tab_count`）及最终页面 URL（`final_url`）。
- **插件退出与重载的超时熔断与 atexit 兜底保护**：
  - 优化主插件 `terminate()`，成对注销 `atexit` 钩子，通过 `ContextManager.close_all_contexts(reason="terminate")` 实施 `asyncio.gather` 并发 5.0 秒总超时熔断；
  - 底层驱动关闭施加 5.0 秒超时安全守卫，结合 `atexit.register` 注册异常退出清理钩子，避免产生孤儿进程。

### 安全权限与会话协同演进 (Security Permissions & Collaborative Sessions)
- **12 项原子化操作权限细分与白名单放行**：新增动作级细粒度权限校验（`click`, `fill`, `select`, `hover`, `focus`, `drag`, `press_key`, `scroll`, `screenshot`, `screenshot_full`, `download`）；白名单放行时基于 `is_navigation_request` 拦截顶层导航，自动保留网页内部第三方资源（如静态样式、脚本、图片、CDN 等），防止页面崩坏。
- **会话模式管理员特权越权防护**：修复共享会话模式下非管理员用户可能通过共享上下文盗用管理员身份的问题，在动作执行中严格按当前实际操作人 `sender_id` 进行动态权限预检。
- **邀请协助委托模型与权限继承**：明确个人隔离模式（`personal`）下由被协助者（上下文所有者）主动发起 `/browser invite` 邀请，受邀协助者通过 `/browser use` 切换后以被协助者的权限与身份协同操作，并在审计日志中严格区分 `owner_id` 与 `operator_id`。

### 并发控制与服务共享基座 (Concurrency & Cross-Plugin Service Base)
- **单上下文排队互斥创建锁 (`_creation_locks`)**：针对相同会话/用户并发请求进入时可能重复创建多个底层 BrowserContext 的竞态问题，实现基于 Context Key 的细粒度异步排队锁。
- **跨标签页单调递增 PID 式 Ref ID 分配**：引入单上下文异步排队锁 `ref_lock`，保证并发提炼正文或多标签页操作时 Ref ID 严格单调递增，避免元素编号冲突。
- **跨插件 Playwright 共享服务基座 (`PlaywrightServiceAPI`)**：基于 AstrBot Star 机制向其他插件开放浏览器上下文申请、复用与生命周期管理能力，实现生态内插件共享同一个底层 Playwright 驱动。
- **异常分级治理与官方 Logger 强化**：全面移除静默 `pass`，完整记录异常 traceback 调用栈；全模块严格仅采用 `from astrbot.api import logger`。

---

## [v1.1.0] - 2026-11-22

### 健壮性与架构重构 (Robustness & Architecture Refactor)
- **Ref ID 字符串化与单调递增**：所有工具入参、内部数据结构及 Schema 中的 `ref` 全面统一为字符串类型（如 `'1'`, `'e1'`）；Markdown 模式由上下文统一管理单调递增计数器（递增上限 1,000,000 后安全回滚至 0），向 DOM 注入 `data-astr-ref`，避免历史元素序号冲突；ARIA 模式无缝对接官方 Ref。
- **Playwright 官方 ARIA 引擎原生替换**：移除自定义 JavaScript 递归遍历 DOM 脚本，原生调用 `page.locator(':root').aria_snapshot(mode='ai')` 与 `aria-ref=` 选择器，大幅提升无障碍语义树快照提取的解析准确性与性能。
- **全链路密码安全脱敏流水线**：表单填入敏感信息时，根据元素属性探测 `type == 'password'`，开启配置后在审计记录入参、调用日志与大模型返回结果中均将敏感密码值替换为 `******`，防止凭据泄露。
- **BaseActionHandler 模板方法切面收敛**：抽取通用动作执行切面基类，通过统一的 `execute_action()` 模板方法收敛上下文寻址、权限预检、稳定等待、业务执行、密码脱敏、异常清洗及审计日志落库，消除各 Handler 中的模板代码冗余。
- **历史死代码清理**：移除已废弃的 `core/page_extractor.py`（500+ 行）及过期单测，清理向后兼容的历史遗留别名与接口。
- **页面就绪等待守卫 (Page Stabilization)**：在导航与页面读取前引入两阶段稳定等待，结合 `domcontentloaded` 与带有 1.5 秒超时熔断机制的 `networkidle` 状态检测，有效防止异步页面未渲染空白及长轮询挂起。
- **四重快照自动失效机制**：实现主 Frame 导航监听（`framenavigated`）、URL 状态偏离比对、交互状态变更脏标记（`is_snapshot_dirty`）以及 60 秒 TTL 衰减，确保操作基于新鲜页面状态。
- **上下文创建异常自动回滚**：`ContextManager` 在创建浏览器上下文过程中若遭遇路由绑定、页面创建或监听器注册失败，自动执行回滚清理关闭底层上下文，防止孤儿进程与内存泄漏。

### 平台合规改进 (Platform Compliance)
- **插件专属数据持久化路径规范**：将审计数据库（`audit.db`）、文件下载目录（`downloads/`）、临时截图（`screenshots/`）与审计截图（`audit_screenshots/`）全部收敛迁移至 AstrBot 插件规范目录 `data/plugin_data/astrbot_plugin_playwright_tools/`。
- **统一 Logger 规范化治理**：移除所有模块中对标准库 `logging` 的回退导入，全插件严格遵循平台规范仅通过 `from astrbot.api import logger` 获取日志器。

---

## [v1.0.0] - 2026-11-21 (正式公开发布)

### 核心亮点与全功能正式发布 (Official Public Release)
- **四大聚合复合工具体系**：全面收敛为 `pw_page`（页面打开与状态控制）、`pw_read`（结构化正文与交互元素提取）、`pw_interact`（全功能键鼠与表单交互）、`pw_media`（多媒体截图交付与文件下载），采用 AstrBot `FunctionTool` 原生强类型注册。
- **元素编号（Ref ID）与精准定位**：精简网页 DOM 树并为所有可交互控件赋予专属自增编号（如 `[1] [按钮] 登录`），告别脆弱且高 Token 消耗的选择器，保证大模型定位精准度。
- **双正文提炼模式与字符预算分页**：
  - **内联交互 Markdown (Inline Markdown)**：默认推荐，将网页正文标题排版、列表、表格、嵌入图片与带 Ref ID 的可交互控件内联熔接为结构化 Markdown，所见即所得。
  - **无障碍语义树快照 (ARIA Snapshot)**：基于浏览器原生 Accessibility Tree 生成严密的语义角色层级树。
  - **长页面自适应分页**：基于字符预算预算（`page_chunk_char_limit`）平滑切分超长文档，支持 `page` 页码翻阅与 `keyword` 关键词定向定位。
- **原生键鼠交互与智能报错脱敏**：
  - 支持点击、文本填充、下拉选择、鼠标悬停（hover）、焦点管理（focus/blur）、元素拖拽（drag）、键盘按键及平滑滚动。
  - Playwright 原生 Locator 体系，自动剥离底层冗余指针跟踪日志，遇到超时、弹层遮挡时输出单行脱敏提示并自动附加下一步行动建议（`[推荐操作: ...]`）。
- **多租户隐私隔离与细粒度安全白名单**：
  - **隔离模式**：个人专属隔离（`personal`）与会话共享（`session`），支持指令邀请好友协同操作及空闲定时回收释放。
  - **白名单防护**：支持域名通配符（如 `*.github.com`）与操作权限多选绑定，拦截未授权跳转与外域 iframe 导航。
  - **密码防泄漏**：可配置 `mask_password_inputs` 自动将敏感密码输入框替换为 `******`。
- **统一 MD3 网页控制台与 SQLite 实时审计**：
  - 在 AstrBot 后台集成 Material Design 3 大圆角风格独立管理视图（`views/browser/`），具备内存路由无缝切换“操作审计”与“会话生命周期”面板。
  - 审计日志全量落盘，支持多维检索、CSV/JSON 导出、带安全确认的一键清空及 Base64 截图大图检视。
- **双驱动适配器引擎**：
  - 首选 **Camoufox** 驱动引擎，具备高级反检测指纹伪装与可选 GeoIP 定位防检。
  - 原生支持 **Playwright** 驱动（Chromium / Firefox / WebKit / 自定义浏览器可执行文件路径）。

---

## [v0.2.1] - 2026-11-21

### 截图 401 鉴权服务 (Authenticated Data URL Screenshots)
- **Data URL / Base64 直出**：增强 `AuditApiHandler.api_audit_screenshot`，默认支持返回通过 AstrBot 宿主鉴权通道获取的 Base64 Data URL（`data:image/png;base64,...`），规避 iframe 原生 `<img>` 标签因无法携带 Bearer Token 而被 401 拦截的问题；同时支持 `format=raw` 保持二进制流直出兼容。
- **大图查看与独立下载**：前端侧边抽屉与手动截图弹窗全面支持大图窗口独立渲染与本地下载。

### 浏览器可执行文件自定义 (Custom Browser Executable Path)
- **新增配置项 `browser_executable_path`**：在 `_conf_schema.json` 中提供通用的 `browser_executable_path` 选项，支持用户手动指定 Playwright 适配器对应的浏览器二进制可执行文件路径；若留空则平滑回退至环境中默认安装的浏览器。
- **适配器工厂与启动透传**：`AdapterFactory` 与 `PlaywrightAdapter` 深度对接该配置项，并在 `launch(executable_path=...)` 中安全生效。

### Web 前端现代化与架构重构 (CSS Modules & Centralized API Client)
- **样式全面解耦 (CSS Modules)**：采用 Vite 原生支持的 `*.module.css`，为所有 Views（`AuditView`、`LifecycleView`）与 Components（`TopAppBar`、`StatsOverview`、`AuditCard`、`SideDrawer`、`ConfirmDialog`、`Navbar`、`App`）抽离独立模块样式文件，全面移除 JSX 内联硬编码 `style={{ ... }}`，零新增 npm 依赖。
- **统一 API 客户端层**：在 `web-src/src/api/` 下抽取集中式的 API 模块（`client.ts`、`audit.ts`、`lifecycle.ts`），统一封装 Bridge 探测与类型定义。

### 死代码与过期测试清理 (Dead Code & Legacy Test Cleanup)
- **移除废弃 V1 工具**：安全删除 `tools/action_tools.py`、`tools/browse_tools.py`、`tools/dialog_tools.py`、`tools/media_tools.py`，项目工具层全面由 `handlers/` 与复合 FunctionTool 承担。
- **清理过期测试与空文件**：删除 `tests/_test_async.py` 与 `tests/test_tools.py`，全量单元测试（136 项）秒级通过。

---

## [v0.2.0] - 2026-11-20

### 页面阅读体验与独立分页 (Structured Content & Independent Pagination)
- **结构化 Markdown 正文提炼**：网页正文提炼全面支持提取 `#` 一级标题、`##` 二级标题、`###` 三级标题、段落、列表项及表格 Markdown 语法，消除散碎短行与排版割裂。
- **正文与控件分流独立分页 (`target`)**：`pw_page` 的 `read` 与 `search` 动作支持 `target="all" | "text" | "elements"`（默认 `all`）。大模型可指定 `target="text"` 独立连贯通读文章长篇，或指定 `target="elements"` 专注文档交互控件。
- **可操作元素换行平整化**：可交互控件内的换行符自动归一化单行展示，支持在配置项中自定义连接分隔符 `element_multiline_separator`（默认 `' | '`）。
- **无状态提炼与多租户隔离**：`PageExtractor` 保持无状态单例，各会话快照独立保存在各自的 `ManagedContext.snapshot_data`，保障高并发与多租户隔离。

### 交互报错精炼与操作推荐 (Sanitized Errors & Next-Action Guidance)
- **Playwright 底层报错脱敏与精炼**：编写 `clean_playwright_error`，剥除 Playwright 内部 `Call log:` 及指针拦截冗余日志，对超时、弹层遮挡（`<dialog open>`）、元素失联等场景精简为一句话中文提示。
- **智能下一步行动指引**：在页面打开、阅读完结、元素点击、表单提交及拦截报错后，自动注入针对性 `[推荐操作: ...]` 指引，降低大模型幻觉与无效重试。

### 真实审计落盘与 WebUI 升级 (Real Audit Outputs & Visual Inspector)
- **真实输出与截断配置**：修复审计日志仅记录开始占位符的问题，全面记录真实执行结果；支持配置 `audit_max_output_chars`（默认 `0` 不限，大于 0 时自动截断并附带标记）。
- **截图安全持久化与预览**：新增配置 `audit_save_screenshots`（默认 `true`），仅对 `pw_media` 截图动作落盘至 `data/audit_screenshots/` 并记录相对路径；Web API 提供带目录越界防护的图片服务接口 `GET /{plugin_name}/audit/screenshot`。
- **Web API 分页与离线预览修复**：实现 `extract_query_param` 支持 `args` / `query_params` / `query` 多源参数提取，修复 AstrBot Dashboard 下分页停留在第 1 页的缺陷；前端抽屉支持完整输出检视、复制与截图缩略图展开查看。

### 架构原生重构 (Playwright-Native Architecture Refactor)
- **原生 Playwright 交互体系**：将 `InteractHandler` 中所有点击、表单输入、下拉选择、悬停、聚焦/失焦、拖拽动作重构为 Playwright 原生 Locator API 调用（`locator.click()`、`locator.fill()`、`locator.select_option()`、`locator.drag_to()` 等），全面享受框架自带的可操作性检查与受控组件事件分发，移除裸 JS 字符串注入。
- **解耦浏览器后端适配器**：将 `CamoufoxAdapter` 与通用 `BrowserAdapterBase` 解耦，将其职责定位为单一的底层浏览器启动器，向上层输出标准的 Playwright `Browser` 与 `BrowserContext`，消除对 Camoufox 的专有强绑定。
- **强类型与官方日志规范**：核心会话上下文与 Handlers 引入 `playwright.async_api` 强类型约束；日志全面采用 AstrBot 官方标准的 `from astrbot.api import logger`。
- **精简测试架构**：移除冗余笨重的端到端集成测试，保留纯净快速的完整单元测试套件（89 项用例秒级通过）。

---

## [v0.1.2] - 2026-11-20

### 稳定性与测试基建 (Stability & Test Infrastructure)
- **真实浏览器端到端测试套件 (Real Browser E2E)**：新增 `tests/e2e/test_real_browser.py` 与本地内置测试静态页夹具（`tests/e2e/fixtures/`），在本地真实 Camoufox 无头环境下全链路自动化测试 `pw_page`、`pw_interact`、`pw_media` 的打开、阅读、搜索、表单输入、按钮点击、下拉选择、页面滚动、Alert 弹窗处理、多标签页切换（`target="_blank"` 与 `switch_tab`）、视口与整页长截图及资源安全释放。
- **规范包导入路径修复**：修正单元测试中遗留的顶层模块导入路径，统一通过标准包路径导入，解决测试运行时的相对导入越界异常，实现全量 85+ 单元测试绿灯通过。
- **异常 Traceback 完整日志保全**：在 Handlers 各动作与顶层 `_execute_with_timeout` 中强化异常捕获，记录完整调用栈信息，避免单行简短异常导致的排查困境。
- **标签页缺省参数修复**：将 `_action_switch_tab` 缺省索引修复为 `1`，与全系统 1-based 语义对齐。
- **依赖声明与规范入宪**：提供标准 `requirements.txt`；在 `AGENT.md` 强制设立硬性规范：代码修改后必须在本机实际执行真实浏览器 E2E 测试并验证通过。

---

## [v0.1.1] - 2026-11-20

### 修复与重构 (Bug Fixes & Refactoring)
- **修复工具协程调用异常**：修复 `tools/tools.py` 中 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 的 `call()` 方法误用异步生成器（`yield`）导致 AstrBot `FuncToolWrapper.call()` 执行抛出 `TypeError: object async_generator can't be used in 'await' expression` 的问题，全面恢复为标准协程（`return`）。截图直发聊天场景改为异步调用 `event.send` 推送图片，同时返回说明文本给大模型。
- **Web API 独立模块化重构**：根据单一职责原则，将原写在 `main.py` 中的审计相关 Web API 路由与业务逻辑（`api_audit_logs`、`api_audit_stats`、`api_audit_export`、`api_audit_clear`）剥离至新建的独立模块 `api/audit_api.py`，`main.py` 仅负责实例化与路由委托挂载。
- **前端 Bridge 响应自适应与构建刷新**：修复 `web-src/src/App.tsx` 在接收 AstrBot Bridge 解包数据时因硬编码检查 `res.code === 0` 导致一直报错“拉取日志失败”的问题，全面自适应 Bridge 解包后的对象结构与标准包裹结构，并重新执行构建将更新后的静态资源同步更新至 `views/audit/`。

---

## [v0.1.0] - 2026-11-20

### 新增与增强 (Features & Enhancements)
- **可视化审计视图 (Visual Audit View)**：在 `metadata.yaml` 声明独立插件页面（`target: plugin_page`），源码采用 Yarn + Vite + React 18 + TS 组织于 `web-src/` 并编译至 `views/audit/`。
- **Material Design 3 大圆角交互设计**：自研轻量级 MD3 组件，采用 16~24px 大圆角与表面色彩体系，自适应 AstrBot 宿主深浅色主题。
- **长文本两行截断预览与右侧抽屉检视**：列表卡片以代码块展示入参单行摘要与输出前 2 行文本，点击任意卡片从右侧平滑滑出大圆角抽屉（Side Drawer Inspector），支持格式化 JSON 树展示、完整结果换行检视与一键快捷复制。
- **审计数据增强与全链路透传**：工具调用链路中纯内存被动探测群聊名称与发送者昵称（私聊标记为 `私聊: {sender_name}`），全链路透传写入 SQLite 审计表。
- **运维与统计管理 Web API**：通过 `context.register_web_api` 注册多维条件检索（`/audit/logs`）、实时指标统计（`/audit/stats`）、全量/筛选日志导出（`/audit/export`，支持 JSON 与 RFC 4180 CSV）及带二次确认的安全清空（`/audit/clear`）。

---

## [v0.0.2] - 2026-11-19

### 优化与重构 (Refactoring)
- **工具方法字典映射分发**：移除 `tools/tools.py` 中三大工具 `call()` 内的 `if-elif-else` 长分支，重构为通过 `self._actions` 字典映射到私有动作方法。
- **统一异步生成器产出**：所有复合工具的 `call()` 统一设计为异步生成器（`yield` 产出结果）。
- **截图消息直发防覆盖**：`pw_media` 截图发送给聊天用户时，改用 `yield event.image_result(path)` 直接交付且立即退出，不再返回额外文本，防止后续消息在聊天界面覆盖图片。

---

## [v0.0.1] - 2026-11-19

### 新增与重构 (Features & Enhancements)
- **类型化大工具聚合**：由分散的原子工具收敛为面向对象的复合工具，继承 AstrBot `FunctionTool` 规范并通过 `context.add_llm_tools` 统一以 `pw_` 前缀注册。
- **高级交互操作补齐**：补齐鼠标悬停（`hover`）、元素聚焦（`focus`）、元素失焦（`blur`）、元素拖拽（`drag`）及键盘按键（`press_key`）支持。
- **双重截图熔断机制**：提供视口截图（`screenshot_viewport`）与全页面长截图（`screenshot_full`）；长截图支持配置最大高度限制（默认 8000px，超限截断）与超时熔断（默认 15s，超时自动降级为视口截图）。
- **单工具执行全局超时保护**：每个工具调用封装 `asyncio.wait_for` 超时拦截（默认 30s），超时立即强制中断并返回友好反馈。
- **系统提示词动态注入**：增加 WebUI 配置项 `system_prompt_injection`，通过 `@filter.on_llm_request()` 钩子在大模型请求前动态注入（留空则不注入）。
- **页面内容关键字检索**：新增快速搜索包含目标词的文本块及邻近 Ref ID。
- **多租户隔离与权限审计**：
  - 支持个人隔离模式与会话共享模式，提供 `/browser invite/use/close/status` 管理指令。
  - 支持域名通配符与动作级白名单管控。
  - SQLite 记录全生命周期审计日志并支持周期性自动清理。
