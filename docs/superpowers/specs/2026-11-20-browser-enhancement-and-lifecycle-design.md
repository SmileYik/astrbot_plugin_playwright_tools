# 浏览器自动化增强、成熟正文提炼与会话生命周期管理设计规范

## 1. 背景与目标 (Intent & Why)

当前 `astrbot_plugin_playwright_tools` 插件在实际使用中存在以下痛点：
1. **正文提取不准与连续换行过多**：原提取脚本依赖固定的 CSS 选择器（如 `article, main, #content`）并只提取 `<p>` 标签，导致在百度贴吧、复杂论坛等使用 `div` 容器与 `<br>` 分行的页面中，无法抓取主贴正文，反而误将右侧登录/推广栏识别为正文；同时拼接换行未规范化，产生了大量连续空白行。
2. **审计页面截图无法正常显示 & 切页拉回**：截图直接采用相对路径通过 `<img>` 加载，未通过 AstrBot 鉴权与正确路径路由，导致 404；前端 `TopAppBar` 搜索防抖由于依赖项闭包刷新，导致点击“下一页”时定时器重新触发重置 `page = 1`。
3. **缺少底层适配器配置与 Playwright 原生浏览器支持**：仅硬编码了 `CamoufoxAdapter(headless=True)`，缺少原生 Playwright（Chromium、Firefox、WebKit）支持，且缺少窗口大小、UserAgent 等初始化配置。
4. **媒体文件管理不全**：缺少图片格式（JPG/PNG）与压缩质量选择；下载与截图路径不可配；缺少过期文件被动清理机制。
5. **缺少会话生命周期追踪与管理**：大模型与用户开启的浏览器上下文生命周期缺乏独立数据追踪；缺少专门的管理界面来实时查看活跃上下文、标签页列表、激活页以及手动页面截图。

本设计旨在一次性解决上述所有问题，提供工业级的成熟提炼算法、完善的多适配器体系、独立生命周期追踪表与 Web 会话管理界面、文件被动清理机制以及扩展的管理指令。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **成熟正文与元素提炼**：
   - 引入 Mozilla Readability 核心算法（DOM 密度评分与正文提取），精准提炼正文，支持 `div`、`<br>`、表格、列表等多种内容形态；
   - 智能排除干扰节点（脚本、样式、广告、导航栏、登录弹窗等）；
   - 换行归一化：连续空行折叠至最多 `\n\n`，列表项保持紧凑单换行 `\n`；
   - 元素提取去噪：过滤不可见、侧边栏重复作者/勋章、空链接与装饰性节点，优先提炼主要交互区域的高价值控件。
2. **二进制流图片直出与前端 Bug 修复**：
   - 后端 `/audit/screenshot` 提供标准二进制流（`FileResponse` / `Response`，带正确 `Content-Type`），避免 Base64 膨胀；
   - 修复前端 `TopAppBar` 与 `App` 组件的切页防抖拉回 Bug。
3. **独立生命周期管理 (SQLite + Web 页面)**：
   - SQLite 新增 `context_lifecycle_logs` 表，记录上下文创建、加入、超时销毁、主动/强制关闭等明细；
   - Web 端在 `metadata.yaml` 增加 `lifecycle` 视图，提供专门的**会话生命周期管理页面**；
   - 页面支持实时查看活跃上下文（Session ID, Context Key, 所有者, 协作者, 空闲倒计时）；
   - 展开查看会话内部各标签页（标题、URL、是否为激活页）；
   - 提供**一键手动截图**（保存至截图目录，并记入 `tool_audit_logs` 审计与日志）；
   - 提供**一键强制关闭**（销毁上下文并写入生命周期表）。
4. **适配器工厂与扩展配置**：
   - 支持 `camoufox`（默认）与 `playwright` 原生驱动（支持 `chromium` / `firefox` / `webkit`）；
   - 支持配置窗口大小（宽/高）、UserAgent、无头模式、GeoIP；
   - 支持截图格式选择（`png` / `jpeg`）与质量（1-100）；
   - 支持自定义下载保存路径与截图保存路径；
   - 支持配置保存天数（`file_retention_days`），并在调用截图或下载工具时被动清理过期文件。
5. **CLI 管理指令扩展**：
   - `/browser list`：查看当前会话活跃上下文；
   - `/browser list-all`：查看全平台所有活跃上下文（仅管理员）；
   - `/browser kill <context_key>`：强制关闭指定上下文并释放资源（仅管理员）。

### 非目标 (Non-Goals)
- 无需考虑旧数据库迁移兼容（由于当前无存量用户，升级时可直接创建或重构表结构）。
- 不引入外部远程打码服务或重型 OCR 模型。

### 反向目标 (Anti-Goals)
- 避免过度提取无效 DOM 导致大模型上下文 Token 爆炸。
- 避免被动清理进行耗时的全盘同步遍历，采用非阻塞的目录文件扫描。

---

## 3. 架构方案评估 (Approaches)

