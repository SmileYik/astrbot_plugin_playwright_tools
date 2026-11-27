# 设计文档：副 AI 压缩与工具历史清理的审计与运行日志增强

## 1. 目标与背景 (Intent & Why)

在 `v1.4.0` 中，插件引入了基于高低双水位线的工具历史清理与副 AI 结构化压缩功能。然而，在现有实现中，清理和压缩过程是以静默模式运行的，控制台缺乏直观的运行日志，系统数据库中也未记录压缩审计记录。

为了提高系统的可观测性、排错效率以及安全合规审计能力，本特性旨在：
1. **实时运行日志**：在清理触发、副 AI 压缩启动、压缩完成（原字数/压缩字数/压缩率）、异常降级及清理完成等关键节点输出清晰规范的 `logger.info` 与 `logger.warning`。
2. **持久化审计记录（双重落盘）**：
   - **上下文生命周期表 (`context_lifecycle_logs`)**：记录全流程会话维度的上下文消减事件（`history_compress` / `history_cleanup`），包含高低水位、前后字符数、消减量、调用提供商与处理批次统计。
   - **工具调用审计表 (`tool_audit_logs`)**：将每次副 AI 压缩或删除操作记录为独立的工具操作条目（`pw_history:compress` 与 `pw_history:delete`），以便在 WebUI 工具审计列表中直观审查压缩输入与副 AI 生成的提炼结果。
3. **零影响防崩卫士**：日志格式化与审计写库异常绝不阻断 LLM 核心请求链路。

---

## 2. 方案对比与选型 (Approaches)

- **方案 A（仅写入生命周期审计表）**：仅在 `context_lifecycle_logs` 中记录上下文事件。缺点是在 WebUI 首页最常用的“工具调用列表”中无法直接看到压缩记录。
- **方案 B（仅写入工具调用审计表）**：将压缩伪装为工具调用。缺点是缺少会话全局上下文生命周期流转的聚合数据。
- **方案 C（双重落地 + 全流程运行日志，已选定）**：
  - 生命周期表记录全局事件；
  - 工具审计表记录详细调用与生成内容；
  - 控制台输出规范统一的 `[HistoryCleaner]` 日志。

---

## 3. 详细设计 (Detailed Design)

### 3.1 核心组件改动

1. **`main.py`**：
   - 实例化 `HistoryCleaner` 时传入 `audit_logger=self.audit_logger`。
2. **`core/history_cleaner.py`**：
   - `HistoryCleaner.__init__(context, config=None, audit_logger=None)`：接收并保存 `self.audit_logger`。
   - 增加事件元数据提取辅助方法 `_extract_event_info(event)`：安全获取 `session_id`, `session_name`, `sender_id`, `sender_name`, `context_key`。
   - **运行日志增强**：
     - 水位触发：`logger.info(f"[HistoryCleaner] 检测到未压缩历史字符数 ({uncompressed_chars}) 超过高水位 ({self.high_watermark})，触发历史清理 (策略: {self.cleanup_strategy}, 目标低水位: {self.low_watermark})")`
     - 单组压缩开始：`logger.info(f"[HistoryCleaner] 正在调用副 AI 对第 {group_idx} 组工具历史 ({len(group)} 个调用, 共 {group_chars} 字符) 进行结构化压缩 (提供商: {prov_id})...")`
     - 单组压缩成功：`logger.info(f"[HistoryCleaner] 第 {group_idx} 组工具历史压缩成功: 原字符数 {group_chars} -> 摘要字符数 {len(summary)} (节省 {savings_pct}%)")`
     - 压缩失败降级：`logger.warning(f"[HistoryCleaner] 第 {group_idx} 组工具历史副 AI 压缩失败，自动降级为直接删除策略: {e}")`
     - 直接删除：`logger.info(f"[HistoryCleaner] 第 {group_idx} 组工具历史已按直接删除策略清理: {len(group)} 个调用, 释放 {freed_chars} 字符")`
     - 清理完成：`logger.info(f"[HistoryCleaner] 上下文历史清理完成: 初始未压缩字符 {before_chars} -> 最终未压缩字符 {after_chars} (累计消减 {reduced_chars} 字符, 处理 {processed_groups} 组)")`
   - **审计记录持久化**：
     - 单组压缩完成时，异步调用 `audit_logger.log_action(...)`：
       - `tool_name`: `"pw_history:compress"`
       - `input_args`: `{"group_size": len(group), "tools": tool_names, "original_chars": group_chars, "preview": prompt_preview}`
       - `output_result`: summary
       - `is_permitted`: True
       - `is_error`: False
     - 压缩失败降级为删除或直接删除策略时，调用 `audit_logger.log_action(...)`：
       - `tool_name`: `"pw_history:delete"` 或记录失败信息
     - 整轮清理结束后，若发生修改，异步调用 `audit_logger.log_lifecycle(...)`：
       - `event_type`: `"history_compress"` (或 `"history_cleanup"`)
       - `operator_name`: `"副AI压缩器"` (或 `"历史清理器"`)
       - `details`: 记录高低水位阈值、前后字符数、消减字符数、耗时、调用组统计等。

### 3.2 错误防御与健壮性
- 所有的 `audit_logger` 记录调用均包裹在 `try...except` 中，审计失败只输出 warning 日志，严禁影响上下文改写与大模型请求的主流程。

---

## 4. 验证计划 (Verification Plan)
1. 单元测试 `tests/test_history_cleaner.py`：
   - 验证传入 `audit_logger` 模拟对象时，成功压缩会正确触发 `log_action`（包含 `"pw_history:compress"`）以及 `log_lifecycle`。
   - 验证直接删除策略会触发相应的审计落盘。
   - 验证即使 `audit_logger` 内部抛出异常，`process_contexts` 依然正常执行并返回修改成功。
   - 验证日志输出（通过 `unittest.TestCase.assertLogs` 捕获）。
2. 集成测试 `tests/test_plugin_main.py`：
   - 验证 `main.py` 正确将 `audit_logger` 注入 `history_cleaner`。
3. 全量测试：252+ 测试 100% 通过。
