# Playwright 原生架构完全重构计划 (Playwright-Native Complete Refactor Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完全推倒并以原生 Playwright（`playwright.async_api`）为核心基石彻底重构 `adapts/`、`core/` 与 `tools/`，使所有交互与上下文管理建立在 Playwright 原生 API（`Page`, `BrowserContext`, `Locator`）之上，Camoufox 仅作为独立浏览器后端，杜绝裸 JS 注入与强耦合。

**Architecture:** 
- `adapts/`：基于 `BrowserAdapterBase` 抽象，`CamoufoxAdapter` 负责拉起防反爬环境并产出标准 Playwright `Browser` 实例；
- `core/`：`ContextManager` 管理原生 `BrowserContext` 多租户隔离；`PageExtractor` 标记 `data-astr-ref` 并抽取紧凑文本骨架；`SecurityManager` 拦截越权；`AuditLogger` 提供 SQLite 审计存储；
- `tools/handlers/`：通过 `page.locator(f'[data-astr-ref="{ref}"]').click() / .fill() / .select_option() / .hover() / .drag_to()` 彻底接管交互；
- `tools/tools.py` 与 `main.py`：暴露类型化 `FunctionTool`，统一使用 `from astrbot.api import logger`。

**Tech Stack:** Python 3.12, Playwright (`playwright.async_api`), Camoufox, AstrBot Plugin API, unittest

**Spec:** `docs/superpowers/specs/2026-11-20-playwright-native-refactor-design.md`

## Global Constraints

- 严禁在交互操作中注入裸 JS `document.querySelector().click()` 或手动派发事件，必须使用 Playwright 原生 `Locator` 方法。
- 除 `adapts/camoufox_adapter.py` 内部外，其余所有模块一律不得直接导入或依赖 `camoufox` 专属结构，完全面向 Playwright 官方接口编程。
- 全模块日志统一采用 `from astrbot.api import logger`（测试环境回退为标准 logger），严禁使用未经包装的标准 `logging`。
- 本计划**不使用 E2E 测试**（聚焦于精简快速、100% 可控的高质量单元测试与核心 Mock 验证）。

## Review Focus

1. **类型一致性**：`ContextManager` 与各个 Handler 传递的必须是原生 `playwright.async_api.Page` 与 `BrowserContext`。
2. **Locator 容错**：当目标元素不存在或已过期时，Playwright Locator 的超时或未找到异常是否被统一捕获并友好返回给大模型。
3. **多租户隔离**：不同 session / sender 的 `BrowserContext` 是否互不干扰，能否正确关闭对应 context。
4. **日志与 Traceback**：异常发生时是否保留调用栈并在 AstrBot WebUI 日志中完整输出。
5. **单元测试全覆盖**：所有重构后的类均拥有独立单测，整体单测秒级跑通无红灯。

---

### Task 1: 重构底层适配器层 (`adapts/`)

**Files:**
- Modify: `adapts/base.py`
- Modify: `adapts/camoufox_adapter.py`
- Test: `tests/test_browser_adapter.py`

- [ ] **Step 1: 在 `tests/test_browser_adapter.py` 中编写适配器规范测试**
  验证 `start()`、`stop()`、`create_context()` 以及 `browser` 属性的标准行为。

- [ ] **Step 2: 在 `adapts/base.py` 中定义标准抽象接口**
  声明 `BrowserAdapterBase`，返回原生 `BrowserContext` 与暴露 `Browser`。

- [ ] **Step 3: 在 `adapts/camoufox_adapter.py` 中实现标准 Camoufox 适配器**
  仅负责拉起 `AsyncCamoufox` 并提供原生 `Browser` 实例和新建 `BrowserContext`，隔离所有专有参数。

- [ ] **Step 4: 运行单测验证**
  运行：`.venv\Scripts\python -m unittest tests/test_browser_adapter.py`

- [ ] **Step 5: 提交代码**
  ```bash
  git add adapts/ tests/test_browser_adapter.py
  git commit -m "refactor(adapts): rebuild browser adapters strictly on playwright api"
  ```

---

### Task 2: 重构核心服务层 (`core/`)

