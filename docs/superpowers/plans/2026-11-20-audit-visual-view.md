# 可视化审计视图与审计数据增强实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为插件新增基于 Material Design 3 大圆角风格的可视化审计视图（`web-src/` Vite + React + TS 构建至 `views/audit/`），列表卡片展示基础元数据与长文本头部预览，点击滑出大圆角抽屉检视全量格式化长文本，并增强后端审计数据（记录会话名与发送者昵称）及提供 Web API 接口。

**Architecture:**
- **后端**：在 `core/audit_logger.py` 中更新建表语句增加 `session_name` 和 `sender_name`，实现多维分页查询、指标统计、导出（JSON/CSV）及清空；`tools/tools.py` 与各个 Handler 纯内存提取会话名与发送者名并持久化；`main.py` 注册 4 个 Web API 端点并在 `metadata.yaml` 声明独立插件视图。
- **前端**：在 `web-src/` 下用 Yarn + Vite + React + TS 搭建轻量级 MD3 组件系统（卡片流、长文本预览、右侧 Side Sheet 抽屉、搜索筛选操作栏），打包输出至 `views/audit/`，通过 AstrBot Bridge API 通信并自适应宿主主题。

**Tech Stack:** Python 3.10+, SQLite3, AstrBot Plugin Web API, React 18, Vite 5/6, TypeScript, Yarn.

**Spec:** [docs/superpowers/specs/2026-11-20-audit-visual-view-design.md](../specs/2026-11-20-audit-visual-view-design.md)

## Global Constraints

- 前端源码必须严格放置在 `web-src/` 目录下，并使用 `yarn` 管理。
- 前端打包产物必须输出至 `views/audit/`，且 `vite.config.ts` 的 `base` 必须设为 `"./"`。
- 严禁在工具主链路中为了拉取群名/发送者而发起外部网络 I/O。
- Web API 直接服务于能够登录 AstrBot WebUI 的用户，无需在插件内部进行二次权限拦截。
- 严格遵循 [AGENT.md](../../../AGENT.md) 极简原则，所有文档与代码保持凝练清晰。

## Review Focus

1. 数据库建表与写入完整性：新增 `session_name` 与 `sender_name` 后，所有字段能正确写入与读取，无 NULL 引发异常。
2. 模糊检索与条件过滤组合：关键词跨字段（URL、入参、结果、报错、名称）搜索时，SQL 占位符与分页 `LIMIT / OFFSET` 计算准确。
3. 导出格式转义安全性：CSV 导出长文本时包含换行、双引号或逗号时必须遵循 RFC 4180 严格转义，不破坏表格行结构。
4. 内存被动提取健壮性：当 `event` 中缺乏 `group` 或 `get_sender_name` 属性时，安全回退到 ID 或空串，不崩溃。
5. 前端长文本渲染与防溢出：数千字符的 DOM 快照或 JSON 在卡片内准确截断 2 行且不撑裂布局，抽屉内滚动自如并支持一键复制。

---

### Task 1: `AuditLogger` 数据库结构扩展与查询/统计/导出/清空 API

**Files:**
- Modify: `core/audit_logger.py`
- Test: `tests/test_audit_logger.py`

**Interfaces:**
- Consumes: SQLite `tool_audit_logs` 表
- Produces: `AuditLogger` 具备 `query_logs`, `get_stats`, `export_logs`, `clear_logs` 方法

- [ ] **Step 1: 在 `tests/test_audit_logger.py` 中编写针对新增字段及查询/统计/导出/清空方法的测试用例**

```python
def test_log_action_with_names_and_queries(self):
    # 测试写入 session_name 与 sender_name
    # 测试 query_logs 分页与 keyword 模糊查询
    # 测试 get_stats 统计指标
    # 测试 export_logs 输出 JSON 与 CSV
    # 测试 clear_logs 清空
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m unittest tests/test_audit_logger.py`
Expected: FAIL（`query_logs` 等方法尚未定义，`log_action` 参数不匹配）

- [ ] **Step 3: 在 `core/audit_logger.py` 中实现结构升级与核心方法**

1. 修改 `_ensure_db`，在 `CREATE TABLE IF NOT EXISTS tool_audit_logs` 中增加 `session_name TEXT DEFAULT ''` 与 `sender_name TEXT DEFAULT ''`。
2. 更新 `log_action` 参数列表支持 `session_name: str = ""` 与 `sender_name: str = ""`，并调整 SQL `INSERT` 字段。
3. 实现 `async def query_logs(self, page: int = 1, page_size: int = 20, keyword: str = "", status: str = "all", tool_name: str = "") -> tuple[list[dict], int]`：
   - 动态构造 `WHERE` 子句（处理 keyword 模糊匹配 `url`, `input_args`, `output_result`, `error_message`, `session_name`, `sender_name`；处理 status 对应 `is_permitted`, `is_error`；处理 tool_name）。
   - 查询总量 `COUNT(*)` 与分页记录 `LIMIT ? OFFSET ?`。
