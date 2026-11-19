# 规格设计：可视化审计视图与审计数据增强

## 1. 意图与背景 (Intent & The Why)
当前 `astrbot_plugin_playwright_tools` 虽然通过 SQLite 记录了详细的工具调用与安全拦截日志，但缺乏可视化操作界面。排查问题时，管理员难以直观查看带有大量 DOM 结构摘要、长参数 JSON 与执行结果的审计记录，且现有数据库仅记录了抽象的 `session_id` 与 `sender_id`，缺乏人员与会话的直观辨识度。

本次工程旨在为插件增加符合 AstrBot 规范的独立插件页面（`target: plugin_page`），提供基于 Material Design 3 大圆角风格的高颜值、易排查可视化审计视图，并对底层审计系统实施字段与接口增强。

## 2. 目标与非目标 (Goals, Non-Goals & Anti-Goals)

### 2.1 目标 (Goals)
1. **前端工程化规范**：在 `web-src/` 目录下搭建 Vite + React + TypeScript 项目，依赖由 Yarn 管理，编译输出至 `views/audit/`。
2. **MD3 大圆角视觉风格**：采用 16px ~ 24px 大圆角卡片、MD3 色彩 tokens 与高低表面层次，通过 `window.AstrBotPluginView` Bridge 自动适配宿主明暗主题。
3. **列表卡片设计（基础信息 + 长文本头部预览）**：列表条目呈现状态徽章、时间、工具动作标签、会话名称、发送者昵称及目标 URL，并在卡片内直接内嵌入参摘要与输出快照前 2 行预览（超出自动折叠截断并标明字符量）。
4. **右侧滑出抽屉（Side Drawer Inspector）**：点击卡片滑出大圆角抽屉，提供完整的元数据排查、带换行和高亮的长文本检视、格式化 JSON 查看与一键复制功能。
5. **运维与排查操作**：支持按会话名/发送者/工具/状态/正文关键字多维检索，支持日志导出为 JSON 与 CSV 格式（支持当前筛选导出与全量导出），支持带确认二次校验的手动清空操作。
6. **后台宿主天然鉴权**：依据 AstrBot 原生架构，能登录 WebUI 打开独立插件页面即代表已具备管理员身份，插件自身 Web API 不做多余二次权限校验。
7. **审计数据增强**：
   - 数据库表 `tool_audit_logs` 直接包含 `session_name` 与 `sender_name` 列（本项目处于初期开发阶段，无需兼容性迁移逻辑）。
   - 工具调用链自动从 `AstrMessageEvent` 进行纯内存被动安全探测群名与发送者昵称（私聊记为 `私聊: {sender_name}`），绝不发起外部网络 I/O，全链路透传记账。
   - 在 `main.py` 通过 `context.register_web_api` 暴露日志分页查询、统计数据、文件导出与日志清空接口。

### 2.2 非目标 (Non-Goals)
1. 不实现聊天消息内嵌交互组件（`chat_message`）或对话工作台，专专注管理运维独立页面（`plugin_page`）。
2. 不开发复杂的浏览器实时 CDP 画面视频流投屏。

### 2.3 反目标 (Anti-Goals)
1. 严禁引入体积数兆的笨重 UI 框架（如 MUI/AntD），严格避免 iframe 加载卡顿。
2. 严禁阻塞工具调用主链路引入外部网络 I/O。

## 3. 技术约束与规范 (Constraints)
1. **AstrBot 插件视图规范**：
   - `metadata.yaml` 声明：`name: audit, target: plugin_page, title: 审计监控`。
   - 入口文件为 `views/audit/index.html`，Vite 打包配置必须设置 `base: "./"`。
   - 前端通过 `window.AstrBotPluginView` Bridge 进行 `ready()` 初始化与 `bridge.apiGet` / `apiPost` 调用。
2. **构建管理**：前端依赖严格使用 `yarn` 管理，源码在 `web-src/`，构建产物在 `views/audit/`。
3. **代码风格规范**：严格遵守 [AGENT.md](../../../AGENT.md)，文档与注释凝练简洁，不搞过度抽象。

## 4. 架构备选方案评估 (Approaches)
- **方案 1：轻量自建 MD3 设计规范组件（React + MD3 CSS Tokens）—— [已选定]**
  - **实现**：基于 React + TS 编写大圆角卡片、状态 Chip、右侧 Side Sheet 抽屉与代码查看器，原生接入 AstrBot Bridge 注入的主题 CSS 变量。
  - **权衡**：产物体积微小（< 100KB），构建极快，无第三方样式冲突，长文本折叠排版完全自由可控。用户已明确选择该方案。
- **方案 2：引入全量 Material UI 库（MUI `@mui/material` + Emotion）—— [已放弃]**
  - **权衡**：开箱即用但产物体积膨胀数兆，样式覆盖繁琐，在 iframe 宿主内开销大。
- **方案 3：Google `@material/web` Web Components 方案 —— [已放弃]**
  - **权衡**：React 绑定繁琐且部分复杂抽屉组件未成熟。

## 5. 详细系统设计 (Detailed System Design)

