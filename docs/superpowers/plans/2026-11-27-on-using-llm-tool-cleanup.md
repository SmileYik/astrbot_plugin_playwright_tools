# 网页工具调用前上下文消减与压缩实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将工具调用历史双水位线消减与副 AI 压缩的触发时机从 `on_llm_request` 迁移至 `on_using_llm_tool`，实现仅对本插件四大核心工具前置触发，并在 Agent 运行期间精准处理 `run_context.messages`。

**Architecture:** 
1. 在 `main.py` 中注册 `@filter.on_agent_begin` 捕获 `run_context` 并保存在 `event._extras` 中，在 `@filter.on_agent_done` 中清理。
2. 在 `main.py` 中注册 `@filter.on_using_llm_tool`，校验 `tool.name` 是否属于 `PLUGIN_TOOLS`，提取 `run_context.messages` 并委托给 `HistoryCleaner.process_contexts`。
3. 升级 `core/history_cleaner.py` 的 `process_contexts` 和 `_get_content`，使其多态兼容 `run_context.messages`、`req.contexts` 以及 `ContentPart` 列表。
4. `on_llm_request` 仅保留管理员同步和系统提示词追加注入逻辑。

**Tech Stack:** Python 3.12, AstrBot Plugin Framework, asyncio, unittest.

**Spec:** `docs/superpowers/specs/2026-11-27-on-using-llm-tool-cleanup-design.md`

## Global Constraints

- 日志仅使用 `from astrbot.api import logger`，严禁 `import logging`。
- 文档与注释表述客观凝练，禁止出现绝对化词汇（如“彻底”、“根治”、“杜绝”、“完全”）。
- 单测必须 100% 通过（`python -m unittest discover tests`）。
- 白名单工具集合为 `PLUGIN_TOOLS = {"pw_page", "pw_read", "pw_interact", "pw_media"}`。

## Review Focus

1. `on_using_llm_tool` 传入非本插件工具（如 `calculator`）时直接跳过，不触发任何清理或日志。
2. `on_using_llm_tool` 传入本插件工具但 `event` 中没有 `_active_run_context` 时的防御性处理（不抛异常）。
3. `run_context.messages` 中包含 `Message` 且 `content` 为 `list[ContentPart]` 时的字符统计与提取。
4. `process_contexts` 传入原生 `list`、`run_context` 对象或 `req` 对象均能正确识别并就地消减。
5. `on_agent_done` 执行后 `_active_run_context` 被安全释放。

---

### Task 1: 升级 HistoryCleaner 支持多态上下文与 ContentPart 解析

**Files:**
- Modify: `core/history_cleaner.py`
- Test: `tests/test_history_cleaner.py`

**Interfaces:**
- Consumes: `PLUGIN_TOOLS`, `Message`, `ContentPart`
- Produces: `HistoryCleaner.process_contexts(event: Any, target: Any) -> bool`, `HistoryCleaner._get_content(msg: Any) -> str`

- [ ] **Step 1: 编写多态上下文与 ContentPart 提取的单测**

在 `tests/test_history_cleaner.py` 中添加测试用例：
1. `test_process_contexts_with_direct_list`: 验证直接传入 `list[Message]` 能正确触发消减。
2. `test_process_contexts_with_run_context`: 验证传入具有 `.messages` 属性的 `ContextWrapper` 能正确触发消减。
3. `test_get_content_with_content_parts`: 验证 `content` 为 `[TextPart(text="hello"), TextPart(text=" world")]` 时能正确提取完整字符串。

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m unittest tests/test_history_cleaner.py`
Expected: 涉及新用例的断言报错或属性不匹配。

- [ ] **Step 3: 实现 HistoryCleaner 的多态解析与 ContentPart 提取**

在 `core/history_cleaner.py` 中：
1. 更新 `process_contexts(self, event: Any, target: Any) -> bool`：
   支持从 `target`（如果是 `list` 直接使用；如果具有 `messages` 属性使用 `target.messages`；如果具有 `contexts` 属性使用 `target.contexts`）中提取列表。
2. 更新 `_get_content(self, msg: Any) -> str`：
   如果 `content` 为列表，遍历解析每个元素（如果是 `str` 直接追加；如果具有 `text` 属性或 dict 包含 `text` 则追加对应文本）。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run python -m unittest tests/test_history_cleaner.py`
