# 压缩功能审计与运行日志增强实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为大模型上下文历史清理与副 AI 压缩功能补充多阶段实时运行日志（`logger.info`/`warning`）以及持久化双重审计记录（同时落盘至 `context_lifecycle_logs` 与 `tool_audit_logs`）。

**Architecture:** 在 `main.py` 实例化 `HistoryCleaner` 时注入全局 `audit_logger`。在 `HistoryCleaner` 中安全提取消息事件的会话与发送者元数据；在触发清理、副 AI 压缩执行、压缩成功/失败降级、直接删除及整轮清理完成等关键节点输出规范控制台日志；并通过 `audit_logger.log_action` 记录单次工具压缩/清理行为，通过 `audit_logger.log_lifecycle` 记录整轮上下文生命周期消减事件，所有审计调用均配备异常静默隔离。

**Tech Stack:** Python 3.12, AstrBot Plugin API (`from astrbot.api import logger`), SQLite3 (`AuditLogger`), `unittest`.

**Spec:** [docs/superpowers/specs/2026-11-27-compress-audit-and-logging-design.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-27-compress-audit-and-logging-design.md)

## Global Constraints

- 严禁使用标准库 `import logging`，仅能使用 `from astrbot.api import logger`。
- 审计记录与日志输出失败绝不能阻断或影响大模型请求及工具调用链路（严格的 `try...except` 隔离）。
- 保持 100% 单测通过率（当前基础测试套件 252 项全部通过）。
- 文档与版本同步：修改 `metadata.yaml` 必须同步更新 `main.py`，保持架构文档与变更日志一致。

## Review Focus

1. `event` 为 `None` 或非标准对象时，`_extract_event_info` 必须安全返回缺省值而不能抛出异常。
2. `audit_logger` 为 `None` 或其方法抛出异常时，`process_contexts` 必须平滑完成文本替换并返回 `True`。
3. 压缩返回文本极长时，写入 `tool_audit_logs` 需依赖 `AuditLogger` 自带的截断机制或安全保护。
4. 副 AI 压缩失败并降级为直接删除时，必须正确记录失败工具审计与降级生命周期审计。
5. 每次计算节省比例时，必须防止除以零异常（例如工具内容为空字符）。

---

### Task 1: HistoryCleaner 审计依赖注入与事件元数据提取

**Files:**
- Modify: `core/history_cleaner.py:10-50`
- Test: `tests/test_history_cleaner.py`

- [ ] **Step 1: 编写元数据提取与依赖注入的失败测试**
  在 `tests/test_history_cleaner.py` 中添加测试用例：
  - `test_init_with_audit_logger`: 验证 `HistoryCleaner` 接收并保存 `audit_logger`。
  - `test_extract_event_info_normal`: 验证能从包含 `unified_msg_origin`, `session_id`, `sender_id`, `sender_name` 的 mock event 中提取信息。
  - `test_extract_event_info_none_or_partial`: 验证 `event=None` 或属性缺失时不会报错且返回安全默认字典。

- [ ] **Step 2: 运行测试并确认失败**
  运行：`uv run python -m unittest tests/test_history_cleaner.py`

- [ ] **Step 3: 实现 `audit_logger` 参数与 `_extract_event_info` 方法**
  在 `core/history_cleaner.py` 中：
  - 更新 `__init__(self, context: Any, config: dict[str, Any] | None = None, audit_logger: Any = None)`。
  - 实现 `_extract_event_info(self, event: Any) -> dict[str, str]`：提取 `session_id`, `session_name`, `sender_id`, `sender_name`, `context_key`。

- [ ] **Step 4: 运行测试并确认通过**
  运行：`uv run python -m unittest tests/test_history_cleaner.py`

- [ ] **Step 5: 提交代码**
  `git add core/history_cleaner.py tests/test_history_cleaner.py`
  `git commit -m "feat(core): add audit_logger dependency and event metadata extraction in HistoryCleaner"`

---

### Task 2: 实现实时运行日志与双重审计落盘

**Files:**
- Modify: `core/history_cleaner.py:175-340`
- Test: `tests/test_history_cleaner.py`

