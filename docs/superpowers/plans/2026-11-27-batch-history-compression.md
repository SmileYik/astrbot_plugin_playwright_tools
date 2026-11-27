# 历史工具调用单批次聚合压缩实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构历史工具消减器（HistoryCleaner），将原先的逐组循环副 AI 压缩改造为单批次聚合压缩（Single-Pass Batch Compression），确保一次清理中仅向副 AI 发起恰好 1 次请求，并增加 `include_compressed_in_watermark` 配置项支持历史摘要计入水位与滚动重压缩。

**Architecture:** 当插件工具消息字符数超过高水位阈值时，按 FIFO（从旧到新）一次性聚合满足消减至低水位的候选工具消息与可选的前序历史摘要，合并拼装后以单次请求发送给副 AI，前 N-1 个条目原位写入合并占位符，最后一个条目写入聚合摘要；并在失败或直接删除模式下批量写入删除占位符。

**Tech Stack:** Python 3.10+, AstrBot Agent Framework, unittest, JSON Schema.

**Spec:** `docs/superpowers/specs/2026-11-27-batch-history-compression-design.md`

## Global Constraints
- 严格遵循 AstrBot 日志规范，所有业务日志使用 `from astrbot.api import logger`，严禁引入第三方日志框架。
- 配置架构在 `_conf_schema.json` 中定义，保持 JSON Schema 规范与联动条件有效。
- 零破坏性变动，所有单元测试必须 100% 通过（`uv run python -m unittest discover tests`）。
- 依据用户要求，无用旧实现与旧测试直接清理，不保留历史过时逻辑与兼容废代码。

## Review Focus
1. 多轮工具调用（非连续消息，夹杂 assistant/user）能正确聚合，副 AI 仅被调用恰好 1 次。
2. `include_compressed_in_watermark=False` 时，已存在的前序摘要不计入字符数且不参与再压缩。
3. `include_compressed_in_watermark=True` 时，已存在的前序摘要计入字符数并以 `【前序历史摘要】` 参与聚合重压缩。
4. 副 AI 调用异常或超时时，整批候选消息均能完整回退降级为直接删除占位符，不漏删、不异常崩溃。
5. 审计日志（`tool_audit_logs` 与 `context_lifecycle_logs`）的参数格式准确记录单批次聚合后的 `batch_size` 与相关统计字段。

---

### Task 1: 配置项 `include_compressed_in_watermark` 定义与单元测试

**Files:**
- Modify: `_conf_schema.json:421-540`
- Modify: `core/history_cleaner.py:11-45`
- Test: `tests/test_conf_schema.py`

- [x] **Step 1: 编写测试断言 `include_compressed_in_watermark` 配置项**
  在 `tests/test_conf_schema.py` 中增加测试用例，断言 `history_cleanup.items` 包含 `include_compressed_in_watermark`，默认值为 `False`，类型为 `bool`，且包含 `condition: {"enable_cleanup": True}`。
  运行测试确认失败：`uv run python -m unittest tests/test_conf_schema.py`

- [x] **Step 2: 更新 `_conf_schema.json`**
  在 `_conf_schema.json` 的 `history_cleanup.items` 中添加 `include_compressed_in_watermark` 字段定义。

- [x] **Step 3: 更新 `HistoryCleaner.__init__` 读取该配置**
  在 `core/history_cleaner.py` 的 `__init__` 中增加 `self.include_compressed_in_watermark = bool(hc_cfg.get("include_compressed_in_watermark", cfg.get("include_compressed_in_watermark", False)))`。

- [x] **Step 4: 运行测试并提交**
  运行 `uv run python -m unittest tests/test_conf_schema.py`，确认全部通过。
  提交代码：`git commit -m "feat(config): add include_compressed_in_watermark option"`

---

### Task 2: 候选条目判定与字符统计重构

**Files:**
- Modify: `core/history_cleaner.py:180-330`
- Test: `tests/test_history_cleaner.py`

- [x] **Step 1: 编写字符统计与候选判定的单元测试**
  在 `tests/test_history_cleaner.py` 中编写测试：
  - 测试 `is_candidate_tool` 在 `include_compressed_in_watermark` 分别为 `True` 和 `False` 时的行为；
  - 测试 `calculate_uncompressed_chars`（或 `calculate_watermark_chars`）在包含 `[历史浏览摘要]` 时受该配置的影响。
  运行测试确认失败。