4. 实现 `async def get_stats(self) -> dict`：统计总记录数、允许数、拒绝数、错误数、今日调用数。
5. 实现 `async def export_logs(self, fmt: str = "json", keyword: str = "", status: str = "all", tool_name: str = "") -> str`：
   - 复用查询条件，根据 `fmt` 生成格式化 JSON 字符串或标准 RFC 4180 CSV 字符串。
6. 实现 `async def clear_logs(self) -> int`：执行 `DELETE FROM tool_audit_logs` 并返回行数。

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m unittest tests/test_audit_logger.py`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add core/audit_logger.py tests/test_audit_logger.py
git commit -m "feat(audit): add session/sender names, query, stats, export and clear methods"
```

---

### Task 2: 全链路传递 `session_name` 与 `sender_name` (Tools & Handlers)

**Files:**
- Modify: `tools/tools.py`
- Modify: `tools/handlers/page_handler.py`
- Modify: `tools/handlers/interact_handler.py`
- Modify: `tools/handlers/media_handler.py`
- Test: `tests/test_tools_v2.py`

**Interfaces:**
- Consumes: `AstrMessageEvent`
- Produces: `_extract_event_and_metadata` 返回 `(event, session_id, sender_id, session_name, sender_name)`，所有 Handler 接收并传递给 `audit_logger.log_action`

- [ ] **Step 1: 在 `tests/test_tools_v2.py` 中编写元数据提取与传递的测试用例**

编写模拟带有 `event.get_sender_name()` 和 `event.message_obj.group.group_name` 的测试，验证 Handler 调用 `log_action` 时正确传入了名称。

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: FAIL

- [ ] **Step 3: 更新 `tools/tools.py` 与各 Handler**

1. 在 `tools/tools.py` 中重命名/升级 `_extract_event_and_ids` 为 `_extract_event_and_metadata(context) -> tuple[Any, str, str, str, str]`：
   - 提取 `session_id`, `sender_id`。
   - 提取 `sender_name`：优先调用 `event.get_sender_name()`，未实现则读 `event.message_obj.sender.nickname`，默认回退 `sender_id`。
   - 提取 `session_name`：若存在 `event.message_obj.group.group_name` 则使用群名；否则为私聊时标记为 `f"私聊:{sender_name}"`；默认回退 `session_id`。
2. 更新三大工具的 `call` 方法，解构出 5 元组并将 `session_name` 与 `sender_name` 传给底层私有动作方法。
3. 更新 `PageHandler`、`InteractHandler`、`MediaHandler` 中的各方法签名及对 `audit_logger.log_action(...)` 的调用，补全透传 `session_name` 和 `sender_name`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tools/tools.py tools/handlers/ tests/test_tools_v2.py
git commit -m "feat(tools): forward session_name and sender_name throughout tool execution chain"
```

---

### Task 3: 注册后端 Web API 与声明 `metadata.yaml` 视图

**Files:**
- Modify: `main.py`
- Modify: `metadata.yaml`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: `AuditLogger` 查询与运维方法
- Produces: Web API 路由 (`/{PLUGIN_NAME}/audit/logs`, `/stats`, `/export`, `/clear`) 与 metadata 视图声明

- [ ] **Step 1: 在 `tests/test_plugin_main.py` 中增加对 Web API 注册与 metadata 视图字段的测试**

```python
def test_metadata_views_declared(self):
    # 验证 metadata.yaml 中包含 views 声明且 target 为 plugin_page