### 5.1 目录结构
```text
astrbot_plugin_playwright_tools/
├── web-src/                      # 前端源代码工程
│   ├── package.json              # yarn 依赖与构建脚本
│   ├── vite.config.ts            # 构建配置（输出至 ../views/audit）
│   ├── tsconfig.json             # TypeScript 配置
│   ├── index.html                # HTML 入口模板
│   └── src/
│       ├── main.tsx              # 应用入口挂载
│       ├── App.tsx               # 主应用容器（AppBar、Filters、List、Drawer）
│       ├── astrbot-bridge.d.ts   # Bridge 接口类型声明
│       ├── components/
│       │   ├── TopAppBar.tsx     # 顶部导航、搜索输入、导出与清空操作
│       │   ├── StatsOverview.tsx # 调用总量、成功率与分类状态指标 Chips
│       │   ├── AuditList.tsx     # 审计卡片虚拟/自适应滚动列表
│       │   ├── AuditCard.tsx     # 单条卡片（状态、时间、名称、长文本头部两行预览）
│       │   └── SideDrawer.tsx    # 右侧滑出长文本抽屉（JSON高亮、快照排版、一键复制）
│       ├── styles/
│       │   └── theme.css         # MD3 CSS 设计变量与大圆角规则
│       └── types.ts              # 审计数据结构接口
├── views/
│   └── audit/                    # 前端编译生产产物 (index.html + assets)
├── core/
│   └── audit_logger.py           # 表结构自动迁移、分页多维检索、导出与清空
├── tools/
│   ├── handlers/                 # 透传 session_name 与 sender_name
│   └── tools.py                  # 从 AstrMessageEvent 提取元数据并注入
├── main.py                       # 注册 /audit/logs, /stats, /export, /clear Web API
└── metadata.yaml                 # 声明 views 独立页面
```

### 5.2 数据库增强 (`core/audit_logger.py`)
1. **表结构升级**：
   在 `CREATE TABLE IF NOT EXISTS tool_audit_logs` 中直接声明 `session_name` 与 `sender_name` 字段（项目初创，无历史用户，无需 `ALTER TABLE` 迁移）：
   ```sql
   CREATE TABLE IF NOT EXISTS tool_audit_logs (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       timestamp TEXT NOT NULL,
       session_id TEXT NOT NULL,
       session_name TEXT DEFAULT '',
       context_key TEXT NOT NULL,
       sender_id TEXT NOT NULL,
       sender_name TEXT DEFAULT '',
       tool_name TEXT NOT NULL,
       url TEXT,
       input_args TEXT,
       output_result TEXT,
       is_permitted INTEGER NOT NULL,
       deny_reason TEXT,
       is_error INTEGER NOT NULL,
       error_message TEXT
   )
   ```
2. **新增核心方法**：
   - `log_action(..., session_name: str = "", sender_name: str = "")`: 写入新增字段。
   - `query_logs(page: int, page_size: int, keyword: str = "", status: str = "all", tool_name: str = "") -> tuple[list[dict], int]`: 支持多条件筛选与分页。
   - `get_stats() -> dict`: 返回 `{ total, allowed, denied, error, today_count }`。
   - `export_logs(fmt: str = "json", keyword: str = "", status: str = "all", tool_name: str = "") -> str`: 支持全量或按当前筛选条件输出 JSON 字符串或标准 CSV 文本。
   - `clear_logs() -> int`: 清空全部记录并返回删除条数。

### 5.3 后端 Web API 规范 (`main.py`)
**鉴权说明**：
无需在插件内编写冗余的拦截器。由于 AstrBot 的 WebUI 后台本身必须管理员登录方可进入，凡是能够访问本独立插件页面（`target: plugin_page`）并调用插件 Bridge 的会话均视为具备管理员身份，后端接口直接提供服务。

**接口列表**（使用 `context.register_web_api` 注册）：
- `GET /astrbot_plugin_playwright_tools/audit/logs`:
  - Query: `page=1&page_size=20&keyword=&status=all&tool_name=`
  - 响应: `{ "code": 0, "data": { "total": int, "items": [...], "page": int, "page_size": int } }`
- `GET /astrbot_plugin_playwright_tools/audit/stats`:
  - 响应: `{ "code": 0, "data": { "total": int, "allowed": int, "denied": int, "error": int, "today_count": int } }`
- `GET /astrbot_plugin_playwright_tools/audit/export`:
  - Query: `format=json|csv&keyword=&status=all&tool_name=`
  - 响应: 包含对应格式数据的下载文件响应或 JSON 负载。
- `POST /astrbot_plugin_playwright_tools/audit/clear`:
  - Body: `{ "confirm": true }`
  - 响应: `{ "code": 0, "data": { "cleared": int } }`

### 5.4 前端界面与长文本交互 (`web-src/`)
1. **列表卡片 (AuditCard)**：
   - 卡片圆角 `20px`，边框在鼠标悬停时过渡为 MD3 Primary 强调色。
   - 顶部区域：状态徽章（绿色 ALLOWED / 红色 DENIED / 橙色 ERROR）、工具标签（`pw_page: open`）、时间、会话名、发送者昵称及目标 URL。
   - 摘要区域：等宽字体浅色代码预览区，入参 JSON 单行省略，输出结果限制 2 行预览，超出显示 `...(剩余 N 字符已折叠)`。
2. **右侧滑出抽屉 (SideDrawer)**：
   - 从右侧平滑滑出，具有大圆角阴影。
   - 展示详细元数据、入参 JSON（格式化缩进展示，提供一键复制）、执行结果/DOM快照（支持搜索、换行与全屏代码弹窗）、错误与拒绝原因（警示红框）。
3. **运维工具条 (TopAppBar)**：
   - 搜索框集成防抖检索；
   - 导出下拉菜单（一键生成并触发下载 `.json` 或 `.csv`）；
   - 清空按钮（弹出 MD3 确认对话框，二次确认后触发清空并刷新列表）。

## 6. 留给构建者的细节 (Left to the Builder)
1. CSV 导出的特殊字符（双引号、换行符）转义处理。
2. 前端单条卡片在会话名或发送者名称为空时的优雅兜底回退显示（显示 ID）。
3. 构建脚本中处理 `yarn build` 确保产物可靠输出至 `views/audit/`。
