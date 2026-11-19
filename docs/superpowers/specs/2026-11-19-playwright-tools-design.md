# 插件设计文档：astrbot_plugin_playwright_tools

## 1. 目标与背景 (Intent & The Why)

本插件旨在为 `AstrBot` 机器人框架提供一套基于 `Playwright`（首选 `Camoufox` 浏览器驱动）的自动化浏览器工具集。
通过向大模型暴露结构简洁、语义明确的 Tool 接口，使 AI 能够代替聊天用户执行网页访问、信息阅读、表单填写、文件下载、屏幕截图等复杂任务。
同时，针对多用户、多会话的机器人使用场景，建立严格的多租户浏览器上下文隔离、域名与操作级权限白名单、审计日志体系，并遵循项目 [AGENT.md](../../../AGENT.md) 中关于“极简、克制、无隐式假设、文档凝练”的规范。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals & Anti-Goals)

### 2.1 目标 (Goals)
1. **大模型友好交互**：通过 DOM 元素编号引用（Ref ID）与长页面自动分页机制，让大模型以最低的 Token 消耗、最确定的定位方式与网页进行交互。
2. **多租户隐私隔离与协作**：支持“个人模式”与“会话模式”。个人模式支持指令邀请协作者；具备明确的多上下文寻址与提示策略；所有上下文生命周期独立且支持超时回收与指令关闭。
3. **安全与权限管控**：提供管理员模式与域名通配符白名单模式，实现页面跳转、弹出新标签页（popup）与跨域 iframe 的顶级导航守卫（Navigation Guard）。
4. **行为审计与追踪**：采用 SQLite 记录工具调用的全要素数据，支持配置日志留存期并自动清理。
5. **Cookie 安全隔离**：支持标准 `storage_state.json` 注入，且限定仅管理员上下文可用，防止特权会话泄露。
6. **适配器可扩展**：底层设计 `BrowserAdapter` 抽象层，初期实现 `CamoufoxAdapter`，预留 `ChromiumAdapter` 接入点。

### 2.2 非目标 (Non-Goals)
1. 不开发专门针对特定网站的爬虫定制逻辑或逆向打码逻辑（验证码遇阻直接如实报告）。
2. 不提供跨服务器的多节点浏览器集群调度（单实例单节点运行）。
3. 不在插件内实现复杂的视觉坐标点击模型（优先依赖 DOM Ref ID 交互）。

### 2.3 反目标 (Anti-Goals)
1. **杜绝将包含隐私的凭证直接返回给 AI**：严禁向大模型泄露管理员 Cookie 或敏感 StorageState。
2. **杜绝向 AI 倾泻原始 HTML**：绝对避免将完整 DOM / HTML 原文塞进大模型上下文，防止上下文爆炸。
3. **杜绝越权与逃逸**：普通用户或协作者不得利用大模型绕过域名白名单或越权访问他人上下文。

---

## 3. 技术约束与规范 (Constraints)
1. **文档与注释规范**：严格遵照 `AGENT.md`，文档、注释及返回给 AI 的提示必须凝练简洁，不啰嗦。
2. **架构原则**：坚持 Simplicity First，杜绝过度抽象与投机性特性；坚持 Surgical Changes 与 Goal-Driven 开发。
3. **版本协同**：`metadata.yaml` 与 `main.py` 严格保持版本号与元数据同步。
4. **环境要求**：Python 3.10+，基于 AstrBot 插件标准规范。

---

## 4. 架构备选方案评估 (Approaches)

### 备选方案 1：分层服务架构（Layered Service Architecture）—— **[已选定]**
- **结构划分**：
  - `adapts/`：底层浏览器适配器（`BrowserAdapterBase`, `CamoufoxAdapter`）。
  - `core/`：核心业务服务，包括上下文管理（`ContextManager`）、安全与白名单守卫（`SecurityManager`）、DOM 精简与 Ref ID 分页抽取（`PageExtractor`）、审计日志（`AuditLogger`）。
  - `tools/`：大模型工具定义，按功能分组。
  - `main.py`：插件注册与指令（`/browser invite`, `/browser use`, `/browser close` 等）。
- **权衡**：模块职责单一明晰，代码精简，各模块单测极易 Mock，后续维护成本低。