def test_web_api_routes_registered(self):
    # 验证 context.register_web_api 正确注册了 4 个 audit 路由
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m unittest tests/test_plugin_main.py`
Expected: FAIL

- [ ] **Step 3: 在 `metadata.yaml` 与 `main.py` 中注册视图和接口**

1. 在 `metadata.yaml` 增加：
   ```yaml
   views:
     - name: audit
       target: plugin_page
       title: 网页工具审计
       description: 查看 Playwright 自动化网页工具的执行明细、DOM快照与安全拦截审计日志
   ```
2. 在 `main.py` 的 `PlaywrightToolPlugin.__init__` 中注册 4 个 Web API：
   - `/{PLUGIN_NAME}/audit/logs` (GET) -> `api_audit_logs`
   - `/{PLUGIN_NAME}/audit/stats` (GET) -> `api_audit_stats`
   - `/{PLUGIN_NAME}/audit/export` (GET) -> `api_audit_export`
   - `/{PLUGIN_NAME}/audit/clear` (POST) -> `api_audit_clear`
3. 编写对应的异步 handler 方法，通过 `astrbot.api.web`（`json_response`, `request`, `file_response` 等）对接 `AuditLogger`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m unittest tests/test_plugin_main.py`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add main.py metadata.yaml tests/test_plugin_main.py
git commit -m "feat(api): register audit Web APIs and declare plugin_page in metadata"
```

---

### Task 4: 搭建前端 `web-src/` 工程脚手架与构建管道

**Files:**
- Create: `web-src/package.json`
- Create: `web-src/vite.config.ts`
- Create: `web-src/tsconfig.json`
- Create: `web-src/index.html`
- Create: `web-src/src/main.tsx`
- Create: `web-src/src/types.ts`
- Create: `web-src/src/astrbot-bridge.d.ts`

**Interfaces:**
- Consumes: Node.js, Yarn, Vite
- Produces: 打包输出目录 `views/audit/index.html` 与编译静态资源

- [ ] **Step 1: 在 `web-src/package.json` 中配置基础依赖与构建脚本**

依赖项包括 `react`, `react-dom`, `@types/react`, `@types/react-dom`, `vite`, `@vitejs/plugin-react`, `typescript`。
脚本包括 `"build": "vite build"`, `"dev": "vite"`。

- [ ] **Step 2: 配置 `vite.config.ts`**

配置 `base: "./"`, `build.outDir: "../views/audit"`, `build.emptyOutDir: true`。

- [ ] **Step 3: 创建 `web-src/src/types.ts` 与 `astrbot-bridge.d.ts`**

声明 `AuditLogItem`, `AuditStats`, `QueryParams` 接口与 `window.AstrBotPluginView` 桥接方法声明。

- [ ] **Step 4: 运行 yarn install 与 yarn build 验证产物生成**

Run: `cd web-src && yarn && yarn build`
Expected: 成功构建并在 `views/audit/` 下生成 `index.html` 及 `assets/`。

- [ ] **Step 5: 提交更改**

```bash
git add web-src/ views/audit/
git commit -m "chore(web): setup Vite React TS scaffold with yarn and build pipeline"
```

---

### Task 5: 实现 Material Design 3 前端审计界面

**Files:**
- Create: `web-src/src/styles/theme.css`
- Create: `web-src/src/components/TopAppBar.tsx`
- Create: `web-src/src/components/StatsOverview.tsx`
- Create: `web-src/src/components/AuditCard.tsx`
- Create: `web-src/src/components/SideDrawer.tsx`
- Modify: `web-src/src/App.tsx`
- Build Output: `views/audit/`

**Interfaces:**
- Consumes: 后端 `/audit/logs`, `/stats`, `/export`, `/clear` API 及 Bridge
- Produces: 完整交互式单页应用

- [ ] **Step 1: 编写 `web-src/src/styles/theme.css`**

定义 MD3 大圆角（`--radius-lg: 16px`, `--radius-xl: 24px`）、色彩体系与自适应宿主变量。

- [ ] **Step 2: 编写 `AuditCard.tsx` 组件**

1. 渲染状态 Chip（ALLOWED/DENIED/ERROR）、工具 Badge、时间戳、会话名、发送者昵称及 URL。
2. 渲染浅色代码背景的入参摘要（单行省略）及输出/DOM快照前部内容（限制 2 行预览，超出显示省略与字符折叠提示）。
3. 鼠标悬停大圆角阴影过渡，点击触发父组件选中条目打开抽屉。

- [ ] **Step 3: 编写 `SideDrawer.tsx` 抽屉检视器组件**

1. 右侧滑出的大圆角 Side Sheet 面板。
2. 包含完整元数据、格式化缩进的 JSON 入参（带复制按钮）、执行结果与 DOM 快照长文本（支持换行、搜索、全屏查看和一键复制）、报错/拒绝详情。

- [ ] **Step 4: 编写 `TopAppBar.tsx` 与 `StatsOverview.tsx`**

1. 搜索栏带防抖输入、状态下拉筛选、今日调用/允许/拒绝/错误指标 Chips。
2. 导出按钮触发 JSON/CSV 下载（联动当前筛选参数）。
3. 清空按钮弹出 MD3 确认弹窗，确认后清空日志并刷新列表。

- [ ] **Step 5: 在 `App.tsx` 串联 Bridge 与状态交互**

1. 调用 `await bridge.ready()`，并挂载 `bridge.onContext` 监听主题切换。
2. 封装 `bridge.apiGet` / `apiPost` 的数据获取与错误提示机制。
3. 支持分页（上一页、下一页、每页条数选择）。

- [ ] **Step 6: 执行前端编译构建与产物校验**

Run: `cd web-src && yarn build`
Expected: 构建成功，`views/audit/index.html` 完整生成。

- [ ] **Step 7: 提交更改**

```bash
git add web-src/ views/audit/
git commit -m "feat(web): implement Material Design 3 audit viewer with drawer and long text preview"
```

---

### Task 6: 文档同步与全量回归测试

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Test: All unit tests in `tests/`

- [ ] **Step 1: 运行全量 Python 单元测试**

Run: `python3 -m unittest discover tests`
Expected: 全部测试通过 (OK)

- [ ] **Step 2: 更新架构文档与变更日志**

在 `docs/ARCHITECTURE.md` 中补充 Web 视图与 Web API 分层架构，在 `CHANGELOG.md` 中记录 v2.1.0 视图与审计增强特性。

- [ ] **Step 3: 提交文档**

```bash
git add docs/ARCHITECTURE.md CHANGELOG.md README.md
git commit -m "docs: update architecture and changelog for visual audit view"
```
