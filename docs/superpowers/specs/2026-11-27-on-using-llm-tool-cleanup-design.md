# 网页工具调用前上下文消减与压缩架构设计

## 背景与问题

在先前的实现中，上下文历史清理与副 AI 压缩被挂载于 `@filter.on_llm_request()` 事件上。然而在 AstrBot Agent 运行机制中：
1. 一次用户交互（LLM Request）触发后，Agent runner 进入内部工具调用循环（`ToolLoopAgentRunner`）。在单轮交互内，大模型可能多次连续调用工具（例如 `pw_page` -> `pw_read` -> `pw_interact`），而 `on_llm_request` 仅在 Agent 运行之初触发一次。
2. `ToolLoopAgentRunner` 独立维护 `run_context.messages` 作为其运行时的上下文（`ContextWrapper.messages`），`on_llm_request` 中的 `req.contexts` 在多步工具调用期间并不包含最新步骤的中间输出。
3. 导致大模型在同一次请求的多步工具交互中产生的大量历史内容（如 `pw_read` 提取的长篇 Markdown）无法在后续工具调用前及时得到压缩与释放。

## 设计目标与核心决策

1. **迁移触发点至 `on_using_llm_tool`**：
   - 在每次大模型准备执行工具前（`@filter.on_using_llm_tool()`）触发历史清理。
   - 此时即将执行的工具调用尚未返回，其即将产生的内容天然保持最新且不被清理；而此前产生的未压缩工具历史（包括本轮之前的工具调用以及更早轮次的工具调用）能够在本次调用前被及时检测与压缩。
2. **严格过滤白名单工具**：
   - 仅当即将调用的工具属于本插件注册的四大核心工具（`pw_page`、`pw_read`、`pw_interact`、`pw_media`）时才触发清理逻辑。其他插件或系统的工具调用予以直接放行，避免额外性能开销与潜在干扰。
3. **通过 `on_agent_begin` 暂存 `run_context`**：
   - 在 `@filter.on_agent_begin()` 中接收 `(event, run_context)`，并通过 `event.set_extra("_active_run_context", run_context)` 记录到事件的元数据字典中。
   - 在 `on_using_llm_tool` 中通过 `event.get_extra("_active_run_context")` 提取 `run_context`，获取 `run_context.messages`。
   - 在 `@filter.on_agent_done()` 中将 `_active_run_context` 清理释放，避免内存引用滞留。
4. **多态兼容的 `HistoryCleaner.process_contexts`**：
   - `process_contexts(event, target)` 支持传入 `list`（如 `run_context.messages`）、带有 `.messages` 属性的对象（如 `run_context`）或带有 `.contexts` 属性的对象（如 `req`），保持高度向下兼容性。
   - `_get_content` 增加对 AstrBot `ContentPart`（如 `TextPart`）列表的多态提取支持。
5. **提示词注入保留在 `on_llm_request`**：
   - 系统提示词动态追加注入（`system_prompt_injection`）与管理员身份同步（`_sync_event_admin`）继续保留在 `on_llm_request`，确保在请求初次发往模型时完成装配。

## 审计与日志规范

- 当消减或副 AI 压缩被触发时，完整记录 `tool_audit_logs`（`pw_history:delete` 或 `pw_history:compress`）与 `context_lifecycle_logs`（`history_cleanup` 或 `history_compress`）。
- 异常捕获记录完整调试日志，不打断大模型的正常工具执行流程。