**Files:**
- Modify: `core/page_extractor.py`
- Modify: `core/security_manager.py`
- Modify: `core/audit_logger.py`
- Modify: `core/context_manager.py`
- Test: `tests/test_page_extractor.py`
- Test: `tests/test_security_manager.py`
- Test: `tests/test_audit_logger.py`
- Test: `tests/test_context_manager.py`

- [ ] **Step 1: 规范化 `core/page_extractor.py`**
  确保提取 JS 脚本在 DOM 节点上打入标准 `data-astr-ref="{ref_id}"`，并生成语义化紧凑文本快照。

- [ ] **Step 2: 规范化 `core/security_manager.py`**
  实现域名通配符、动作权限白名单及 Admin Bypass 逻辑。

- [ ] **Step 3: 规范化 `core/audit_logger.py`**
  实现异步 SQLite 记录入库、查询、指标统计、导出与清空。

- [ ] **Step 4: 重写 `core/context_manager.py` 面向 Playwright 原生上下文**
  `ManagedContext` 强类型绑定 `BrowserContext` 与 `Page`；实现个人/会话模式查找、创建、授权与超期回收。

- [ ] **Step 5: 运行核心层全部单元测试**
  运行：
  - `.venv\Scripts\python -m unittest tests/test_page_extractor.py`
  - `.venv\Scripts\python -m unittest tests/test_security_manager.py`
  - `.venv\Scripts\python -m unittest tests/test_audit_logger.py`
  - `.venv\Scripts\python -m unittest tests/test_context_manager.py`

- [ ] **Step 6: 提交代码**
  ```bash
  git add core/ tests/
  git commit -m "refactor(core): rebuild context manager and core services around native playwright"
  ```

---

### Task 3: 重构原生 Playwright 动作处理器 (`tools/handlers/`)

**Files:**
- Modify: `tools/handlers/interact_handler.py`
- Modify: `tools/handlers/page_handler.py`
- Modify: `tools/handlers/media_handler.py`
- Test: `tests/test_interact_handler.py`
- Test: `tests/test_page_handler.py`
- Test: `tests/test_media_handler.py`

- [ ] **Step 1: 彻底重写 `tools/handlers/interact_handler.py`**
  所有交互动作（`click`, `fill_form`, `select_option`, `hover`, `focus`, `blur`, `drag`, `press_key`, `scroll`）全部使用 Playwright 原生 Locator 与键盘/鼠标 API。

- [ ] **Step 2: 彻底重写 `tools/handlers/page_handler.py`**
  使用 `page.goto()`, `page.on("dialog")`, `context.pages` 原生标签页切换及 `context.close()`。

- [ ] **Step 3: 彻底重写 `tools/handlers/media_handler.py`**
  使用 `page.screenshot()`（视口与整页长图及熔断）和原生下载流。

- [ ] **Step 4: 运行 Handler 单元测试**
  运行：
  - `.venv\Scripts\python -m unittest tests/test_interact_handler.py`
  - `.venv\Scripts\python -m unittest tests/test_page_handler.py`
  - `.venv\Scripts\python -m unittest tests/test_media_handler.py`

- [ ] **Step 5: 提交代码**
  ```bash
  git add tools/handlers/ tests/
  git commit -m "refactor(handlers): implement all actions with native playwright locator and page apis"
  ```

---

### Task 4: 重构顶层门面工具与主入口 (`tools/` & `main.py`)

**Files:**
- Modify: `tools/schemas.py`
- Modify: `tools/tools.py`
- Modify: `main.py`
- Test: `tests/test_tools_v2.py`
- Test: `tests/test_plugin_main.py`

- [ ] **Step 1: 统一 `tools/tools.py`**
  装配 `PwPageTool`, `PwInteractTool`, `PwMediaTool`，结合 `_execute_with_timeout`，规范使用 `from astrbot.api import logger`。

- [ ] **Step 2: 统一 `main.py`**
  注入三大原生工具，保留指令 `/browser` 与 WebUI 审计视图注册。

- [ ] **Step 3: 运行完整单元测试回归集**
  运行：`.venv\Scripts\python -m unittest discover tests`

- [ ] **Step 4: 提交代码**
  ```bash
  git add tools/ main.py tests/
  git commit -m "feat(plugin): finalize native playwright architecture integration"
  ```
