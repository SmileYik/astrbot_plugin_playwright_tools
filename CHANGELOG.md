# 变更日志 (CHANGELOG)

本项目遵循语义化版本规范。

---

## [v2.2.1] - 2026-11-21

### 截图 401 鉴权服务 (Authenticated Data URL Screenshots)
- **Data URL / Base64 直出**：增强 `AuditApiHandler.api_audit_screenshot`，默认支持返回通过 AstrBot 宿主鉴权通道获取的 Base64 Data URL（`data:image/png;base64,...`），规避 iframe 原生 `<img>` 标签因无法携带 Bearer Token 而被 401 拦截的问题；同时支持 `format=raw` 保持二进制流直出兼容。
- **大图查看与独立下载**：前端侧边抽屉与手动截图弹窗全面支持大图窗口独立渲染与本地下载。

### 浏览器可执行文件自定义 (Custom Browser Executable Path)
- **新增配置项 `browser_executable_path`**：在 `_conf_schema.json` 中提供通用的 `browser_executable_path` 选项，支持用户手动指定 Playwright 适配器对应的浏览器二进制可执行文件路径；若留空则平滑回退至环境中默认安装的浏览器。
- **适配器工厂与启动透传**：`AdapterFactory` 与 `PlaywrightAdapter` 深度对接该配置项，并在 `launch(executable_path=...)` 中安全生效。

### Web 前端现代化与架构重构 (CSS Modules & Centralized API Client)
- **样式全面解耦 (CSS Modules)**：采用 Vite 原生支持的 `*.module.css`，为所有 Views（`AuditView`、`LifecycleView`）与 Components（`TopAppBar`、`StatsOverview`、`AuditCard`、`SideDrawer`、`ConfirmDialog`、`Navbar`、`App`）抽离独立模块样式文件，全面移除 JSX 内联硬编码 `style={{ ... }}`，零新增 npm 依赖。
- **统一 API 客户端层**：在 `web-src/src/api/` 下抽取集中式的 API 模块（`client.ts`、`audit.ts`、`lifecycle.ts`），统一封装 Bridge 探测与类型定义。

### 死代码与过期测试清理 (Dead Code & Legacy Test Cleanup)
- **移除废弃 V1 工具**：安全删除 `tools/action_tools.py`、`tools/browse_tools.py`、`tools/dialog_tools.py`、`tools/media_tools.py`，项目工具层全面由 `handlers/` 与复合 FunctionTool 承担。
- **清理过期测试与空文件**：删除 `tests/_test_async.py` 与 `tests/test_tools.py`，全量单元测试（136 项）秒级通过。

---

## [v2.2.0] - 2026-11-20

### 页面阅读体验与独立分页 (Structured Content & Independent Pagination)
- **结构化 Markdown 正文提炼**：网页正文提炼全面支持提取 `#` 一级标题、`##` 二级标题、`###` 三级标题、段落、列表项及表格 Markdown 语法，消除散碎短行与排版割裂。
- **正文与控件分流独立分页 (`target`)**：`pw_page` 的 `read` 与 `search` 动作支持 `target="all" | "text" | "elements"`（默认 `all`）。大模型可指定 `target="text"` 独立连贯通读文章长篇，或指定 `target="elements"` 专注文档交互控件。
- **可操作元素换行平整化**：可交互控件内的换行符自动归一化单行展示，支持在配置项中自定义连接分隔符 `element_multiline_separator`（默认 `' | '`）。
- **无状态提炼与多租户隔离**：`PageExtractor` 保持无状态单例，各会话快照独立保存在各自的 `ManagedContext.snapshot_data`，保障高并发与多租户隔离。

### 交互报错精炼与操作推荐 (Sanitized Errors & Next-Action Guidance)
- **Playwright 底层报错脱敏与精炼**：编写 `clean_playwright_error`，剥除 Playwright 内部 `Call log:` 及指针拦截冗余日志，对超时、弹层遮挡（`<dialog open>`）、元素失联等场景精简为一句话中文提示。
- **智能下一步行动指引**：在页面打开、阅读完结、元素点击、表单提交及拦截报错后，自动注入针对性 `[推荐操作: ...]` 指引，降低大模型幻觉与无效重试。