### 备选方案 2：中间件管道架构（Middleware Pipeline Architecture）—— **[已放弃]**
- **权衡**：引入类似 Web 框架的请求管道（`AuthMiddleware` -> `GuardMiddleware` -> `AuditMiddleware`）。对于轻量级机器人插件属于过度抽象，增加调用栈深度与调试阻碍。

### 备选方案 3：单体控制器模式（Monolithic Controller）—— **[已放弃]**
- **权衡**：所有状态逻辑放在单一 Controller 中。前期简单，但很快会膨胀至数千行不可维护代码，违背工程原则。

---

## 5. 详细系统设计 (Detailed System Design)

### 5.1 目录结构
```text
astrbot_plugin_playwright_tools/
├── adapts/
│   ├── __init__.py
│   ├── base.py                 # BrowserAdapter 抽象基类
│   └── camoufox_adapter.py     # Camoufox 驱动实现
├── core/
│   ├── __init__.py
│   ├── context_manager.py      # 上下文生命周期、隔离模式、寻址路由与协作管理
│   ├── security_manager.py     # 域名通配符白名单、操作授权、顶级导航守卫
│   ├── page_extractor.py       # DOM 精简、Ref ID 映射、文本分页
│   └── audit_logger.py         # SQLite 审计记账与过期清理
├── tools/
│   ├── __init__.py
│   ├── browse_tools.py         # open_url, read_page, switch_tab, close_browser
│   ├── action_tools.py         # click, fill_form, select_option, scroll
│   ├── media_tools.py          # take_screenshot, download_file
│   └── dialog_tools.py         # handle_dialog
├── docs/
│   └── ...
├── _conf_schema.json           # AstrBot WebUI 配置定义
├── main.py                     # 插件入口、指令与工具注册
├── metadata.yaml               # 插件元信息
└── AGENT.md
```

### 5.2 页面表示与 Ref ID 协议 (Page Representation)
1. **DOM 提炼与交互树**：
   - 注入轻量 JavaScript 脚本提取可见交互元素（`button`, `a`, `input`, `select`, `textarea`, `[role=button]` 等）。
   - 每个元素分配自增整数标号 `[1]`, `[2]`, ...，内存中维护 `ref_id -> ElementHandle/Locator` 映射字典。
2. **长内容分页与提示**：
   - 配置阈值 `max_page_char_length`（默认 2500 字符）。
   - 超过阈值时按块截断，输出带明确分页引导的简洁 Markdown：
     ```text
     === 页面: {title} (URL: {url}) [标签页: {tab_idx}/{tab_total}] [分页: {cur_page}/{total_pages}] ===
     {page_compact_content}
     --- [提示: 本页未完，剩余 {remain} 页，可调用 read_page(page={next_page}) 查看后续] ---
     ```
3. **Ref ID 生命周期**：
   - 页面 URL 发生导航跳转、刷新或切换 Tab 时，自动清空旧映射并重新生成。

### 5.3 浏览器上下文隔离与生命周期 (Context & Lifecycle)
1. **隔离模式**：
   - **个人模式（Personal Mode）**：Key 为 `(session_id, owner_uid)`。创建者为 owner，维护 `allowed_users: Set[str]`。
   - **会话模式（Session Mode）**：Key 为 `session_id`。同一会话内所有人共享同一浏览器实例。
2. **多上下文寻址与路由策略（用户决定）**：
   - **自身优先**：若用户自身拥有活跃上下文，默认操作自己的上下文；
   - **最近活跃回退**：若用户没有自己的上下文，则默认路由到最近活跃的被受邀上下文；
   - **显式切换指令**：提供 `/browser use @用户` 或 `/browser use <owner_uid>` 显式指定当前会话所指向的操作目标；
   - **多上下文操作提示**：在多上下文场景下，工具返回给大模型的系统前缀中明确标明 `[当前操作上下文: 用户X的浏览器]`，引导 AI 在回复中告知用户当前执行的目标上下文。
3. **指令管理与释放**：
   - `/browser invite @用户`：邀请协作者加入当前个人上下文。
   - `/browser close`：供用户主动关闭并释放**自己拥有的个人上下文**（释放内存）。
   - `/browser status`：查看当前绑定的上下文及可用标签页信息。
