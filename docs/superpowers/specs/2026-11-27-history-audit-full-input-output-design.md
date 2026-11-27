# 历史工具消减审计完整输入输出记录设计规范 (History Audit Full Input & Output Design Spec)

## 1. 概述与背景

在上下文历史消减（副 AI 压缩与直接删除）执行时，当前工具审计日志（`tool_audit_logs`）在 `input_args` 中仅记录了截断为 200 字符的 `"preview"`，导致管理员在 WebUI 审计详情中无法完整回溯压缩前发送给副 AI 的全量原始文本，也无法审计直接删除策略下被清空的具体工具历史。

本次设计旨在实现全量输入输出记录与专属排版视图：
1. **后端完整持久化**：
   - 在 `pw_history:compress` 与 `pw_history:delete` 记录中，将待消减的全部历史条目原文合并完整记录在 `input_args["original_input"]` 中，去除任何截断限制；
   - `output_result` 继续保持记录副 AI 生成的完整摘要（压缩模式）或删除占位符（删除模式）。
2. **WebUI 前端专属双栏排版视图**：
   - 在详情抽屉（`SideDrawer.tsx`）中检测 `tool_name.startsWith("pw_history:")`；
   - 提取 `original_input` 并在界面中渲染为独立的 **“消减前完整输入”** 原生多行文本卡片（带字符数统计与独立“复制完整输入”按钮）；
   - 在 **“调用输入参数 (JSON)”** 区域过滤掉超长 `original_input` 文本，保持元数据（`batch_size`、`tools`、`original_chars`、`freed_chars`）精简直观；
   - **“输出结果 / 快照内容”** 区域完整展示压缩后摘要或清理占位符。

---

## 2. 详细设计规范

### 2.1 后端设计 (`core/history_cleaner.py`)

#### 2.1.1 拼装全量输入文本
定义统一的候选条目拼装方法（复用现有的条目格式化）：
- 普通工具调用：`【工具: {tool_name}】\n{content}`
- 前序历史摘要：`【前序历史摘要】\n{body}`
- 各条目之间用 `\n\n` 分隔。

#### 2.1.2 压缩模式 (`pw_history:compress`)
在 `_compress_batch` 中：
- `full_input = "\n\n".join(contents_to_compress)`
- 成功记录审计：
  ```python
  await self._record_tool_audit(
      event_info=event_info,
      tool_name="pw_history:compress",
      input_args={
          "batch_size": len(batch_indices),
          "group_size": len(batch_indices),
          "tools": tool_names,
          "original_chars": accumulated_chars,
          "original_input": full_input,
      },
      output_result=summary,
      is_error=False,
      error_message="",
  )
  ```
- 失败降级记录审计：
  同样保存完整的 `original_input: full_input`，以便回溯副 AI 究竟是在处理什么输入时报错的。

#### 2.1.3 直接删除模式 (`pw_history:delete`)
在直接删除逻辑中：
- 遍历 `batch_indices`，按相同格式拼装被删除条目的完整内容 `full_deleted_input`；
- 记录工具审计：
  ```python
  await self._record_tool_audit(
      event_info=event_info,
      tool_name="pw_history:delete",
      input_args={
          "batch_size": len(batch_indices),
          "group_size": len(batch_indices),
          "tools": tool_names,
          "freed_chars": accumulated_chars,
          "original_input": full_deleted_input,
      },
      output_result=DELETE_PLACEHOLDER,
  )
  ```

---

### 2.2 前端 WebUI 设计 (`web-src/src/components/SideDrawer.tsx`)

#### 2.2.1 状态与属性解析
1. 解析 `item.input_args`：
   - 尝试解析为 JSON 对象；
   - 若含有 `original_input` 字段且非空：
     - 将其提取为 `originalInputText = parsed.original_input`；
     - 在深拷贝后的元数据对象中移除 `original_input` 字段，然后再格式化为 `formattedArgs`，供“调用输入参数 (JSON)”展示纯净的元数据信息。
2. 判定是否为历史消减工具：
   - `isHistoryTool = item.tool_name.startsWith("pw_history:")`。

#### 2.2.2 界面组件排版布局
当 `isHistoryTool && originalInputText` 时：
1. **元信息区域**：展示调用工具、调用时间、会话名、发送用户等（现有逻辑不变）；
2. **入参元数据 (JSON)**：展示 `batch_size`, `tools`, `original_chars` / `freed_chars` 等，代码框紧凑整洁；
3. **消减前原始输入面板 (新增)**：
   - 标题：`消减前完整输入`（若为 `pw_history:compress` 则标为 `压缩前完整输入`，若为 `pw_history:delete` 则标为 `删除前完整输入`）；
   - 副标题：`(N 字符)`；
   - 按钮：`📋 复制完整输入`；
   - 文本展示框：使用与 `outputResultBox` 相同的自适应滚动多行样式，保留换行排版。
4. **输出结果面板 (现有优化)**：
   - 标题：若为压缩模式标为 `压缩后结构化摘要`，删除模式标为 `清理执行结果`；
   - 副标题：`(N 字符)`；
   - 按钮：`📋 复制完整内容`；
   - 文本展示框：展示 `summary` 或 `DELETE_PLACEHOLDER`。

---

### 2.3 测试与验证规范

1. **后端单元测试 (`tests/test_history_cleaner.py`)**：
   - 断言 `pw_history:compress` 成功记录时，`input_args["original_input"]` 存在且为全量输入字符串，与 `contents_to_compress` 拼接结果一致，无 200 字符截断；
   - 断言副 AI 失败降级时，记录的 `pw_history:compress` 与后续 `pw_history:delete` 均包含完整 `original_input`；
   - 断言直接删除模式（`pw_history:delete`）的 `input_args["original_input"]` 包含所有被删除工具调用的完整正文。
2. **全测试套件验证**：
   - 执行 `uv run python -m unittest discover tests`，确保全量单测 100% 通过。
3. **前端构建与静态产物更新**：
   - 在 `web-src` 目录下运行构建命令（如 `pnpm build`），产物输出至 `views/browser/assets/`。