### 真实审计落盘与 WebUI 升级 (Real Audit Outputs & Visual Inspector)
- **真实输出与截断配置**：修复审计日志仅记录开始占位符的问题，全面记录真实执行结果；支持配置 `audit_max_output_chars`（默认 `0` 不限，大于 0 时自动截断并附带标记）。
- **截图安全持久化与预览**：新增配置 `audit_save_screenshots`（默认 `true`），仅对 `pw_media` 截图动作落盘至 `data/audit_screenshots/` 并记录相对路径；Web API 提供带目录越界防护的图片服务接口 `GET /{plugin_name}/audit/screenshot`。
- **Web API 分页与离线预览修复**：实现 `extract_query_param` 支持 `args` / `query_params` / `query` 多源参数提取，修复 AstrBot Dashboard 下分页停留在第 1 页的缺陷；前端抽屉支持完整输出检视、复制与截图缩略图展开查看。

### 架构原生重构 (Playwright-Native Architecture Refactor)
- **原生 Playwright 交互体系**：将 `InteractHandler` 中所有点击、表单输入、下拉选择、悬停、聚焦/失焦、拖拽动作重构为 Playwright 原生 Locator API 调用（`locator.click()`、`locator.fill()`、`locator.select_option()`、`locator.drag_to()` 等），全面享受框架自带的可操作性检查与受控组件事件分发，移除裸 JS 字符串注入。
- **解耦浏览器后端适配器**：将 `CamoufoxAdapter` 与通用 `BrowserAdapterBase` 严格解耦，将其职责定位为单一的底层浏览器启动器，向上层完全输出标准的 Playwright `Browser` 与 `BrowserContext`，消除对 Camoufox 的专有强绑定。
- **强类型与官方日志规范**：核心会话上下文与 Handlers 引入 `playwright.async_api` 强类型约束；日志全面采用 AstrBot 官方标准的 `from astrbot.api import logger`。
- **精简测试架构**：移除冗余笨重的端到端集成测试，保留纯净快速的完整单元测试套件（89 项用例秒级通过）。

---

## [v2.1.2] - 2026-11-20

### 稳定性与测试基建 (Stability & Test Infrastructure)
- **真实浏览器端到端测试套件 (Real Browser E2E)**：新增 `tests/e2e/test_real_browser.py` 与本地内置测试静态页夹具（`tests/e2e/fixtures/`），在本地真实 Camoufox 无头环境下全链路自动化测试 `pw_page`、`pw_interact`、`pw_media` 的打开、阅读、搜索、表单输入、按钮点击、下拉选择、页面滚动、Alert 弹窗处理、多标签页切换（`target="_blank"` 与 `switch_tab`）、视口与整页长截图及资源安全释放。
- **规范包导入路径修复**：修正单元测试中遗留的顶层模块导入路径，统一通过标准包路径导入，解决测试运行时的相对导入越界异常，实现全量 85+ 单元测试绿灯通过。
- **异常 Traceback 完整日志保全**：在 Handlers 各动作与顶层 `_execute_with_timeout` 中强化异常捕获，记录完整调用栈信息，避免单行简短异常导致的排查困境。
- **标签页缺省参数修复**：将 `_action_switch_tab` 缺省索引修复为 `1`，与全系统 1-based 语义对齐。
- **依赖声明与规范入宪**：提供标准 `requirements.txt`；在 `AGENT.md` 强制设立硬性规范：代码修改后必须在本机实际执行真实浏览器 E2E 测试并验证通过。

---

## [v2.1.1] - 2026-11-20

### 修复与重构 (Bug Fixes & Refactoring)
- **修复工具协程调用异常**：修复 `tools/tools.py` 中 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 的 `call()` 方法误用异步生成器（`yield`）导致 AstrBot `FuncToolWrapper.call()` 执行抛出 `TypeError: object async_generator can't be used in 'await' expression` 的问题，全面恢复为标准协程（`return`）。截图直发聊天场景改为异步调用 `event.send` 推送图片，同时返回说明文本给大模型。
- **Web API 独立模块化重构**：根据单一职责原则，将原写在 `main.py` 中的审计相关 Web API 路由与业务逻辑（`api_audit_logs`、`api_audit_stats`、`api_audit_export`、`api_audit_clear`）剥离至新建的独立模块 `api/audit_api.py`，`main.py` 仅负责实例化与路由委托挂载。
- **前端 Bridge 响应自适应与构建刷新**：修复 `web-src/src/App.tsx` 在接收 AstrBot Bridge 解包数据时因硬编码检查 `res.code === 0` 导致一直报错“拉取日志失败”的问题，全面自适应 Bridge 解包后的对象结构与标准包裹结构，并重新执行构建将更新后的静态资源同步更新至 `views/audit/`。

