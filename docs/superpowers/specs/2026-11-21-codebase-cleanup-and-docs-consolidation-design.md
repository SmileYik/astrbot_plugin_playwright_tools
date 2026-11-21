# 设计规范：代码库清理、死文档归档与文档整合规范

## 1. 背景与目标 (Intent & The Why)

在快速迭代与多轮架构演进（如 SPA 单页面架构合并、Playwright 原生能力解耦、5 分组配置面板升级等）之后，项目中遗留了部分技术债务与过时内容：
- 前端 `web-src` 中保留了早期离线/开发调试用的硬编码 Mock 数据，且在接口异常时会隐式回退到 Mock 数据，导致用户在无数据或网络异常时无法感知真实状态；
- 文档体系中存在未维护的死文档（`InitialRequirementsList.md`）、重复维护的双份说明文件（`README.md` 与 `docs/README.md`）以及未同步更新的架构图与过时路径（如 `views/audit/`）；
- 文档用词中存在较多夸大或绝对化词汇（如“彻底xxx”、“完美保障”），违反了 [AGENT.md](../../../AGENT.md) 中关于客观凝练的写作规范；
- 测试体系中残留了冗余单测（`test_browser_adapter.py` 已被工厂单测覆盖）、历史命名的工具单测（`test_tools_v2.py`）以及已删除真实脚本但残留 `__pycache__` 的空目录（`tests/e2e/`）。

本设计的核心意图是通过系统化清洗与整合，使代码库结构清晰统一，消除虚假测试数据，保证文档、代码与单测高度一致。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals & Anti-Goals)

### 目标 (Goals)
1. **移除前端 Mock 假数据**：移除 `web-src/src/api/audit.ts` 与 `web-src/src/api/lifecycle.ts` 中的所有 Mock 常量及模拟过滤回退逻辑。接口返回非零或发生异常时，均返回结构清晰的空结果，并重新构建生成 `views/browser/assets/` 资源。
2. **死文档归档与结构清理**：
   - 将根目录早期草案需求文档 `InitialRequirementsList.md` 移入 `docs/old/` 归档。
   - 将 `docs/README.md` 完整并入根目录 `README.md`（包含详细工具参数表与 5 大配置分组指南），随后删除 `docs/README.md`。
3. **架构文档与用词治理**：
   - 更新 `docs/ARCHITECTURE.md`，同步最新的 `views/browser/` 统一控制台、生命周期 Web API 以及双适配器架构（Playwright + Camoufox）；
   - 治理 `CHANGELOG.md` 和 `docs/ARCHITECTURE.md` 中的绝对化/夸张用词（如“彻底解决”、“完美保障”等），替换为实事求是的客观技术描述（注：用户明确说明 `./docs/superpowers/` 目录下的文档无需处理）。
4. **精简测试套件**：
   - 删除冗余的 `tests/test_browser_adapter.py`；
   - 彻底删除孤立残留的 `tests/e2e/` 目录；
   - 将 `tests/test_tools_v2.py` 重命名为 `tests/test_tools.py`；
   - 保证 `python -m unittest discover tests` 运行全部测试通过。

### 非目标 (Non-Goals)
- 不修改 `./docs/superpowers/` 目录下的任何历史设计与执行计划。
- 不修改后端核心业务逻辑（`core/`、`api/`、`tools/`、`adapts/`）的功能行为，仅做测试与文档清理。
- 不引入新的第三方依赖。

### 反目标 (Anti-Goals)
- 严禁在移除前端 Mock 后导致页面崩溃：必须返回符合接口类型定义的默认空对象（空数组、计数为 0 等），保证 UI 能够正常渲染空态。
- 严禁破坏单测覆盖率或导致现有有效用例失败。

---

## 3. 约束条件 (Constraints)

1. **环境与运行工具**：
   - Python 3.12 虚拟环境：`.\.venv\Scripts\python.exe`；
   - Node.js 前端构建：在 `web-src/` 目录下执行构建脚本；
   - 操作系统：Windows (PowerShell)。
2. **规范守则**：
   - 严格遵循 `AGENT.md` 中对于文档语言简洁实事求是、严禁夸大词汇的规定；
   - 遵循 `metadata.yaml` 视图声明（`views/browser/`）。

---

## 4. 备选方案对比与选定方案 (Approaches)

### 方案一：模块分阶段清洗与验证（选定）
将清理工作分为三个可独立验证的阶段：
1. Web 代码清理与重新打包：修改 API 调用空态逻辑，执行 `npm run build`，验证 `views/browser/` 生成成功；
2. 测试代码重构与验证：删除冗余文件、重命名工具单测、清理死目录，执行 `python -m unittest discover tests` 验证通过；
3. 文档归档、合并与措辞清理：移动归档 `InitialRequirementsList.md`，合并并删除 `docs/README.md`，更新架构图与日志措辞。
- **优点**：阶段边界清晰，每步均有对应的构建或测试命令快速检验，风险隔离彻底。
- **缺点**：需分步执行与验证。

### 方案二：全量并行重构
同时修改前端、测试与文档，最后统一编译和运行测试。
- **缺点**：若发生路径缺失或编译错误，难以迅速定位是哪个层级改动所致。

