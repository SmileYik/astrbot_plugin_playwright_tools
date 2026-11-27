# 工具历史记录消减与压缩实现计划 (Tool History Cleanup & Compression Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现基于纯高低双水位线的工具历史记录消减与压缩机制，当本插件工具累计字符超过高水位时，按轮次从旧到新（FIFO）执行直接删除占位或副 AI 智能压缩，直至回落至低水位以内，永久收敛上下文并保证 API 协议合规。

**Architecture:** 在 `core/history_cleaner.py` 中封装独立的 `HistoryCleaner` 核心组件，按轮次（Tool Call Group）识别并聚合本插件（`pw_page`, `pw_read`, `pw_interact`, `pw_media`）的工具消息；在 `@filter.on_llm_request()` 中执行水位检测与消减，利用 AstrBot 原生的 `context_observer` 自动将变更持久化回会话事件流；副 AI 支持自定义模型、人设融合、输入长度控制（0 为不限长，大于 0 直接截断）及失败降级。

**Tech Stack:** Python 3.12, AstrBot Star Plugin API (`@filter.on_llm_request`, `Context`, `Provider`, `PersonaManager`), unittest.

**Spec:** `docs/superpowers/specs/2026-11-27-tool-history-cleanup-design.md`

## Global Constraints

- 绝不破坏 `assistant(tool_calls)` 与 `tool(tool_call_id)` 的配对结构，保留消息骨架仅替换 `content`，杜绝 400 报错。
- 仅处理本插件注册的工具（`pw_page`, `pw_read`, `pw_interact`, `pw_media`），放行其他插件工具。
- 严禁在代码中使用 `import logging`，必须统一使用 `from astrbot.api import logger`。
- 测试验证规范：必须运行 `python -m unittest discover tests`（或 `uv run python -m unittest discover tests`）确保 100% 通过。
- 每次元数据或重要功能变更时，必须同步更新 `metadata.yaml`、`main.py`、`README.md`、`docs/ARCHITECTURE.md` 与 `AGENT.md`。

## Review Focus

1. **已压缩/已清理内容的特征识别与防重复计算**：带有 `[历史浏览摘要]` 或 `[该历史工具调用结果已按策略清理]` 前缀的内容不得计入未压缩总字符，防止副 AI 无限重复压缩。
2. **`compress_max_input_chars` 临界值边界**：`0` 代表不限长度，全量输入给副 AI；`>0` 且超长时严格在末尾追加截断提示，防止输入超标。
3. **副 AI 调用异常/超时的静默降级**：当副 AI 抛出超时或异常时，必须自动平滑回退到直接删除占位模式，绝不中断用户主流程。
4. **单条超大记录且无旧记录可压时的安全跳出**：当候选可清理组已空但字符仍高于低水位时，循环必须正常 `break` 退出，绝不陷入死循环。
5. **多轮混合上下文中的因果链保持**：第 1 轮工具摘要写入第 1 轮末尾工具，第 2 轮工具摘要写入第 2 轮末尾工具，避免跨轮次摘要混乱堆叠。

---

### Task 1: 配置定义与模式校验 (`_conf_schema.json`)

**Files:**
- Modify: `_conf_schema.json`
- Test: `tests/test_conf_schema.py`

**Interfaces:**
- Produces: `history_cleanup` 配置字典，包含 `enable_cleanup: bool`, `high_watermark: int`, `low_watermark: int`, `cleanup_strategy: str`, `compress_provider_id: str`, `compress_max_input_chars: int`, `compress_prompt: str`, `compress_use_persona: bool`, `compress_persona_id: str`。

- [ ] **Step 1: 编写新增配置项的模式验证测试**

在 `tests/test_conf_schema.py` 中增加对 `history_cleanup` 配置组及所有子字段的结构、默认值及 `_special` 标记的断言测试：
```python
def test_history_cleanup_schema(self):
    self.assertIn("history_cleanup", self.schema)
    hc = self.schema["history_cleanup"]
    self.assertEqual(hc["type"], "object")
    items = hc["items"]
    self.assertIn("enable_cleanup", items)
    self.assertFalse(items["enable_cleanup"]["default"])
    self.assertEqual(items["high_watermark"]["default"], 8000)
    self.assertEqual(items["low_watermark"]["default"], 3000)
    self.assertEqual(items["cleanup_strategy"]["default"], "delete")
    self.assertEqual(items["compress_max_input_chars"]["default"], 0)
    self.assertEqual(items["compress_provider_id"]["_special"], "select_provider")
    self.assertEqual(items["compress_persona_id"]["_special"], "select_persona")
```