### 方案 A：内嵌 Readability 核心提炼 + 抽象适配工厂 + 双视图 Web 体系（已采纳）
- **正文提炼**：在浏览器端注入经过精简打包的 Readability 算法引擎，结合 DOM 语义打分与纯净 Markdown 序列化，辅以 Python 端的高性能正则规范化过滤；
- **适配器**：抽象 `BrowserAdapterBase`，提供 `CamoufoxAdapter` 与 `PlaywrightAdapter` 两套实现，由 `AdapterFactory` 依据 `_conf_schema.json` 动态构建；
- **生命周期**：SQLite 新增 `context_lifecycle_logs` 表；Web 模块采用多视图构建，生成 `views/audit` 与 `views/lifecycle`；
- **媒体流**：后端直接返回二进制流，前端通过标准扩展路径或 Blob 加载，省去 Base64 编解码开销。
- **优点**：成熟可靠，提炼准确率极高，架构解耦清晰，运行性能最高。

### 方案 B：Python 端纯解析 (如 BeautifulSoup / Trafilatura) + 单页面混合 Tab
- 将整个网页 HTML 传回 Python 端再用第三方库解析。
- **缺点**：对于重度 SPA（单页应用）或需要先在 DOM 打标签（`data-astr-ref`）与控件交互的场景，HTML 传回解析后无法与浏览器内实际可见 DOM 节点一一对齐，导致元素 Ref 映射错位。故排除。

---

## 4. 详细设计 (Detailed Design)

### 4.1 数据模型设计 (SQLite)

在 SQLite 数据库中，保留原 `tool_audit_logs` 表，并新增 `context_lifecycle_logs` 表：

```sql
CREATE TABLE IF NOT EXISTS context_lifecycle_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,       -- create, close, timeout, join, switch, force_kill
    session_id TEXT NOT NULL,
    session_name TEXT DEFAULT '',
    context_key TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,      -- 操作发起人 UID (系统超时销毁时为 'system')
    details TEXT DEFAULT '{}'       -- JSON 结构: 包含初始参数、标签页数、激活URL、原因等
);
```

### 4.2 配置规范 (`_conf_schema.json`)

新增/优化的配置字段：
- `browser_adapter`: `{"type": "string", "description": "浏览器适配器 (camoufox / playwright)", "default": "camoufox"}`
- `playwright_browser_type`: `{"type": "string", "description": "Playwright 原生浏览器内核 (chromium / firefox / webkit)", "default": "chromium"}`
- `browser_window_width`: `{"type": "int", "description": "浏览器初始视口宽度 (像素)", "default": 1280}`
- `browser_window_height`: `{"type": "int", "description": "浏览器初始视口高度 (像素)", "default": 720}`
- `browser_user_agent`: `{"type": "string", "description": "自定义 User-Agent (留空使用默认)", "default": ""}`
- `browser_headless`: `{"type": "bool", "description": "是否以无头模式运行浏览器", "default": true}`
- `camoufox_geoip`: `{"type": "bool", "description": "Camoufox 是否启用 GeoIP 定位防检", "default": false}`
- `screenshot_format`: `{"type": "string", "description": "截图文件格式 (png / jpeg)", "default": "png"}`
- `screenshot_quality`: `{"type": "int", "description": "截图质量 (1-100，仅当格式为 jpeg 时生效)", "default": 80}`
- `download_save_path`: `{"type": "string", "description": "下载文件保存路径", "default": "data/downloads"}`
- `screenshot_save_path`: `{"type": "string", "description": "截图文件保存路径", "default": "data/screenshots"}`
- `file_retention_days`: `{"type": "int", "description": "截图与下载文件的保存天数 (超过将自动被动清理)", "default": 7}`

### 4.3 浏览器适配器抽象与工厂 (`adapts/`)

- `BrowserAdapterBase`：定义统一接口：
  - `start()` / `stop()`
  - `create_context(storage_state_path=None) -> BrowserContext`
  - 统一应用 `viewport`、`user_agent`、`headless` 参数。
- `CamoufoxAdapter`：封装 `AsyncCamoufox`，注入 `geoip` 与初始化尺寸。
- `PlaywrightAdapter`：封装原生 Playwright，支持 `async_playwright`，动态启动 `chromium` / `firefox` / `webkit`。
- `AdapterFactory`：依据配置一键实例化。

### 4.4 正文提炼与元素提炼引擎 (`core/page_extractor.py`)

1. **正文提炼算法**：
   - 注入成熟的 Readability 启发式算法：
     - 去噪层：自动删除 `script, style, noscript, nav, header, footer, aside, .sidebar, .login-box, .advertisement` 等；
     - 容器打分层：依据段落文本长度、标点密度、链接文本比率（Link Density）评估得分，定位真正的主内容容器；
     - 块级解析层：支持 `div`（将含 `<br>` 的行分割解析为段落）、`p`、`h1-h6`、`ul/ol/li`、`table`、`blockquote`、`pre/code`；
   - 格式归一化：
     - 段落与标题之间合并为标准双换行 `\n\n`；
     - 列表项紧凑排版，采用单换行 `\n`；
     - 正则清理：`re.sub(r'\n{3,}', '\n\n', text).strip()`。