4. **生命周期调度**：
   - **惰性启动**：首次有浏览器操作工具调用时才启动 Context。
   - **空闲超时**：配置项 `idle_timeout_minutes`（默认 10 分钟），无操作自动关闭 Context 释放内存。
   - **AI 主动销毁**：AI 调用 `close_browser` 工具（可在配置中开关是否向大模型注册该工具）。

### 5.4 权限与白名单守卫 (Security & Guard)
1. **权限模式分支**：
   - `admin_only = True`：仅全局管理员与插件配置额外管理员 UID 可调用。
   - `admin_only = False`：白名单模式生效。
2. **白名单规则配置**：
   - 格式：域名匹配串（支持通配符 `*.example.com`、`http*://example.com/*`）绑定允许的行为列表 `["read", "click", "fill", "scroll", "screenshot", "download", "tab", "dialog"]`。
3. **导航守卫（Navigation Guard - 构建者决策）**：
   - 仅对**顶级导航请求**（`request.is_navigation_request()`）、`page.on("popup")`（新建标签页）以及跨域 iframe 操作执行白名单与动作校验；
   - 允许白名单页面正常加载 CDN 脚本、CSS、字体、图片等静态子资源，避免页面渲染崩溃。
   - 若目标 URL 未命中白名单或缺失对应行为权限，直接中止跳转并抛出结构化拒绝信息给大模型。
4. **权限继承**：
   - 个人模式下受邀参与者执行操作时，校验的权限基准均以该上下文的 `owner` 权限配置为准。

### 5.5 Cookie 与认证隔离 (Cookie Management)
1. **存储格式**：使用 Playwright 标准 `storage_state.json` 规范（含 cookies 和 localStorage）。
2. **注入策略**：
   - 配置文件中指定 `storage_state_path` 或预填各站点 Cookie。
   - **严格限定**：仅当上下文创建者属于管理员时，创建 Context 时载入该状态；普通用户上下文始终使用空沙箱环境。

### 5.6 媒体与交互工具 (Media & Tools)
1. **截图控制 (`take_screenshot`)**：
   - 参数：`target: "chat" | "ai"`。
   - 配置开关：`allow_screenshot_to_ai`（布尔值）。
   - 逻辑：若 AI 请求 `target="ai"` 但配置中 `allow_screenshot_to_ai=False`，立即拦截并返回拒绝原因；若 `target="chat"`，通过 AstrBot 消息链直接发送图片给用户。
2. **文件下载与交付 (`download_file` - 构建者决策)**：
   - 监听 Playwright 的 `download` 事件，将文件转存到 `data/downloads/`；
   - 优先通过 AstrBot `File` 消息组件将下载文件直接发送给聊天用户；若平台适配器不支持文件上传，则降级发送本地存储路径通知。
3. **弹窗处理 (`handle_dialog` - 构建者决策)**：
   - 默认启用自动放行模式（Auto-accept alert/confirm），避免 Playwright 异步协程挂起死锁，并将弹窗消息（如 `"已检测到弹窗: '操作成功'，已自动确认"`）附在工具执行返回中；
   - 提供 `handle_dialog(action="accept"|"dismiss", prompt_text=None)` 工具供 AI 在预期有输入提示弹窗时预先配置下一次响应策略。

### 5.7 审计日志 (Audit Logging)
1. **SQLite 存储**：存储在 `data/audit.db`，表名 `tool_audit_logs`。
2. **字段定义**：`id`, `timestamp`, `session_id`, `context_key`, `sender_id`, `tool_name`, `url`, `input_args`, `output_result`, `is_permitted`, `deny_reason`, `is_error`, `error_message`。
3. **自动轮询清理**：配置项 `audit_retention_days`（默认 30 天），插件启动及定时器中执行 `DELETE FROM tool_audit_logs WHERE timestamp < ?`。

---

## 6. 留给构建者的实现细节 (Left to the Builder)
1. 具体的 DOM 提取脚本（JavaScript 代码编写与跨浏览器兼容）。
2. SQLite 异步连接与写入封装（避免阻塞主事件循环）。
3. AstrBot `_conf_schema.json` 的具体表单控件布局与默认值细化。
4. 各工具的 Docstring 按照 AstrBot 规范（`Args:` 段等）编写。
