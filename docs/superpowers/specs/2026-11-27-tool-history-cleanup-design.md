# 工具历史记录消减与压缩设计文档 (Tool History Cleanup & Compression)

## 1. 意图与背景 (Intent & Why)

### 背景
本插件为大语言模型提供了强大的网页浏览能力（`pw_page` 页面管理、`pw_read` 正文阅读、`pw_interact` 键鼠交互、`pw_media` 视口/审计截图）。尽管阅读器中已经内置了分页机制（`page_chunk_char_limit`）以控制单次返回的峰值 Token，但在多轮对话和长链路任务中，随着工具调用次数不断积累，历史消息中的网页长文本和调用记录会使上下文窗口持续膨胀，最终导致大模型达到或超出上下文长度限制（Context Window Exceeded）或造成巨大的 Token 成本浪费。

### 意图
建立一套轻量、自动化且协议兼容的**工具历史消减与压缩机制**。当本插件的历史工具调用总字符数突破设定阈值时，自动介入将久远的历史调用进行**直接删除（安全占位）**或**通过副 AI 结构化压缩**，从而永久收敛大模型的上下文体积，同时保证关键事实不丢失、API 协议不报错。

---

## 2. 目标、非目标与反目标 (Goals, Non-goals, Anti-goals)

### 目标 (Goals)
1. **纯双水位线管理 (Double Watermark)**：
   - 支持配置**高水位（触发阈值 `high_watermark`）**与**低水位（目标回退水位 `low_watermark`）**。
   - 当历史未消减工具调用总字符超过高水位时，触发消减流程，从最旧的记录开始逐批处理，直至历史工具总字符回落至低水位以内。
2. **严格的 API 协议兼容与防 400 机制**：
   - 绝不破坏 OpenAI / Gemini / Claude 规范中 `assistant(tool_calls)` 与 `tool(tool_call_id)` 的配对完整性，无论是删除还是压缩，均保留结构并替换 `content`。
3. **两种处理策略**：
   - **直接删除模式 (`delete`)**：将超标的旧 `tool` 消息体替换为精炼占位符（如 `[该历史工具调用结果已按策略清理]`）。
   - **副 AI 压缩模式 (`compress`)**：
     - 支持在 WebUI 中通过 `_special: "select_provider"` 选取指定的副 AI 模型。
     - 支持配置自定义系统压缩提示词（提供优质默认提示词）。
     - 支持配置副 AI 单次最大输入字符（`compress_max_input_chars`，设置为 0 代表不限制长度；大于 0 时若超长则直接截断）。
     - 支持选择是否启用人设面具（`use_persona`）；若启用，可通过 `_special: "select_persona"` 指定人设，未指定时自动回退读取系统默认人设。
     - 将多步/长文本内容整合成紧凑的事实摘要并写回。
4. **当前未决与近期工具自然保护 (FIFO Drainage Protection)**：
   - 采用先进先出（FIFO）队列由最旧历史开始消减，留出充足的水位差缓冲空间，最新轮次完成的工具调用自然位于队尾得到完好保留。
5. **自动持久化 (Auto-Persistence)**：
   - 深度利用 AstrBot 底层在 `OnLLMRequestEvent` 执行完毕后的 `context_observer("plugin")` 机制，使修改后的 `req.contexts` 自动通过 `stage_history()` 提交至会话事件数据库，避免未来轮次重复计算与二次调用副 AI。

### 非目标 (Non-goals)
- 不处理非本插件注册的工具（只匹配 `pw_page`, `pw_read`, `pw_interact`, `pw_media`）。
- 不干预普通用户消息与主 AI 回复的正文内容。
- 不引入外部后台守护轮询常驻线程，仅在请求即将发送给大模型时的拦截钩子中按需执行。