Expected: 所有用例通过。

- [ ] **Step 5: 提交 Task 1 代码**

```bash
git add core/history_cleaner.py tests/test_history_cleaner.py
git commit -m "feat(cleaner): support polymorphic contexts and ContentPart extraction"
```

---

### Task 2: 在 main.py 中重构事件监听器并实现白名单工具前置消减

**Files:**
- Modify: `main.py`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: `HistoryCleaner.process_contexts`, `HistoryCleaner.is_plugin_tool`
- Produces: `@filter.on_agent_begin() async def on_agent_begin(...)`, `@filter.on_using_llm_tool() async def on_using_llm_tool(...)`, `@filter.on_agent_done() async def on_agent_done(...)`

- [ ] **Step 1: 编写 on_agent_begin、on_using_llm_tool 与 on_agent_done 的测试**

在 `tests/test_plugin_main.py` 中添加/更新测试：
1. 验证 `on_agent_begin` 能将 `run_context` 记录到 `event.set_extra("_active_run_context", ...)`。
2. 验证 `on_using_llm_tool` 针对非插件工具（如 `search`、`calculator`）不调用 `history_cleaner.process_contexts`。
3. 验证 `on_using_llm_tool` 针对插件工具（如 `pw_read`）正确调用 `history_cleaner.process_contexts` 并传入 `run_context.messages`。
4. 验证 `on_agent_done` 能将 `_active_run_context` 重置为 `None`。
5. 验证 `on_llm_request` 保留系统提示词注入与管理员同步，不再调用 `history_cleaner.process_contexts`。

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run python -m unittest tests/test_plugin_main.py`
Expected: 新测试用例失败（因为 `on_agent_begin` / `on_using_llm_tool` 尚未定义）。

- [ ] **Step 3: 在 main.py 中实现事件监听器与逻辑**

在 `main.py` 中：
1. 导入 `@filter.on_agent_begin`, `@filter.on_agent_done`, `@filter.on_using_llm_tool`。
2. 实现 `on_agent_begin(self, event: AstrMessageEvent, run_context: Any)`：
   通过 `event.set_extra("_active_run_context", run_context)` 存储。
3. 实现 `on_using_llm_tool(self, event: AstrMessageEvent, tool: Any, tool_args: dict | None = None)`：
   检查 `tool_name = getattr(tool, "name", "")`，若不属于 `self.history_cleaner.is_plugin_tool(tool_name)` 则直接返回。
   从 `event.get_extra("_active_run_context")` 获取 `run_context`，提取 `run_context.messages` 或 `run_context`，调用 `await self.history_cleaner.process_contexts(event, target)`。
4. 实现 `on_agent_done(self, event: AstrMessageEvent, run_context: Any)`：
   通过 `event.set_extra("_active_run_context", None)` 释放。
5. 简化 `on_llm_request(self, event: AstrMessageEvent, req: Any)`：
   移除历史清理调用，仅保留 `self._sync_event_admin(event)` 和 `system_prompt_injection` 注入。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run python -m unittest tests/test_plugin_main.py`
Expected: 全部测试通过。

- [ ] **Step 5: 提交 Task 2 代码**

```bash
git add main.py tests/test_plugin_main.py
git commit -m "feat(plugin): migrate cleanup trigger to on_using_llm_tool with whitelist"
```

---

### Task 3: 更新项目文档与全套测试验证

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新架构与功能说明文档**

在 `README.md`、`docs/ARCHITECTURE.md` 与 `CHANGELOG.md` 中：
1. 说明历史消减与副 AI 压缩机制已升级为在工具执行前（`on_using_llm_tool`）精准拦截。
2. 说明白名单机制与 `run_context` 协同机制。
3. 遵循客观简明的编写规范。

- [ ] **Step 2: 运行全量单元测试套件**

Run: `uv run python -m unittest discover tests`
Expected: 基础测试 100% 通过（260+ 测试用例全部通过）。

- [ ] **Step 3: 提交文档更新与版本记录**

```bash
git add README.md docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: document on_using_llm_tool history cleanup refactor"
```
