# Codebase Cleanup and Docs Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清理前端代码中硬编码的 Mock 测试数据并重新打包，治理并精简测试套件，归档死文档并将 `docs/README.md` 完整并入根目录 `README.md`，规范技术文档中的夸张措辞。

**Architecture:** 按照三阶段分层推进：阶段一在前端 TypeScript API 层中移除假数据并使用 Vite 编译更新静态控制台视图；阶段二清理测试套件中冗余文件与历史命名，并由 unittest 自动化回归保障；阶段三执行文档归档、双份 README 合并与客观化措辞治理。

**Tech Stack:** TypeScript, React, Vite, Python 3.12, unittest, Markdown

**Spec:** [docs/superpowers/specs/2026-11-21-codebase-cleanup-and-docs-consolidation-design.md](../../../docs/superpowers/specs/2026-11-21-codebase-cleanup-and-docs-consolidation-design.md)

## Global Constraints

- 严禁在移除前端 Mock 假数据后出现未捕获异常导致 UI 崩溃，接口失败时必须返回符合类型定义的空值默认对象（空列表、0 统计等）。
- 绝不触碰或修改 `./docs/superpowers/` 目录中的任何历史文档（用户明确排除）。
- 测试套件整理后必须保证 `python -m unittest discover tests` 13 套单测 100% 通过。
- 严格遵循 `AGENT.md` 中禁止使用“彻底xxx”、“根治xxx”、“完美xxx”等绝对化词汇的规定。

## Review Focus

- **后端无响应或网络异常时前端表现**：审计与生命周期面板在接口 500 或网络断开时正常显示空列表与 0 统计，不出现白屏崩溃。
- **截图预览异常回退**：截图 API 失败或返回非图片时不输出写死的模拟 SVG 预览。
- **测试重命名后导入完整性**：`test_tools_v2.py` 重命名为 `test_tools.py` 后无残留引用失效。
- **配置与工具文档完整度**：`README.md` 合并后必须包含完整的 5 大配置分组与三大工具详细参数，且无断链。
- **绝对化词汇清理彻底性**：`CHANGELOG.md` 和 `docs/ARCHITECTURE.md` 不存在违规绝对化用词。

---

### Task 1: 前端代码 Mock 数据清理与重新构建

**Files:**
- Modify: `web-src/src/api/audit.ts`
- Modify: `web-src/src/api/lifecycle.ts`
- Output: `views/browser/assets/*`

**Interfaces:**
- Consumes: `ApiResponse<T>`, `AuditStats`, `LogsResponseData`, `ActiveContextItem`, `LifecycleLogsResponseData` from `web-src/src/types.ts`
- Produces: 编译后的静态 WebUI 产物到 `views/browser/assets/`

- [ ] **Step 1: 清理 `web-src/src/api/audit.ts` 中的 Mock 数据与回退逻辑**
  - 移除 `MOCK_STATS` 和 `MOCK_LOGS` 常量定义；
  - 修改 `fetchAuditLogs`：移除 `catch` 后的 mock 过滤逻辑，网络异常或接口返回异常时直接返回空分页：
    ```typescript
    return {
      total: 0,
      items: [],
      page: query.page,
      page_size: query.page_size,
    };
    ```
  - 修改 `fetchAuditStats`：移除 `MOCK_STATS` 回退，失败时返回：
    ```typescript
    return { total: 0, allowed: 0, denied: 0, error: 0, today_count: 0 };
    ```
  - 修改 `exportAuditLogs`：移除 `MOCK_LOGS` 回退，失败时返回 `{ data: "", format }`；
  - 修改 `fetchScreenshot`：移除 `mock_screenshot_sample` 及伪预览 SVG 生成代码，失败时返回 `""`。

- [ ] **Step 2: 清理 `web-src/src/api/lifecycle.ts` 中的 Mock 数据与回退逻辑**
  - 移除 `MOCK_ACTIVE_CONTEXTS` 和 `MOCK_LIFECYCLE_LOGS` 常量定义；
  - 修改 `fetchActiveContexts`：移除 `MOCK_ACTIVE_CONTEXTS` 回退，失败时返回 `[]`；
  - 修改 `fetchLifecycleLogs`：移除 `MOCK_LIFECYCLE_LOGS` 回退，失败时返回：
    ```typescript
    return {
      total: 0,
      items: [],
      page: query.page,
      page_size: query.page_size,
    };
    ```

- [ ] **Step 3: 运行 TypeScript 检查与 Vite 构建**
  - 切换到 `web-src/` 目录运行 `npm run build`；
  - 验证构建成功退出（Exit Code 0），并在 `views/browser/assets/` 中生成了更新后的 `index-*.js` 和 `index-*.css`。

- [ ] **Step 4: 提交 Task 1 变更**
  ```bash
  git add web-src/ views/browser/
  git commit -m "refactor(web): remove mock data fallbacks and re-bundle browser assets"
  ```

---

### Task 2: 测试套件精简与单测全量验证

**Files:**
- Delete: `tests/test_browser_adapter.py`
- Delete: `tests/e2e/` (包含残留 `__pycache__`)
- Move: `tests/test_tools_v2.py` -> `tests/test_tools.py`

**Interfaces:**
- Consumes: `tools/tools.py`, `adapts/`, `core/`, `api/`
- Produces: 13 套规范命名的单元测试，全部通过 `python -m unittest discover tests`