### 反目标 (Anti-goals - 绝不能出现的情况)
- **严禁孤立删除 `tool` 消息或剥离 `tool_call_id`**，导致下游 API 报 400 Bad Request。
- **严禁副 AI 压缩调用自身再次触发 `on_llm_request`**，杜绝任何无限递归风险。
- **严禁对已压缩/已清理的内容重复计入水位或重复压缩**，杜绝 Token 浪费。

---

## 3. 备选方案对比与抉择 (Approaches)

### 方案 A：单轮次/单次工具独立 1 对 1 压缩
- **机制**：逐条检查历史 `tool` 消息，对超标单条记录分别调用一次副 AI。
- **缺点**：若历史有 4~5 个 `pw_read` 分页，需发起 4~5 次副 AI 请求，极大增加首字延迟（TTFT），易撞 API 并发限制，且割裂了跨页上下文。
- **结论**：放弃。

### 方案 B：固定保留 N 轮明文 + 单水位阈值
- **机制**：只看轮数（如保留最近 2 轮），其余超限直接归并。
- **缺点**：由于本插件很多工具调用是极短的操作反馈（如点击成功只占 50 字符），按“轮次”截断往往把本不需要清理的短记录误伤，而大段 `pw_read` 依然可能在受保轮次内突破 Token 预算。
- **结论**：放弃。

### 方案 C：双水位线驱动的批量/逐轮归并消减（最终选定）
- **机制**：
  - 以真实的字符总量为容量指标，设置高水位（触发）与低水位（目标）。
  - 当总字符 > 高水位时，从最旧的未压缩工具调用开始，以轮次为批次进行折叠（前面填占位，尾部填综合摘要，或全填占位），直至降到低水位以下。
- **优势**：
  - 真正反映 Token 压力（精准对标 `pw_read` 等大文本）。
  - 一旦触发清理，即可腾出足够的缓冲空间，杜绝临界点频繁抖动。
  - 批量压缩只需 1~2 次副 AI 请求，延迟低、语义连贯完整。

---

## 4. 详细架构与逻辑流程 (Detailed Architecture)

### 4.1 核心组件划分
1. **配置层 (`_conf_schema.json`)**：
   - 增加 `history_cleanup` 模块配置项（布尔开关、高低水位、策略选择、副 AI 提供商、输入长度上限、提示词、人设面具配置）。
2. **核心业务组件 (`core/history_cleaner.py`)**：
   - `HistoryCleaner` 独立类，负责：
     - 解析当前上下文中的本插件工具消息及其字符量。
     - 判断是否突破高水位。
     - 按轮次工具组从旧到新（FIFO）进行消减（直接删除占位或副 AI 压缩）。
     - 若启用压缩，检查 `compress_max_input_chars`（0 代表不限；>0 时超长则直接截断）。
     - 负责副 AI 调度、人设融合与降级容错。
     - 更新消息内容并保证消息序列协议合法。
3. **插件主入口集成 (`main.py`)**：
   - 初始化 `HistoryCleaner`。
   - 在 `@filter.on_llm_request()` 中同步管理员标识后，直接调用 `await self.history_cleaner.process_contexts(event, req)`。

### 4.2 轮次工具组划分与逐轮归并 (Turn-based Grouping & FIFO Drainage)

#### 1. 工具记录的分组逻辑
在 `req.contexts` 中，模型的一次浏览任务往往连续调用多次工具（例如先 `pw_page` 打开，后 `pw_read` 阅读）。我们以对话轮次边界（两次 `user` 消息之间，或每个包含 `tool_calls` 的 `assistant` 调用块）将连续的工具调用划分为独立的 **“工具调用组 (Tool Call Group)”**。

#### 2. 从旧到新逐组处理 (FIFO)
当统计到历史未压缩工具总字符超过 `high_watermark` 时：
1. 取出**最久远的一个工具调用组**。
2. 对该组进行消减：
   - **直接删除模式**：保持 `tool_call_id` 不变，将该组内所有 `tool` 消息的 `content` 替换为占位符 `"[该历史工具调用结果已按策略清理]"`。
   - **副 AI 压缩模式**：将该组内所有工具的调用参数及输出拼装为一段输入，由副 AI 提炼出一段精炼的轮次摘要。
     - 组内第 1 到 N-1 个 `tool` 的 `content` 替换为 `"[已并入本轮浏览摘要]"`；
     - 组内最后一个 `tool` 的 `content` 替换为 `"[历史浏览摘要]:\n{summary_text}"`。
