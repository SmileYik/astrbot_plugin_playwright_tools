# 副 AI 压缩提示词用户意图占位符实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在副 AI 压缩提示词中支持 `{{user_input}}` 动态占位符，自动从上下文或事件中提取当前用户消息并替换，实现目标导向的聚焦历史摘要。

**Architecture:**
- 在 `core/history_cleaner.py` 中实现 `_extract_user_input`，逆序检索 `contexts` 中最近的 `role == "user"` 消息并提取文本（多态支持纯字符串与 `TextPart` 列表），若无则回退至 `event`；
- 在 `_resolve_system_prompt` 中支持将 `compress_prompt` 中的 `{{user_input}}` 替换为实际用户提问；
- 更新 `_conf_schema.json` 提示文案，并在 `tests/test_history_cleaner.py` 与 `tests/test_conf_schema.py` 中编写完备单元测试。

**Tech Stack:** Python 3.10+, AstrBot Agent Framework, unittest, JSON Schema.

**Spec:** `docs/superpowers/specs/2026-11-27-compress-prompt-user-input-placeholder-design.md`

## Global Constraints
- 严格遵循 AstrBot 日志规范，所有业务日志使用 `from astrbot.api import logger`。
- 所有 Python 单元测试 100% 通过（`uv run python -m unittest discover tests`）。
- 保持 100% 向后兼容：未包含 `{{user_input}}` 的静态提示词行为完全不变。

## Review Focus
1. 多态提取：`content` 为普通 `str` 或 `list[TextPart]` 时均能正确提取文本。
2. 逆序最近优先：多轮对话中存在多条用户消息时，确保提取的是最近一条。
3. 占位符替换：`compress_prompt` 中多次出现 `{{user_input}}` 时均能完整替换。
4. 安全回退：上下文和事件均无用户消息时，占位符替换为 `""`，不发生异常或残留未替换字样。

---

### Task 1: 用户消息提取与占位符替换逻辑实现 (TDD)

**Files:**
- Modify: `core/history_cleaner.py:490-590`
- Test: `tests/test_history_cleaner.py`

- [x] **Step 1: 编写单元测试**
  在 `tests/test_history_cleaner.py` 中增加测试用例：
  - 测试 `_extract_user_input` 能够从 `Message(role='user', content='hello')` 与 `Message(role='user', content=[TextPart(text='query')])` 中提取文本；
  - 测试 `_extract_user_input` 在多轮消息中提取最近一条；
  - 测试 `_resolve_system_prompt` 正确替换 `{{user_input}}`；
  - 测试无 user 消息时安全替换为 `""`。
  运行测试确认失败：`uv run python -m unittest tests/test_history_cleaner.py`

- [x] **Step 2: 在 `core/history_cleaner.py` 中实现提取与替换**
  - 新增 `_extract_user_input(self, contexts: list[Any] | None = None, event: Any = None) -> str`；
  - 更新 `_resolve_system_prompt(self, user_input: str = "") -> str`：执行 `base_prompt.replace("{{user_input}}", user_input)`；
  - 在 `_compress_batch` 中提取 `user_input` 并传入 `_resolve_system_prompt`。

- [x] **Step 3: 运行测试并验证**
  运行 `uv run python -m unittest tests/test_history_cleaner.py`，确认测试全部通过。
  运行 `uv run python -m unittest discover tests`，确认全量测试通过。

- [x] **Step 4: 提交代码**
  提交代码：`git commit -am "feat(cleaner): support {{user_input}} placeholder in compress_prompt"`

---

### Task 2: 配置模式文档更新与测试

**Files:**
- Modify: `_conf_schema.json`
- Test: `tests/test_conf_schema.py`

- [x] **Step 1: 编写测试**
  在 `tests/test_conf_schema.py` 中验证 `compress_prompt` 的 `hint` 包含对 `{{user_input}}` 的说明。
  运行测试确认失败。

- [x] **Step 2: 更新 `_conf_schema.json`**
  更新 `history_cleanup.items.compress_prompt` 的 `hint`，说明支持 `{{user_input}}` 占位符。

- [x] **Step 3: 运行测试并提交**
  运行 `uv run python -m unittest tests/test_conf_schema.py` 确认通过。
  提交代码：`git commit -am "docs(schema): document {{user_input}} placeholder in compress_prompt hint"`

---

### Task 3: 全量测试验证与文档同步

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/plans/2026-11-27-compress-prompt-user-input-placeholder.md`

- [x] **Step 1: 更新文档与变更日志**
  - 在 `CHANGELOG.md`（`[v1.4.5] - 2026-11-27`）中记录 `{{user_input}}` 动态占位符支持；
  - 在 `docs/ARCHITECTURE.md` Section 5.4 中更新提示词组装说明；
  - 勾选实现计划中的全部任务复选框。

- [x] **Step 2: 运行全量测试并提交**
  运行 `uv run python -m unittest discover tests`，确认 100% 通过。
  提交代码：`git commit -am "docs: update changelog and architecture for {{user_input}} placeholder"`