- [ ] **Step 2: 运行测试以确认失败**

运行：`uv run python -m unittest tests/test_conf_schema.py`
预期：FAIL（`KeyError: 'history_cleanup'`）

- [ ] **Step 3: 在 `_conf_schema.json` 中添加 `history_cleanup` 配置对象**

在 `_conf_schema.json` 顶层添加 `history_cleanup` 对象，完整定义开关、高低水位、策略单选、提供商选择器、输入上限（默认 0）、提示词文本域、人设开关与人设选择器。

- [ ] **Step 4: 运行测试以验证通过**

运行：`uv run python -m unittest tests/test_conf_schema.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add _conf_schema.json tests/test_conf_schema.py
git commit -m "feat(config): add history_cleanup configuration schema"
```

---

### Task 2: 核心组件基础框架与直接删除模式 (`core/history_cleaner.py`)

**Files:**
- Create: `core/history_cleaner.py`
- Test: `tests/test_history_cleaner.py`

**Interfaces:**
- Produces: `HistoryCleaner` 类：
  - `__init__(self, context: Any, config: dict[str, Any])`
  - `is_plugin_tool(self, name: str) -> bool`: 检查是否属于 `pw_page`, `pw_read`, `pw_interact`, `pw_media`
  - `is_processed_tool(self, content: str) -> bool`: 检查是否已包含清理/压缩标记
  - `calculate_uncompressed_chars(self, contexts: list[Any]) -> int`: 统计未压缩的本插件工具字符
  - `group_tool_calls(self, contexts: list[Any]) -> list[list[int]]`: 按轮次划分属于本插件的工具消息索引组
  - `async def process_contexts(self, event: Any, req: Any) -> bool`: 执行双水位线检查与消减

- [ ] **Step 1: 编写 `HistoryCleaner` 基础功能与直接删除单元测试**

在 `tests/test_history_cleaner.py` 中测试：
1. 字符统计（正确统计 `pw_*` 工具字符，排除已处理工具与其他插件工具）；
2. 轮次分组（将同一个 assistant 下的多次连续工具划分在同一组）；
3. 高低双水位线触发（低于高水位不动作，高于高水位时按 FIFO 逐组删除，直至降到低水位以下）；
4. 直接删除占位格式（保留 `tool_call_id`，`content` 替换为 `"[该历史工具调用结果已按策略清理]"`）。

- [ ] **Step 2: 运行测试以确认失败**

运行：`uv run python -m unittest tests/test_history_cleaner.py`
预期：FAIL（`ModuleNotFoundError: No module named '...history_cleaner'`）

- [ ] **Step 3: 实现 `core/history_cleaner.py` 的基础类与删除消减逻辑**

编写 `HistoryCleaner`：
- 初始化解析 `history_cleanup` 配置项；
- 支持 `dict` 与 `Message` 双重消息格式兼容；
- 实现基于双水位线的 FIFO 逐组删除循环，并包含候选组耗尽的安全跳出逻辑。

- [ ] **Step 4: 运行测试以验证通过**

运行：`uv run python -m unittest tests/test_history_cleaner.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add core/history_cleaner.py tests/test_history_cleaner.py
git commit -m "feat(core): implement HistoryCleaner base and delete strategy"
```

---

### Task 3: 副 AI 压缩、人设融合与长度控制 (`core/history_cleaner.py`)

**Files:**
- Modify: `core/history_cleaner.py`
- Test: `tests/test_history_cleaner.py`

**Interfaces:**
- Consumes: Task 2 中的 `HistoryCleaner` 基础框架
- Produces: 
  - `_prepare_compress_input(self, tool_group_contents: list[str]) -> str`: 拼装输入并根据 `compress_max_input_chars`（0 不限，>0 截断）处理文本
  - `_resolve_compress_provider(self, event: Any) -> Any`: 获取指定或默认 Provider
  - `_resolve_system_prompt(self) -> str`: 组装基础提示词与人设（支持指定人设与默认人设回退）
  - `_compress_tool_group(self, group_indices: list[int], contexts: list[Any], event: Any) -> bool`: 调用副 AI 并原位写回折叠占位与最终摘要，失败时自动平滑降级为直接删除

- [ ] **Step 1: 在 `tests/test_history_cleaner.py` 中编写副 AI 压缩测试用例**

