# 历史工具调用单批次聚合压缩设计规范 (Batch History Compression Design Spec)

## 1. 概述与设计背景

### 1.1 背景
在 AstrBot 的多轮大模型调用或子代理编排中，每调用一次工具通常会产生 `User -> Assistant(tool_call) -> Tool(result) -> Assistant(tool_call) -> Tool(result)...` 的消息链条。
旧版 `HistoryCleaner` 采用按相邻工具调用切组并逐组遍历调用副 AI 的方案。在子代理或跨轮次场景中，每组仅有 1 个工具调用，当积攒了十数次工具调用超过高水位时，会连续触发多达数十次副 AI 调用，产生极高的请求延迟（数十秒）甚至造成小模型输出摘要反向膨胀。

### 1.2 目标
1. **单次聚合消减 (Single-Pass Batch Compression)**：
   当对话中插件工具总字符数超过 `high_watermark` 时，计算降至 `low_watermark` 所需消减的字符量，按 FIFO（从旧到新）一次性聚集足够的历史工具调用，仅发起 **1 次** 副 AI 请求完成全局结构化压缩；若配置为直接删除策略或压缩失败降级，则批量写回删除占位符。
2. **历史摘要计入水位可选项 (`include_compressed_in_watermark`)**：
   在配置项中提供布尔开关 `include_compressed_in_watermark`（默认 `false`）：
   - `false`：历史已生成的 `[历史浏览摘要]` 不计入水位统计，也不参与后续滚动重压缩；
   - `true`：`[历史浏览摘要]` 计入水位统计，超限时作为候选块与后续新工具调用合并滚动重压缩。
3. **彻底清理无用旧实现与旧测试**：
   彻底移除逐组循环压缩逻辑与冗余兼容代码，保持实现轻量高效与 100% 测试覆盖。

---

## 2. 详细设计与规范

### 2.1 配置模式 (`_conf_schema.json`)
在 `history_cleanup.items` 下增加配置项：
```json
"include_compressed_in_watermark": {
  "type": "bool",
  "description": "历史摘要计入水位",
  "hint": "开启后，此前已生成的 [历史浏览摘要] 也将计入水位统计并在再次超限时参与滚动重压缩；关闭后已压缩摘要不计入水位且不再重复压缩",
  "default": false,
  "condition": {
    "enable_cleanup": true
  }
}
```

### 2.2 核心逻辑 (`core/history_cleaner.py`)

#### 2.2.1 候选条目判定与字符统计
定义常量：
- `DELETE_PLACEHOLDER = "[该历史工具调用结果已按策略清理]"`
- `MERGE_PLACEHOLDER = "[已并入本轮浏览摘要]"`
- `SUMMARY_PREFIX = "[历史浏览摘要]"`

条目有效性判定规则：
- 属于本插件四大核心工具 (`pw_page`, `pw_read`, `pw_interact`, `pw_media`)。
- 若内容以 `DELETE_PLACEHOLDER` 或 `MERGE_PLACEHOLDER` 开头：永久忽略，不计入水位，不参与消减。
- 若内容以 `SUMMARY_PREFIX` 开头：
  - 当 `include_compressed_in_watermark == True`：计入水位，可被选入聚合消减批次；
  - 当 `include_compressed_in_watermark == False`：不计入水位，不参与后续消减。
- 其余普通工具返回内容：正常计入水位，参与消减。

#### 2.2.2 批次收集算法 (FIFO 贪心收集)
1. 计算当前总有效字符数 `current_chars = self.calculate_uncompressed_chars(contexts)`。
2. 若 `current_chars <= self.high_watermark`，不触发消减，返回 `False`。
3. 从前到后遍历 `contexts` 中的所有消息，找出所有符合上述有效性判定的工具消息索引 `idx`：
   - 累加字符数 `accumulated_chars += len(content)`；
   - 加入候选列表 `batch_indices.append(idx)`；
   - 当 `current_chars - accumulated_chars <= self.low_watermark` 时终止遍历。
4. 若 `batch_indices` 为空，返回 `False`。

#### 2.2.3 批量压缩与写回
- **副 AI 提示词拼装**：
  对 `batch_indices` 中每个消息：
  - 若为普通工具调用：`【工具: {tool_name}】\n{content}`
  - 若为前序历史摘要：`【前序历史摘要】\n{content去除前缀}`
  以双换行 `\n\n` 拼接。
  若配置了 `compress_max_input_chars > 0` 且总文本超长，截断并附加 `\n...[超出副 AI 最大输入限制，已截断]`。
- **发起单次副 AI 请求**：
  调用 `provider.text_chat(...)`。
- **写回规则**：
  - 成功时：`batch_indices` 中前 `0` 到 `N-2` 个工具消息内容写为 `MERGE_PLACEHOLDER` (`[已并入本轮浏览摘要]`)；最后一个（第 `N-1` 个）写入 `f"{SUMMARY_PREFIX}:\n{summary}"`。
  - 失败或直接删除模式：`batch_indices` 中所有工具消息内容直接写为 `DELETE_PLACEHOLDER` (`[该历史工具调用结果已按策略清理]`)。

#### 2.2.4 审计日志对齐
- **工具调用审计 (`tool_audit_logs`)**：
  - 压缩：`tool_name="pw_history:compress"`, `input_args={"batch_size": len(batch_indices), "tools": tool_names, "original_chars": accumulated_chars, "preview": preview}`, `output_result=summary`
  - 删除 / 降级：`tool_name="pw_history:delete"`, `input_args={"batch_size": len(batch_indices), "tools": tool_names, "freed_chars": accumulated_chars}`, `output_result=DELETE_PLACEHOLDER`
- **生命周期审计 (`context_lifecycle_logs`)**：
  - 压缩：`event_type="history_compress"`, `operator_name="副AI压缩器"`
  - 删除：`event_type="history_cleanup"`, `operator_name="历史清理器"`
  - `details` 包含 `high_watermark`, `low_watermark`, `before_chars`, `after_chars`, `reduced_chars`, `batch_size`, `strategy`。

---

## 3. 验证与测试规范

1. **配置架构测试**：验证 `include_compressed_in_watermark` 字段属性、默认值与条件联动。
2. **字符统计与候选判定测试**：
   - `include_compressed_in_watermark=False` 时，已存在 `[历史浏览摘要]` 不计入字符数。
   - `include_compressed_in_watermark=True` 时，已存在 `[历史浏览摘要]` 计入字符数。
3. **单批次聚合压缩测试**：
   - 构造跨多轮、包含 5 个以上工具调用的上下文，总字符数 > 高水位。
   - 验证副 AI 提供商的 `text_chat` **仅被调用恰好 1 次**。
   - 验证前 N-1 个消息被替换为 `[已并入本轮浏览摘要]`，最后 1 个被替换为结构化摘要。
4. **滚动重压缩测试**：
   - 当 `include_compressed_in_watermark=True` 时，前序摘要被包含在新的聚合输入中（带有 `【前序历史摘要】` 标识）。
5. **失败自动降级测试**：
   - 副 AI 报错时，整批候选消息均优雅降级替换为 `[该历史工具调用结果已按策略清理]`。