3. 重新计算当前未消减工具总字符数。
4. **终止条件**：
   - 若总字符已降低至 `low_watermark` 以内，**立即终止处理，保留较近历史工具明文**；
   - 若依然高于 `low_watermark` 且历史中仍有未处理的旧工具组，继续取出下一个最旧的工具组进行处理；
   - 若所有候选历史工具组已全部处理完毕（例如单条大记录已无其它旧记录可压），安全退出循环（无死循环或溢出风险）。

#### 3. 局部因果链与协议安全性
- 摘要写回每个轮次工具组自身的末尾 `tool` 消息，使主 AI 在回顾历史时，每一轮的 `assistant` 回答与该轮自身的工具摘要严格对应，因果清晰。
- 每一个 `tool` 消息均保持原有的 `tool_call_id` 和 `role: "tool"`，100% 免疫各大厂商的 400 Bad Request 报错。

### 4.3 执行时机与最新记录自然保护
1. **触发时机**：AstrBot 的 `@filter.on_llm_request()` 在每次用户发送新消息、主 Agent 启动前拦截执行。此时 `req.contexts` 中的工具记录均为**已完成的前序轮次记录**。
2. **自然保护**：因为采用纯双水位线从最旧向最新（FIFO）逐组处理，且高低水位差（如 8000 -> 3000）留有充足缓冲空间，通常只需压缩 1~2 个最旧的轮次即可迅速达标，**最新一两轮的工具记录自然处于队列尾部，完好保留 100% 原始明文**供即时追问。
3. **容错兜底**：若副 AI 压缩发生超时或异常，自动降级为“直接删除（安全占位）”策略，确保主流程绝不受阻。

### 4.4 副 AI 唤起、输入截断与人设组装逻辑
1. **输入字符长度控制**：
   - 提取工具组拼接文本后，检查配置项 `compress_max_input_chars`：
     - 若 `compress_max_input_chars <= 0`：**不限制长度，全量输入**；
     - 若 `compress_max_input_chars > 0` 且字符超限：直接截断为该上限长度，并在末尾附加提示：`"\n...[超出副 AI 最大输入限制，已截断]"`。
2. **Provider 获取**：
   - 若配置了 `compress_provider_id`：调用 `self.context.get_provider_by_id(compress_provider_id)`。
   - 若未配置或获取失败：通过 `await self.context.get_using_provider_async(umo=event.unified_msg_origin)` 回退使用当前会话绑定的默认对话模型。
3. **System Prompt / 人设组装**：
   - 基础压缩指令：使用配置的 `compress_prompt`。
   - 人设面具追加：
     - 若 `compress_use_persona` 为 `True`：
       - 若配置了 `compress_persona_id`，调用 `await self.context.persona_manager.get_persona(persona_id)` 提取 `persona.system_prompt`。
       - 若未配置，读取 `self.context.persona_manager.default_persona` 获取系统默认人设。
       - 将人设提示词与压缩指令进行融合拼接。
4. **主动调用**：
   - 调用 `await provider.text_chat(prompt=batch_text, system_prompt=final_system_prompt)` 获取提炼结果。
   - 该调用直连底层模型，不经过事件钩子，安全无环。

---

## 5. 配置定义设计 (Configuration Schema)

在 `_conf_schema.json` 中定义如下字段：