增加测试：
1. 压缩模式正常流程：验证副 AI 接收拼接文本与组装后的提示词，验证首尾工具替换（第 1~N-1 个替换为 `"[已并入本轮浏览摘要]"`，第 N 个替换为 `"[历史浏览摘要]:\n..."`）；
2. 人设启用与未指定回退：验证启用人设且未指定时，正确调用 `persona_manager.get_persona(default_persona)`；
3. `compress_max_input_chars`：测试为 `0` 时输入保持原样，大于 `0` 且超长时直接截断并附加提示；
4. 异常降级兜底：模拟副 AI 抛出异常或超时，断言自动平滑降级为直接删除占位，不会抛出未捕获错误。

- [ ] **Step 2: 运行测试以确认失败**

运行：`uv run python -m unittest tests/test_history_cleaner.py`
预期：FAIL（相关压缩方法未实现）

- [ ] **Step 3: 在 `core/history_cleaner.py` 中实现副 AI 压缩相关方法**

编写 `_prepare_compress_input`、`_resolve_compress_provider`、`_resolve_system_prompt` 与 `_compress_tool_group`：
- 调用 `provider.text_chat(prompt=..., system_prompt=...)`；
- 使用 `try-except` 包裹，异常时回退到删除占位；
- 将压缩完成标志标记在消息体中。

- [ ] **Step 4: 运行测试以验证通过**

运行：`uv run python -m unittest tests/test_history_cleaner.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add core/history_cleaner.py tests/test_history_cleaner.py
git commit -m "feat(core): implement secondary AI compression with persona and input limit"
```

---

### Task 4: 插件入口集成与端到端钩子挂载 (`main.py`)

**Files:**
- Modify: `main.py:30-45, 355-375`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: Task 2 & 3 中的 `HistoryCleaner`
- Produces: `PlaywrightToolPlugin.history_cleaner` 实例并在 `@filter.on_llm_request()` 中自动触发。

- [ ] **Step 1: 编写 `main.py` 中集成 `HistoryCleaner` 的单元测试**

在 `tests/test_plugin_main.py` 中增加测试用例：
1. 测试插件初始化时正确实例化 `self.history_cleaner`；
2. 测试 `on_llm_request` 钩子被触发时，会调用 `history_cleaner.process_contexts(event, req)`。

- [ ] **Step 2: 运行测试以确认失败**

运行：`uv run python -m unittest tests/test_plugin_main.py`
预期：FAIL（`PlaywrightToolPlugin` 缺少 `history_cleaner` 属性或未调用）

- [ ] **Step 3: 修改 `main.py` 完成组件挂载**

1. 引入 `from .core.history_cleaner import HistoryCleaner`；
2. 在 `__init__` 中实例化 `self.history_cleaner = HistoryCleaner(self.context, self.config)`；
3. 在 `@filter.on_llm_request()` 中调用：
   ```python
   await self.history_cleaner.process_contexts(event, req)
   ```

- [ ] **Step 4: 运行测试以验证通过**

运行：`uv run python -m unittest tests/test_plugin_main.py`
预期：PASS

- [ ] **Step 5: 运行全量单元测试套件**

运行：`uv run python -m unittest discover tests`
预期：100% 测试通过（全部 ~240+ 测试用例无回归）

- [ ] **Step 6: 提交更改**

```bash
git add main.py tests/test_plugin_main.py
git commit -m "feat(plugin): wire HistoryCleaner into on_llm_request hook"
```

---

### Task 5: 文档同步、元数据更新与版本交付

**Files:**
- Modify: `metadata.yaml`
- Modify: `main.py`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `AGENT.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- 完整同步元数据与版本号，记录历史消减与压缩功能。

- [ ] **Step 1: 更新 `metadata.yaml` 与 `main.py` 版本号与说明**

更新版本号（从 `v1.3.0` 升级为 `v1.4.0`），补充关于双水位线工具历史消减与副 AI 压缩特性的说明。

- [ ] **Step 2: 更新 `README.md` 与 `docs/ARCHITECTURE.md`**

在 README 与架构文档中添加“上下文与历史消减”章节，清晰说明高低双水位线机制、直接删除与副 AI 压缩策略及配置项说明。

- [ ] **Step 3: 更新 `CHANGELOG.md`**

在 CHANGELOG 中增加 `v1.4.0` 版本记录。

- [ ] **Step 4: 运行全量测试进行最终验证**

运行：`uv run python -m unittest discover tests`
预期：所有单测 100% 通过。

- [ ] **Step 5: 提交所有文档更新**

```bash
git add metadata.yaml main.py README.md docs/ARCHITECTURE.md AGENT.md CHANGELOG.md
git commit -m "docs: document tool history cleanup and bump version to v1.4.0"
```