- [ ] **Step 1: 编写审计与日志记录的失败测试**
  在 `tests/test_history_cleaner.py` 中添加用例：
  - `test_compress_audit_and_logging_success`: 验证副 AI 压缩成功时，控制台输出指定前缀日志，且 `audit_logger.log_action`（`tool_name="pw_history:compress"`）与 `audit_logger.log_lifecycle`（`event_type="history_compress"`）被异步调用且参数正确。
  - `test_compress_audit_fallback_on_error`: 验证副 AI 异常降级时，输出警告日志，并触发降级审计。
  - `test_delete_strategy_audit_and_logging`: 验证直接删除模式下，输出删除日志并记录 `tool_name="pw_history:delete"` 与 `event_type="history_cleanup"`。
  - `test_audit_logger_exception_isolation`: 当 `audit_logger.log_action` 或 `log_lifecycle` 抛出运行时异常时，`process_contexts` 不崩溃且正常返回。

- [ ] **Step 2: 运行测试并确认失败**
  运行：`uv run python -m unittest tests/test_history_cleaner.py`

- [ ] **Step 3: 在 `core/history_cleaner.py` 中实现日志与审计调用**
  - 在 `process_contexts` 中引入计数与前后字符统计。
  - 在清理触发时输出 `logger.info`。
  - 在 `_compress_tool_group` 成功/失败处输出 `logger.info` / `logger.warning`，并异步调用 `_record_tool_audit`。
  - 在直接删除处输出 `logger.info` 并调用 `_record_tool_audit`。
  - 在 `process_contexts` 结束时输出全流程统计，并异步调用 `_record_lifecycle_audit`。
  - 编写私有方法 `_record_tool_audit` 和 `_record_lifecycle_audit`，内部完整包裹 `try...except`。

- [ ] **Step 4: 运行测试并确认通过**
  运行：`uv run python -m unittest tests/test_history_cleaner.py`

- [ ] **Step 5: 提交代码**
  `git add core/history_cleaner.py tests/test_history_cleaner.py`
  `git commit -m "feat(core): implement real-time logs and dual audit recording for history cleanup"`

---

### Task 3: 在 main.py 中注入 audit_logger 与集成验证

**Files:**
- Modify: `main.py:180-200`
- Test: `tests/test_plugin_main.py`

- [ ] **Step 1: 编写 main.py 依赖注入的失败测试**
  在 `tests/test_plugin_main.py` 中更新或添加测试用例，验证插件初始化后 `self.history_cleaner.audit_logger` 等于 `self.audit_logger`。

- [ ] **Step 2: 运行测试确认失败**
  运行：`uv run python -m unittest tests/test_plugin_main.py`

- [ ] **Step 3: 修改 main.py 传入 audit_logger**
  在 `main.py` 的 `__init__` 中将 `self.history_cleaner = HistoryCleaner(self.context, self.config)` 修改为：
  `self.history_cleaner = HistoryCleaner(self.context, self.config, audit_logger=self.audit_logger)`

- [ ] **Step 4: 运行测试确认通过**
  运行：`uv run python -m unittest tests/test_plugin_main.py`

- [ ] **Step 5: 提交代码**
  `git add main.py tests/test_plugin_main.py`
  `git commit -m "feat(main): wire audit_logger into history_cleaner"`

---

### Task 4: 版本升级、文档同步与全量测试

**Files:**
- Modify: `metadata.yaml:1-5`
- Modify: `main.py:30-45`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_plugin_main.py`

- [ ] **Step 1: 升级版本号至 v1.4.1**
  - `metadata.yaml`: version -> `v1.4.1`
  - `main.py`: `__version__` -> `v1.4.1`
  - `tests/test_plugin_main.py`: `test_metadata_synced` 中的期望版本更新为 `v1.4.1`

- [ ] **Step 2: 更新说明文档与架构文档**
  - 在 `README.md` 与 `docs/ARCHITECTURE.md` 中补充关于历史压缩审计（生命周期表与工具审计表双重落盘）与运行日志的架构说明。
  - 在 `CHANGELOG.md` 中增加 `v1.4.1` 的更新条目。

- [ ] **Step 3: 执行完整测试套件**
  运行：`uv run python -m unittest discover tests`，确保所有测试（255+）100% 通过。

- [ ] **Step 4: 提交代码**
  `git add metadata.yaml main.py README.md docs/ARCHITECTURE.md CHANGELOG.md tests/test_plugin_main.py`
  `git commit -m "chore(release): bump version to v1.4.1 and update audit architecture docs"`