---

## [v2.1.0] - 2026-11-20

### 新增与增强 (Features & Enhancements)
- **可视化审计视图 (Visual Audit View)**：在 `metadata.yaml` 声明独立插件页面（`target: plugin_page`），源码采用 Yarn + Vite + React 18 + TS 组织于 `web-src/` 并编译至 `views/audit/`。
- **Material Design 3 大圆角交互设计**：自研轻量级 MD3 组件，采用 16~24px 大圆角与表面色彩体系，自适应 AstrBot 宿主深浅色主题。
- **长文本两行截断预览与右侧抽屉检视**：列表卡片以代码块展示入参单行摘要与输出前 2 行文本，点击任意卡片从右侧平滑滑出大圆角抽屉（Side Drawer Inspector），支持格式化 JSON 树展示、完整结果换行检视与一键快捷复制。
- **审计数据增强与全链路透传**：工具调用链路中纯内存被动探测群聊名称与发送者昵称（私聊标记为 `私聊: {sender_name}`），全链路透传写入 SQLite 审计表。
- **运维与统计管理 Web API**：通过 `context.register_web_api` 注册多维条件检索（`/audit/logs`）、实时指标统计（`/audit/stats`）、全量/筛选日志导出（`/audit/export`，支持 JSON 与 RFC 4180 CSV）及带二次确认的安全清空（`/audit/clear`）。

---

## [v2.0.1] - 2026-11-19

### 优化与重构 (Refactoring)
- **工具方法字典映射分发**：移除 `tools/tools.py` 中三大工具 `call()` 内的 `if-elif-else` 长分支，重构为通过 `self._actions` 字典映射到私有动作方法。
- **统一异步生成器产出**：所有复合工具的 `call()` 统一设计为异步生成器（`yield` 产出结果）。
- **截图消息直发防覆盖**：`pw_media` 截图发送给聊天用户时，改用 `yield event.image_result(path)` 直接交付且立即退出，不再返回额外文本，防止后续消息在聊天界面覆盖图片。

---

## [v2.0.0] - 2026-11-19

### 新增与重构 (Features & Enhancements)
- **类型化大工具聚合**：由分散的原子工具收敛为三大面向对象复合工具（`pw_page`、`pw_interact`、`pw_media`），继承 AstrBot `FunctionTool` 规范并通过 `context.add_llm_tools` 统一以 `pw_` 前缀注册。
- **高级交互操作补齐**：补齐鼠标悬停（`hover`）、元素聚焦（`focus`）、元素失焦（`blur`）、元素拖拽（`drag`）及键盘按键（`press_key`）支持。
- **双重截图熔断机制**：提供视口截图（`screenshot_viewport`）与全页面长截图（`screenshot_full`）；长截图支持配置最大高度限制（默认 8000px，超限截断）与超时熔断（默认 15s，超时自动降级为视口截图）。
- **单工具执行全局超时保护**：每个工具调用封装 `asyncio.wait_for` 超时拦截（默认 30s），超时立即强制中断并返回友好反馈。
- **系统提示词动态注入**：增加 WebUI 配置项 `system_prompt_injection`，通过 `@filter.on_llm_request()` 钩子在大模型请求前动态注入（留空则不注入）。
- **页面内容关键字检索**：新增 `search_page` 动作与 `PageExtractor.search_snapshot` 算法，支持快速搜索包含目标词的文本块及邻近 Ref ID。
- **多租户隔离与权限审计**：
  - 支持个人隔离模式与会话共享模式，提供 `/browser invite/use/close/status` 管理指令。
  - 支持域名通配符与动作级白名单管控。
  - SQLite 记录全生命周期审计日志并支持周期性自动清理。
