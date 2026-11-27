# 历史工具消减审计完整输入输出记录实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在工具历史消减（副 AI 压缩与直接删除）的审计记录中完整记录消减前的全部原始输入内容（无截断），并在 WebUI 前端审计抽屉中提供“消减前完整输入”与“压缩后摘要/清理结果”的独立原生多行排版卡片，实现前后对比清晰可视。

**Architecture:** 
- 后端在 `core/history_cleaner.py` 的 `_compress_batch`（压缩模式与失败降级）及直接删除逻辑中，将 `batch_indices` 涉及的全部原始工具调用与前序摘要拼装为全量文本存入 `input_args["original_input"]`，去除原有 200 字符 preview 截断；
- 前端在 `web-src/src/components/SideDrawer.tsx` 中识别 `pw_history:*` 工具与 `original_input`，将超长输入从参数 JSON 中解耦剥离并渲染为专属的“消减前完整输入”多行文本框，入参 JSON 仅展示精炼元数据，配合现有的“输出结果”形成直观对比；
- 编译更新 WebUI 静态产物至 `views/browser/`。

**Tech Stack:** Python 3.10+, SQLite, TypeScript, React 18, Vite.

**Spec:** `docs/superpowers/specs/2026-11-27-history-audit-full-input-output-design.md`

## Global Constraints
- 严格遵循 AstrBot 日志规范，所有业务日志使用 `from astrbot.api import logger`。
- 所有 Python 单元测试 100% 通过（`uv run python -m unittest discover tests`）。
- 前端构建必须使用 `web-src` 中的 `npm run build`，成功产出至 `views/browser/`。
- 保证前后端数据契约向后兼容，若历史旧记录没有 `original_input` 则正常回退展示原 JSON。

## Review Focus
1. `pw_history:compress` 成功记录中，`input_args["original_input"]` 包含整批各工具调用与前序摘要的 100% 完整原文，无 200 字符截断。
2. `pw_history:compress` 失败记录中，同样保存完整的 `original_input`。
3. `pw_history:delete` 记录中，`input_args["original_input"]` 包含所有被直接删除的工具调用完整原文。
4. 前端抽屉展示 `pw_history:*` 时，参数 JSON 框不出现巨大且带 `\n` 转义的 `original_input`，仅展示结构化元数据。
5. 前端抽屉中“消减前完整输入”卡片具备字符统计与独立“复制完整输入”按钮，多行文本排版换行正确。

---

### Task 1: 后端完整原始输入采集与单元测试

**Files:**
- Modify: `core/history_cleaner.py:548-646`
- Modify: `tests/test_history_cleaner.py`

- [ ] **Step 1: 编写单元测试断言 `original_input` 全量记录**
  在 `tests/test_history_cleaner.py` 中：
  - 更新 `test_compress_audit_and_logging_success`：断言 `input_args["original_input"]` 存在且长度大于 6000 字符，包含 `"Opened page"` 与 `"A" * 6000`；
  - 更新 `test_compress_audit_fallback_on_error`：断言失败时的 `pw_history:compress` 与降级 `pw_history:delete` 的 `input_args["original_input"]` 均完整保存；
  - 更新 `test_delete_strategy_audit_and_logging`：断言 `pw_history:delete` 的 `input_args["original_input"]` 包含 `"A" * 6000`。
  运行测试确认失败：`uv run python -m unittest tests/test_history_cleaner.py`

- [ ] **Step 2: 在 `core/history_cleaner.py` 中记录全量 `original_input`**
  - 在 `_compress_batch` 中：将待压缩文本完整保留为 `full_input = "\n\n".join(contents_to_compress)`，传入 `_record_tool_audit` 的 `input_args`（使用 `"original_input": full_input`，移除 200 字符的 `"preview"` 限制）；
  - 在 `process_contexts` 的直接删除与降级删除逻辑中：以相同格式拼装被清理条目的完整文本 `full_deleted_input`，传入 `pw_history:delete` 的 `input_args["original_input"]`。

- [ ] **Step 3: 运行测试并验证**
  运行 `uv run python -m unittest tests/test_history_cleaner.py`，确认测试全部通过。
  运行 `uv run python -m unittest discover tests`，确认全量测试无回归。

- [ ] **Step 4: 提交后端变更**
  提交代码：`git commit -am "feat(cleaner): record full original input in history cleanup tool audit"`

---

### Task 2: 前端 SideDrawer 专属对比视图与静态构建

**Files:**
- Modify: `web-src/src/components/SideDrawer.tsx`
- Modify: `views/browser/` (build artifacts)

- [ ] **Step 1: 优化 `SideDrawer.tsx` 中的历史审计展示**
  - 在 `parsedArgs` 中提取 `original_input`：
    ```ts
    const originalInputText = parsedArgs?.original_input || "";
    // 从复制/展示的 formattedArgs 中剥离 original_input，保留 metadata
    ```
  - 当 `item.tool_name.startsWith("pw_history:") && originalInputText` 时：
    - 在入参区域渲染剥离后的元数据 JSON；
    - 新增“消减前完整输入”卡片（标题根据 compress/delete 显示“压缩前完整输入”或“删除前完整输入”），带 `({originalInputText.length} 字符)`、独立复制按钮与多行滚动框；
    - “输出结果”卡片标题根据 compress/delete 标为“压缩后结构化摘要”或“清理执行结果”。

- [ ] **Step 2: 执行前端构建**
  在 `web-src` 目录下运行 `npm run build`，编译产出至 `views/browser/assets/`。

- [ ] **Step 3: 验证构建产物并提交**
  检查 `views/browser/` 产物更新情况。
  提交代码：`git commit -am "feat(webui): add dedicated full input/output view in audit drawer"`

---

### Task 3: 全量测试验证与文档更新

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新架构文档与变更日志**
  - 在 `CHANGELOG.md` 中增加 `[v1.4.4] - 2026-11-27` 条目，说明审计日志中完整输入输出记录与 WebUI 专属长文本对比视图；
  - 在 `docs/ARCHITECTURE.md` Section 5.4 中更新工具调用审计说明。

- [ ] **Step 2: 运行全量测试**
  运行 `uv run python -m unittest discover tests`，确认 100% 通过。

- [ ] **Step 3: 提交文档更新**
  提交代码：`git commit -am "docs: update changelog and architecture for audit full input recording"`