- [ ] **Step 1: 删除冗余单测 `tests/test_browser_adapter.py`**
  - 执行 `git rm tests/test_browser_adapter.py`；
  - 该文件的测试目标已由 `tests/test_adapter_factory.py` 完整且更严谨地覆盖。

- [ ] **Step 2: 清理孤立残留目录 `tests/e2e/`**
  - 删除 `tests/e2e/` 目录及其内部的 `.pyc` 缓存文件。

- [ ] **Step 3: 重命名 `tests/test_tools_v2.py` 为 `tests/test_tools.py`**
  - 执行 `git mv tests/test_tools_v2.py tests/test_tools.py`；
  - 检查类名 `class TestToolsV2(unittest.TestCase)`，更新为 `class TestTools(unittest.TestCase)`。

- [ ] **Step 4: 运行全量单元测试验收**
  - 运行 `.\.venv\Scripts\python.exe -m unittest discover tests`；
  - 预期结果：13 套单测全部通过（OK），用例数约 136 个，无任何报错。

- [ ] **Step 5: 提交 Task 2 变更**
  ```bash
  git add tests/
  git commit -m "chore(tests): prune redundant tests, remove e2e pycache and standardize test names"
  ```

---

### Task 3: 死文档归档与 README 整合

**Files:**
- Move: `InitialRequirementsList.md` -> `docs/old/InitialRequirementsList.md`
- Modify: `README.md`
- Delete: `docs/README.md`

**Interfaces:**
- Consumes: `docs/README.md`, `README.md`, `_conf_schema.json`
- Produces: 自包含、内容详实的根目录 `README.md`，并在 `docs/old/` 归档历史需求

- [ ] **Step 1: 归档 `InitialRequirementsList.md`**
  - 创建 `docs/old/` 目录；
  - 执行 `git mv InitialRequirementsList.md docs/old/InitialRequirementsList.md`。

- [ ] **Step 2: 将 `docs/README.md` 核心内容并入根目录 `README.md`**
  - 保留根目录 `README.md` 顶部的项目简介、核心亮点（将过时的 `views/audit/` 路径更新为 `views/browser/` 网页工具控制台）；
  - 保留并美化插件用户指令表（`/browser invite`, `/browser use`, `/browser close`, `/browser status`）；
  - 将 `docs/README.md` 中详尽的大模型工具规范（`pw_page`、`pw_interact`、`pw_media` 的全部 action 参数、取值范围与默认值）整合进 `README.md` 的大模型工具部分；
  - 将 `docs/README.md` 中完整的 WebUI 配置指南（5 大业务分组：`security`、`runtime`、`browser`、`media`、`storage_audit` 的全部字段表格）合并进 `README.md`；
  - 更新底部架构参考链接（仅保留指向 `docs/ARCHITECTURE.md` 的链接，移除指向 `docs/README.md` 的无效链接）。

- [ ] **Step 3: 删除 `docs/README.md`**
  - 执行 `git rm docs/README.md`。

- [ ] **Step 4: 检查全文链接有效性**
  - 确保根目录 `README.md` 无失效锚点与坏死链接。

- [ ] **Step 5: 提交 Task 3 变更**
  ```bash
  git add README.md docs/old/
  git commit -m "docs: merge docs/README.md into root README.md and archive initial requirements"
  ```

---

### Task 4: 架构文档更新与变更日志客观化治理

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: 当前项目实际架构（SPA 路由、双适配器、生命周期 Web API）
- Produces: 准确反映当前系统架构的 `docs/ARCHITECTURE.md`，以及措辞客观合规的 `CHANGELOG.md`

- [ ] **Step 1: 更新 `docs/ARCHITECTURE.md` 架构图与分层描述**
  - 更新 Mermaid 图表：
    - 将 `views/audit/` 替换为 `views/browser/ (Vite + React SPA)`；
    - 在 Web APIs 中加入 `/lifecycle/*`；
    - 在 Browser Adapter Layer 中展示 `AdapterFactory` 接入 `PlaywrightAdapter` 和 `CamoufoxAdapter`；
  - 更新 1.1 适配器层描述，说明工厂模式支持 Playwright 原生与 Camoufox 防检适配器；
  - 更新 1.5 视图层描述，说明已收敛为统一控制台 SPA 并支持标签页切换；
  - 治理该文件中的绝对化用词（如将“彻底移除 if-elif-else”改为“移除 if-elif-else 分支，采用字典映射”）。

- [ ] **Step 2: 客观化治理 `CHANGELOG.md` 中的夸大/绝对化用词**
  - 扫描并替换所有违反 `AGENT.md` 规范的绝对化词汇：
    - “彻底解决” -> “修复”
    - “彻底杜绝” -> “阻断”
    - “彻底消除” -> “消除”
    - “完美保障” -> “保障”
    - “彻底修复” -> “修复”
    - “架构彻底重构” -> “架构原生重构”
    - “彻底重构” -> “原生重构”
    - “彻底移除” -> “移除”
    - “彻底告别” -> “避免”
    - “彻底剥离” -> “解耦剥离”
  - 确保行文严谨、实事求是。

- [ ] **Step 3: 运行完整验证检查**
  - 运行 `.\.venv\Scripts\python.exe -m unittest discover tests` 确保测试仍保持 100% 通过；
  - 执行 `git status` 检查工作区干净，无未追踪的遗留文件。

- [ ] **Step 4: 提交 Task 4 变更**
  ```bash
  git add docs/ARCHITECTURE.md CHANGELOG.md
  git commit -m "docs: update architecture to unified SPA console and sanitize exaggerated wording"
  ```