```json
{
  "history_cleanup": {
    "type": "object",
    "description": "工具历史消减与压缩",
    "hint": "当大模型对话中累积的本插件工具调用字符过多时，自动执行消减或由副 AI 压缩，防止超出上下文限制",
    "items": {
      "enable_cleanup": {
        "type": "bool",
        "description": "启用历史消减",
        "hint": "开启后，将监控本插件工具调用字符并在超标时自动消减",
        "default": false
      },
      "high_watermark": {
        "type": "int",
        "description": "高水位阈值 (字符)",
        "hint": "历史工具调用总字符超过此时触发清理（建议 5000 ~ 12000）",
        "default": 8000,
        "slider": { "min": 2000, "max": 30000, "step": 500 },
        "condition": { "enable_cleanup": true }
      },
      "low_watermark": {
        "type": "int",
        "description": "低水位目标 (字符)",
        "hint": "触发清理后消减到的目标字符数（建议设为高水位的 30% ~ 50%）",
        "default": 3000,
        "slider": { "min": 1000, "max": 15000, "step": 500 },
        "condition": { "enable_cleanup": true }
      },
      "cleanup_strategy": {
        "type": "string",
        "description": "消减策略",
        "hint": "直接替换为占位符删除，或调用另外一个 AI 生成紧凑摘要",
        "default": "delete",
        "options": ["delete", "compress"],
        "labels": ["直接删除 (占位清空)", "副 AI 压缩 (总结提炼)"],
        "subtitles": ["直接将历史正文清空替换为简短占位符，零额外开销", "唤起副 AI 提取网页关键事实与操作结论，保留历史认知"],
        "condition": { "enable_cleanup": true }
      },
      "compress_provider_id": {
        "type": "string",
        "description": "压缩模型提供商",
        "hint": "选择负责执行压缩摘要的 AI 提供商；留空则使用当前会话默认模型",
        "default": "",
        "_special": "select_provider",
        "condition": { "enable_cleanup": true, "cleanup_strategy": "compress" }
      },
      "compress_max_input_chars": {
        "type": "int",
        "description": "副 AI 输入上限 (字符)",
        "hint": "送给副 AI 压缩的最大字符预算，设置为 0 代表不限制长度；大于 0 时若超出则直接截断",
        "default": 0,
        "slider": { "min": 0, "max": 50000, "step": 1000 },
        "condition": { "enable_cleanup": true, "cleanup_strategy": "compress" }
      },
      "compress_prompt": {
        "type": "text",
        "description": "压缩提示词",
        "hint": "副 AI 执行总结提炼时遵循的核心指导原则",
        "default": "你是一个精炼的内容总结器。请对以下浏览器历史操作及网页正文进行结构化提炼：保留核心事实、关键结论、数据指标及必要链接，剔除冗余修饰与排版，输出不超过 300 字的紧凑摘要。",
        "condition": { "enable_cleanup": true, "cleanup_strategy": "compress" }
      },
      "compress_use_persona": {
        "type": "bool",
        "description": "启用人设面具",
        "hint": "是否在压缩时注入人设设定",
        "default": false,
        "condition": { "enable_cleanup": true, "cleanup_strategy": "compress" }
      },
      "compress_persona_id": {
        "type": "string",
        "description": "指定人设面具",
        "hint": "选择用于压缩的人设面具；留空则自动选用当前系统默认人设",
        "default": "",
        "_special": "select_persona",
        "condition": { "enable_cleanup": true, "cleanup_strategy": "compress", "compress_use_persona": true }
      }
    }
  }
}
```

---

## 6. 留给构建者决定的工程细节 (Left to the Builder)
1. **工具过滤判定**：通过 `tool_call["function"]["name"] in {"pw_page", "pw_read", "pw_interact", "pw_media"}` 严格匹配本插件工具，其余插件工具一律放行。
2. **容错降级**：若副 AI 超时或返回空内容，自动降级为“直接删除（安全占位）”策略，确保主流程绝不受阻。
3. **单元测试矩阵**：覆盖双水位线计算、输入上限 0 不限与正数直接截断、FIFO 逐步退水退出条件、直接删除占位、副 AI 模拟调用、人设提取与注入、异常降级等完备场景。
