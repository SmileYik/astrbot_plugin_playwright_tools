# 配置默认值优化与分层文档措辞统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `_conf_schema.json`、`main.py` 与 `core/history_cleaner.py` 的默认值及建议范围调优为均衡的现代大上下文配置，并按受众定位同步润色 `README.md` 与 `docs/`（排除 `docs/superpowers/`）下的所有文档。

**Architecture:** 统一 `_conf_schema.json` 与 Python 入口/清理器中的默认配置值，避免双端不一致或临界超时；同步更新 `tests/test_conf_schema.py` 等单测断言；最后按受众分层审校 `README.md`（普通用户）、`docs/AI_TOOLS.md` & `docs/ARCHITECTURE.md`（技术约定）、`docs/EXTERNAL_API.md`（开发者）与 `CHANGELOG.md`。

**Tech Stack:** JSON Schema, Python 3.12, unittest, Markdown

**Spec:** `docs/superpowers/specs/2026-11-28-config-defaults-and-docs-polish-design.md`

## Global Constraints

- 日志记录严禁使用 `import logging`，仅能使用 `from astrbot.api import logger`。
- 文档与提示文本需凝练简洁、实事求是，禁止使用绝对化词汇（如“彻底”“根治”“杜绝”“完全”）。
- 不修改 `docs/superpowers/` 下的历史设计/计划文档。
- 每次修改核心代码或配置后必须运行 `.venv/bin/python -m unittest discover tests` 保证 100% 通过。

## Review Focus

- `main.py` 与 `core/history_cleaner.py` 中的所有兜底默认值必须与 `_conf_schema.json` 严格一致，不能出现一处改了另一处仍用旧值的情况。
- `history_cleanup` 中 `low_watermark` (10000) 严格小于 `high_watermark` (24000)，且 `compress_prompt` 不再出现 `300 字` 限制。
- `README.md` 面向普通插件用户，配置表格中的默认值、类型与说明必须与 `_conf_schema.json` 一一对应。

---

### Task 1: 更新 `_conf_schema.json`、`main.py`、`core/history_cleaner.py` 默认值与单测

**Files:**
- Modify: `_conf_schema.json`
- Modify: `main.py`
- Modify: `core/history_cleaner.py`
- Test: `tests/test_conf_schema.py`
- Test: `tests/test_history_cleaner.py`

- [ ] **Step 1: Update assertions in `tests/test_conf_schema.py` (RED)**

更新 `tests/test_conf_schema.py` 中的默认值断言：`page_chunk_char_limit == 4000`、`high_watermark == 24000`、`low_watermark == 10000`、`tool_execution_timeout_seconds == 45`、`browser_window_height == 800`、`screenshot_timeout_seconds == 20`、`audit_retention_days == 14`、`compress_prompt` 包含 `1000`。

- [ ] **Step 2: Run `tests.test_conf_schema` to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_conf_schema -v`
Expected: FAIL

- [ ] **Step 3: Update `_conf_schema.json`, `main.py`, and `core/history_cleaner.py`**

- `_conf_schema.json`：按 Spec 表格更新默认值与面向普通用户的 `hint` 建议文案，更新 `compress_prompt` 默认值为不超过 `1000` 字的结构化提炼提示词。
- `main.py`：同步 `tool_timeout=45`、`page_chunk_char_limit=4000`、`browser_window_height=800`（如读取）、`screenshot_timeout=20`、`retention_days=14` 兜底默认值。
- `core/history_cleaner.py`：同步 `high_watermark=24000`、`low_watermark=10000` 及新的 `compress_prompt` 兜底默认值。

- [ ] **Step 4: Run `tests.test_conf_schema` and `tests.test_history_cleaner` to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_conf_schema tests.test_history_cleaner -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json main.py core/history_cleaner.py tests/test_conf_schema.py
git commit -m "chore(config): tune defaults for large-context UX and sync fallback values"
```

---

### Task 2: 按受众定位同步更新 `README.md`、`docs/` 与 `CHANGELOG.md` 并运行全量测试

**Files:**
- Modify: `README.md`
- Modify: `docs/AI_TOOLS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/EXTERNAL_API.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update `README.md` (面向普通插件用户)**

同步配置表格的默认值、建议值与通俗说明，确保与 `_conf_schema.json` 完全对齐且易读。

- [ ] **Step 2: Polish `docs/AI_TOOLS.md`, `docs/ARCHITECTURE.md`, `docs/EXTERNAL_API.md`, and `CHANGELOG.md`**

- `docs/AI_TOOLS.md`、`docs/ARCHITECTURE.md`：核对工具定义、架构约定与默认数值一致。
- `docs/EXTERNAL_API.md`：按开发者视角审校措辞，确保与当前 `ContextManager` / `PlaywrightServiceAPI` 行为一致。
- `CHANGELOG.md`：在 `v1.5.0` 条目下补充配置默认值调优与文档分层完善记录。

- [ ] **Step 3: Run forbidden-word scan and full test suite**

Run: `.venv/bin/python -m unittest discover tests`
Expected: All tests PASS (100% pass rate)

- [ ] **Step 4: Commit**

```bash
git add README.md docs/AI_TOOLS.md docs/ARCHITECTURE.md docs/EXTERNAL_API.md CHANGELOG.md
git commit -m "docs: align config defaults and polish docs by target audience"
```