**结论**：用户已确认采用【方案一】。

---

## 5. 详细实现规范 (Detailed Design)

### 5.1 阶段 1：Web 代码 Mock 清理与静态构建 (`web-src/`)

#### 5.1.1 `web-src/src/api/audit.ts`
- 移除常量：`MOCK_STATS`、`MOCK_LOGS`；
- 函数改造：
  - `fetchAuditLogs(params)`：调用失败或无数据时，直接返回默认空分页对象：
    ```typescript
    return {
      total: 0,
      items: [],
      page: query.page,
      page_size: query.page_size,
    };
    ```
  - `fetchAuditStats()`：调用失败时直接返回零统计：
    ```typescript
    return {
      total: 0,
      allowed: 0,
      denied: 0,
      error: 0,
      today_count: 0,
    };
    ```
  - `exportAuditLogs(format)`：调用失败时返回空内容 `{ data: "", format }`；
  - `fetchScreenshot(path)`：调用失败时直接返回空字符串 `""`，移除写死的伪预览 SVG。

#### 5.1.2 `web-src/src/api/lifecycle.ts`
- 移除常量：`MOCK_ACTIVE_CONTEXTS`、`MOCK_LIFECYCLE_LOGS`；
- 函数改造：
  - `fetchActiveContexts(includeAll)`：调用失败时直接返回空数组 `[]`；
  - `fetchLifecycleLogs(params)`：调用失败时直接返回空分页对象：
    ```typescript
    return {
      total: 0,
      items: [],
      page: query.page,
      page_size: query.page_size,
    };
    ```

#### 5.1.3 构建部署
在 `web-src/` 目录下运行 `npm run build`，确保 TypeScript 检查通过，产物正确输出至 `views/browser/`。

---

### 5.2 阶段 2：测试套件清理与单测验证 (`tests/`)

1. **删除冗余文件与死目录**：
   - 删除 `tests/test_browser_adapter.py`（其功能已由 `tests/test_adapter_factory.py` 完整覆盖）；
   - 删除 `tests/e2e/` 目录（仅含残存 pycache，无任何实际用例，且 AGENT.md 规范不执行 e2e）。
2. **统一命名测试文件**：
   - 将 `tests/test_tools_v2.py` 重命名为 `tests/test_tools.py`；
   - 检查并确保测试内对 `tools.tools` 的引用正常。
3. **单测验收**：
   - 运行 `.\.venv\Scripts\python.exe -m unittest discover tests`，验证剩余 13 套单测全部执行通过，无任何失败或导入异常。

---

### 5.3 阶段 3：文档归档、合并与措辞治理

#### 5.3.1 死文档归档
- 创建 `docs/old/` 目录；
- 将根目录 `InitialRequirementsList.md` 移动到 `docs/old/InitialRequirementsList.md`。

#### 5.3.2 `README.md` 与 `docs/README.md` 合并
- 保留 `README.md` 的整体精简大纲风格：
  - 项目简介与核心特性（修正 `views/audit/` 为 `views/browser/` 控制台）；
  - 插件指令表；
  - 大模型工具规范：整合 `docs/README.md` 中的 `pw_page`、`pw_interact`、`pw_media` 详细参数列表与取值说明；
  - WebUI 配置说明：完整并入 5 大分组（安全、运行时、浏览器、媒体、存储审计）的配置项表格；
  - 依赖安装与架构参考链接；
- 移除原 `docs/README.md`，删除任何指向 `docs/README.md` 的链接。

#### 5.3.3 `docs/ARCHITECTURE.md` 架构修正与用词治理
- 更新 Mermaid 流程图：
  - 将 `AuditView["Plugin View: views/audit/"]` 更新为 `BrowserView["Plugin View: views/browser/ (Vite + React SPA)"]`；
  - 补充生命周期 API：`Web APIs: /audit/*, /lifecycle/*`；
  - 补充适配器：`AdapterFactory -> CamoufoxAdapter / PlaywrightAdapter`；
- 更新分层说明文字：
  - 纠正 `views/audit/` 描述，阐明统一的控制台架构与 Tab 内存路由；
  - 纠正适配器层描述，说明原生 Playwright 与 Camoufox 适配器双轨支持；
- 用词治理：清理“彻底移除 if-elif-else”等绝对词汇，改为“移除 if-elif-else 分支，采用字典映射分发”。

#### 5.3.4 `CHANGELOG.md` 用词治理
- 对 `CHANGELOG.md` 中出现的绝对化/夸张用词做客观化重述：
  - “彻底解决” -> “修复” / “支持”
  - “彻底杜绝” -> “规避” / “阻断”
  - “彻底消除” -> “消除”
  - “完美保障” -> “保障”
  - “彻底修复” -> “修复”
  - “架构彻底重构” -> “架构原生重构”
  - “彻底移除” -> “移除”
  - “彻底告别” -> “避免”
  - “彻底剥离” -> “解耦剥离”

---

## 6. 留给构建者决策的事项 (What's Left to the Builder)

- 前端编译具体使用的打包命令（优先 `npm run build`）；
- `README.md` 章节合并时的排版美化与细节微调；
- 单测运行脚本的微调保证路径平滑。