2. **元素提炼算法**：
   - 排除非关键区域（侧边栏、免责声明页脚、重复作者名卡片）的密集无效链接；
   - 仅对可见、具有实质可点击语义或表单交互的元素分配 `data-astr-ref`；
   - 去重同名同目标的多余元素，精简 Token。

### 4.5 媒体管理与被动清理 (`tools/handlers/media_handler.py`)

1. **截图参数适配**：
   - 当 `screenshot_format == "jpeg"` 时，调用 `page.screenshot(type="jpeg", quality=screenshot_quality)` 并保存为 `.jpg`；否则为 `png`；
   - 返回标准本地路径 `[IMAGE_PATH:...]`。
2. **被动清理逻辑**：
   - 封装异步辅助函数 `_cleanup_expired_files(target_dir, retention_days)`；
   - 每次调用 `screenshot_viewport`、`screenshot_full` 或 `download_file` 时触发；
   - 扫描目标目录，对比文件修改时间 `mtime < now - retention_days * 86400`，超期文件执行 `os.remove`。

### 4.6 会话生命周期与审计接口 (`api/`)

1. **接口列表**：
   - `GET /{plugin_name}/audit/logs`: 审计日志列表
   - `GET /{plugin_name}/audit/stats`: 审计指标统计
   - `GET /{plugin_name}/audit/screenshot`: **直出二进制流**（`FileResponse(filepath, media_type=mime)`）
   - `GET /{plugin_name}/lifecycle/active`: 获取所有当前活跃的会话及其标签页明细
   - `GET /{plugin_name}/lifecycle/logs`: 获取生命周期历史记录（分页）
   - `POST /{plugin_name}/lifecycle/screenshot`: 对指定上下文的指定标签页手动截图并记入审计/日志
   - `POST /{plugin_name}/lifecycle/kill`: 强行关闭指定上下文
2. **生命周期事件埋点**：
   - `ContextManager` 在发生以下事件时，调用 `AuditLogger.log_lifecycle(...)`：
     - `create`: 上下文被创建
     - `close`: 用户主动关闭
     - `timeout`: 空闲超时回收
     - `join`: 协作者加入/切换
     - `force_kill`: 管理员强制终止

### 4.7 Web 前端工程 (`web-src/`)

- 在 `metadata.yaml` 声明两个视图：
  - `audit`: 网页工具审计
  - `lifecycle`: 会话生命周期管理
- 修复 `TopAppBar` 的 `useEffect` 循环触发 Bug：
  - `onKeywordChange` 绑定稳定回调；
  - 仅在 `searchInput !== keyword` 时触发回调。
- 前端截图展示组件：
  - `<img src="/api/v1/plugins/extensions/${pluginName}/audit/screenshot?path=${encodeURIComponent(path)}" />`，浏览器自动携带登录态 Cookie 并直读二进制流。
- 新增 `LifecycleView` 页面组件：
  - 卡片式展示所有活跃的上下文、所有者与协作者标签；
  - 展开卡片可实时查看其打开的所有标签页列表（标题、URL、是否激活）；
  - “手动截图”按钮：触发截图后弹窗查看预览并提供下载；
  - “强行关闭”按钮：二次确认后终止上下文。

### 4.8 管理指令扩展 (`main.py`)

- `/browser list`：
  - 遍历当前会话相关的活跃上下文，输出上下文 Key、所有者、协作者、当前激活网页 URL、标签页总数。
- `/browser list-all`：
  - 管理员鉴权：若非管理员拒绝执行；
  - 输出全平台所有活跃上下文的列表概览。
- `/browser kill <context_key>`：
  - 管理员鉴权：强行关闭目标上下文，释放浏览器内存，并在生命周期表中记录 `force_kill`。

---

## 5. 实施要点与验证计划 (Verification Plan)

1. **单元测试与集成测试**：
   - 测试 `PageExtractor` 对论坛类富 HTML 的提取效果（验证贴吧格式 `div+br` 正文被完整提取、换行无冗余）；
   - 测试 `AdapterFactory` 对 `camoufox` 与 `playwright` 的初始化和参数传递；
   - 测试 `media_handler` 的被动清理机制与 JPG 截图质量参数；
   - 测试 `AuditLogger` 新增 `context_lifecycle_logs` 的写入与查询；
   - 测试 `/audit/screenshot` 的二进制流响应；
   - 测试 `/browser list`、`/browser list-all`、`/browser kill` 指令逻辑与权限判断。
2. **前端构建与联调**：
   - 运行 Vite 构建，输出 `views/audit` 与 `views/lifecycle`；
   - 验证切页时不会被拉回第 1 页；
   - 验证截图抽屉能正常渲染直出二进制图片。