- [x] **Step 2: 实现 `is_candidate_tool` 与更新字符统计逻辑**
  在 `core/history_cleaner.py` 中：
  - 新增 `is_candidate_tool(self, content: Any) -> bool`：遇到 `DELETE_PLACEHOLDER` 与 `MERGE_PLACEHOLDER` 始终返回 `False`；遇到 `SUMMARY_PREFIX` 返回 `self.include_compressed_in_watermark`；其余返回 `True`；
  - 更新 `calculate_uncompressed_chars`（并提供 `calculate_watermark_chars` 别名），使用 `is_candidate_tool` 进行过滤；
  - 简化 `is_processed_tool`。

- [x] **Step 3: 运行测试并提交**
  运行 `uv run python -m unittest tests/test_history_cleaner.py`，确认测试通过。
  提交代码：`git commit -m "refactor(cleaner): update candidate check and watermark calculation for existing summaries"`

---

### Task 3: 实现单批次聚合消减与单次副 AI 压缩

**Files:**
- Modify: `core/history_cleaner.py:389-663`
- Test: `tests/test_history_cleaner.py`

- [x] **Step 1: 编写单批次压缩与删除的单元测试**
  在 `tests/test_history_cleaner.py` 中编写测试用例：
  - 构造跨 3 轮以上工具调用，断言触发清理时，副 AI 提供商的 `text_chat` **恰好调用 1 次**；
  - 验证合并后的提示词包含各个工具的输入标识，或者在已有摘要时包含 `【前序历史摘要】`；
  - 验证前 N-1 个消息被替换为 `[已并入本轮浏览摘要]`，最后 1 个消息被替换为 `[历史浏览摘要]:\n{summary}`；
  - 验证失败时全部回退降级为 `[该历史工具调用结果已按策略清理]`。
  运行测试确认失败。

- [x] **Step 2: 重构 `process_contexts` 为单批次聚合**
  在 `core/history_cleaner.py` 中：
  - 计算 `current_chars = self.calculate_uncompressed_chars(contexts)`；若 `<= high_watermark` 则退出；
  - 遍历 `contexts`，按 FIFO 收集属于本插件且符合 `is_candidate_tool` 的工具消息索引 `batch_indices`，直到累积字符数使剩余字符 `<= low_watermark`；
  - 如果 `cleanup_strategy == "compress"`：拼装多项文本（支持普通工具与 `【前序历史摘要】`），单次调用副 AI；成功则前 N-1 项写 `MERGE_PLACEHOLDER`，末项写 `SUMMARY_PREFIX`；
  - 如果压缩失败或策略为 `delete`：将 `batch_indices` 中所有条目内容写入 `DELETE_PLACEHOLDER`；
  - 记录 `tool_audit_logs` 与 `context_lifecycle_logs`，将 `batch_size` 写入审计元数据；
  - 彻底移除旧版逐组循环方法 `_compress_tool_group` 与不再使用的辅助逻辑。

- [x] **Step 3: 运行全量单元测试**
  运行 `uv run python -m unittest discover tests`，修正所有因旧接口变动而受影响的测试，保证 100% 通过。

- [x] **Step 4: 提交代码**
  提交代码：`git commit -m "feat(cleaner): implement single-pass batch compression and cleanup"`

---

### Task 4: 清理旧实现与废弃测试

**Files:**
- Modify: `core/history_cleaner.py`
- Modify: `tests/test_history_cleaner.py`

- [x] **Step 1: 审查并移除无用代码**
  检查 `core/history_cleaner.py` 中无用的旧代码（如 `group_tool_calls` 若外部不再使用可清理或重构成轻量实现），检查 `tests/test_history_cleaner.py` 中已过时的测试用例。

- [x] **Step 2: 运行测试并验证**
  运行 `uv run python -m unittest discover tests`，确保无 warning 无 failure。

- [x] **Step 3: 提交清理变更**
  提交代码：`git commit -m "clean(history_cleaner): remove obsolete group-based compression logic and tests"`

---

### Task 5: 文档与架构规范更新

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [x] **Step 1: 更新架构文档与说明书**
  - 在 `README.md` 与 `docs/ARCHITECTURE.md` 中更新工具历史消减说明，强调单批次聚合压缩（Single-Pass Batch Compression）机制与 `include_compressed_in_watermark` 配置项的作用与默认行为；
  - 在 `CHANGELOG.md` 中记录本次单批次聚合压缩重构及配置项新增。

- [x] **Step 2: 运行全量测试验证与提交**
  运行 `uv run python -m unittest discover tests`。
  提交文档更新：`git commit -m "docs: update architecture and changelog for batch history compression"`
