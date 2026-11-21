# 网页视图重构、适配器可执行文件配置与死代码清理设计规范

## 1. 概述与背景 (Intent & Why)

当前 `astrbot_plugin_playwright_tools` 插件在实际使用中存在以下痛点：
1. **Web 视图截图 401 鉴权拦截**：插件控制台前端组件（`SideDrawer`、`LifecycleView`）直接使用原生 `<img>` 标签请求 `/api/v1/plugins/extensions/.../audit/screenshot`。由于 AstrBot Dashboard 对插件扩展接口启用了 Bearer JWT 鉴权（`require_plugin_scope`），而 iframe 内的原生图片请求无法自动附加父页面的 Bearer Token，导致截图加载时均被 401 拦截拒绝。
2. **缺乏浏览器二进制自定义能力**：在某些服务器或环境上，Playwright 默认安装的浏览器可能受系统库依赖限制或需要使用特定定制的 Chromium/Chrome/Edge 可执行文件，目前插件无法指定自定义路径。
3. **Web 前端样式硬编码与 API 散乱**：前端各个组件与视图内混杂了上百处内联 `style={{ ... }}`，代码可读性差、不易复用；API 调用直接通过全局 `window.AstrBotPluginView` 裸调，散落在各个组件内部，缺乏统一的请求抽象、类型定义与错误处理。
4. **历史死代码遗留**：`tools/` 根目录下遗留了旧版 V1 工具实现（`action_tools.py`、`browse_tools.py`、`dialog_tools.py`、`media_tools.py`），且包含仅测试旧工具的 `tests/test_tools.py` 与空文件 `tests/_test_async.py`，需一并清理以保持工程整洁。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **解决截图 401 问题**：截图获取改由统一的前端 API 模块通过 `bridge.apiGet` 携带宿主凭据向后端请求，后端支持返回 Base64 Data URL（或直接直出），前端通过 `data:image/...;base64,...` 或 Blob URL 渲染，确保在 AstrBot Dashboard 中 100% 正常显示并支持弹窗大图与下载。
2. **新增 `browser_executable_path` 配置**：在 `_conf_schema.json` 中提供通用的 `browser_executable_path` 选项，当指定时作为 `executable_path` 传给 Playwright 的 `launch()` 方法；若未指定则默认沿用环境内置浏览器。
3. **前端样式解耦与现代化**：采用 Vite 原生支持的 **CSS Modules**（`*.module.css`），将各组件内的硬编码内联样式全部抽离，复用 `theme.css` 中的全局主题变量。
4. **统一前端 API 客户端**：在 `web-src/src/api/` 下抽取集中式的 API 模块（`client.ts`、`audit.ts`、`lifecycle.ts`），规范请求签名、返回值类型和离线 Mock 回退逻辑。
5. **清理死代码**：删除旧版 V1 工具及过期测试，确保全量自动化单元测试 100% 通过。

### 非目标 (Non-Goals)
- 不修改 AstrBot 核心的 JWT 鉴权中间件架构。
- 不引入 Tailwind CSS、UnoCSS 等重型原子化 CSS 框架以防构建依赖膨胀。
- 不改变现有的单页应用（SPA）内存路由（Memory Routing）机制。

### 反目标 (Anti-Goals)
- 严禁将明文 Token 或特权 Key 注入或硬编码在前端静态打包产物中。
- 严禁破坏现有后端接口的向后兼容性（`/audit/screenshot` 保留 `format=raw` 模式以兼容可能的二进制直出需求）。

---

## 3. 技术方案与技术决策 (Approaches & Trade-offs)

### 3.1 Web 前端样式组织方案
- **备选方案 A：Vite 原生 CSS Modules（选定）**
  - **评估**：Vite 原生支持 `[name].module.css`，零新增 npm 依赖，编译后自动进行作用域哈希隔离，完美继承当前已有的 CSS 变量（`var(--color-primary)` 等）。开发体验极佳，彻底消灭 JSX 标签内联 `style` 臃肿问题。
- **备选方案 B：全局普通 CSS + BEM 命名**
  - **评估**：无构建期作用域隔离，类名容易随着组件增加而冲突或膨胀，维护成本随项目演进而升高。
- **备选方案 C：引入 Tailwind CSS / UnoCSS**
  - **评估**：需要引入 PostCSS、Tailwind 配置文件以及多个开发依赖，对于轻量内嵌插件的前端构建包而言过于重型。

### 3.2 截图 401 修复方案
- **备选方案 A：通过 Bridge API 请求 Base64 Data URL（选定）**
  - **评估**：AstrBot 插件页面内置的 `window.AstrBotPluginView.apiGet` 会通过父页面 `PluginViewFrame.vue` 发起 Axios 请求，天然携带当前登录用户的 JWT Bearer Token。后端返回 Base64 编码的 Data URL 后，前端将其赋给 `img.src`，整个过程无需通过原生浏览器 GET 接口跨域请求图片，彻底杜绝 401。
- **备选方案 B：通过后端生成短期临时 Ticket URL**
  - **评估**：需要设计 Ticket 签发、失效与内存清理机制，且增大了后端状态同步复杂度，不够轻巧。

---

## 4. 详细设计与技术规格 (Detailed Design)

### 4.1 后端：截图预览接口增强 (`api/audit_api.py`)
在 `AuditApiHandler.api_audit_screenshot` 中新增 `format` 参数支持：
- 参数 `format`：可选值 `data_url` / `base64`（默认）或 `raw` / `binary`。
- 流程：
  1. 验证 `path` 是否在 `base_dir` 合法范围内（越界防护，防止目录遍历攻击）。
  2. 若 `format in ("raw", "binary")`：返回原有的 `FileResponse` / `Response` 二进制流（保留向后兼容能力）。
  3. 若 `format in ("data_url", "base64", "")`（默认）：读取图片二进制内容，进行 Base64 编码，生成形如 `data:image/png;base64,...` 的 Data URL，返回标准 JSON 结构：
     ```json
     {
       "code": 0,
       "data": {
         "data_url": "data:image/png;base64,...",
         "media_type": "image/png",
         "filename": "screenshot_xxx.png"
       }
     }
     ```

### 4.2 后端：浏览器二进制路径选项 (`browser_executable_path`)
1. **配置架构** (`_conf_schema.json`):
   ```json
   "browser_executable_path": {
     "type": "string",
     "description": "自定义浏览器二进制可执行文件路径 (留空则使用环境默认浏览器)",
     "default": ""
   }
   ```
2. **适配器工厂** (`adapts/factory.py`):
   读取 `config.get("browser_executable_path", "")` 并传递给适配器构造函数。
3. **适配器实现** (`adapts/playwright_adapter.py`):
   `PlaywrightAdapter.__init__` 接收 `executable_path: str = ""`。在 `start()` 方法中：
   ```python
   launch_kwargs = {"headless": self.headless}
   if self.executable_path and self.executable_path.strip():
       launch_kwargs["executable_path"] = self.executable_path.strip()
   self._browser = await browser_launcher.launch(**launch_kwargs)
   ```

### 4.3 前端：统一 API 客户端架构 (`web-src/src/api/`)
建立目录 `web-src/src/api/`，划分为以下模块：
1. **`client.ts`**:
   - 封装 `getBridge()` 检测 `window.AstrBotPluginView || window.AstrBotPluginPage`。
   - 实现 `apiRequest<T>(endpoint: string, method: "GET" | "POST", payload?: any): Promise<T>`。
   - 统一异常捕获与离线模拟数据（Mock）回退逻辑。
2. **`audit.ts`**:
   - `fetchAuditLogs(params: AuditQueryParams): Promise<AuditLogsResponse>`
   - `fetchAuditStats(): Promise<AuditStats>`
   - `clearAuditLogs(): Promise<boolean>`
   - `exportAuditLogs(format: "json" | "csv"): Promise<any>`
   - `fetchScreenshot(path: string): Promise<string>`（调用 `apiGet("audit/screenshot", { path, format: "data_url" })`，返回 `data_url`）
3. **`lifecycle.ts`**:
   - `fetchContexts(): Promise<LifecycleContextItem[]>`
   - `fetchAllContexts(): Promise<LifecycleContextItem[]>`
   - `fetchLifecycleLogs(params: LifecycleLogQueryParams): Promise<LifecycleLogResponse>`
   - `killContext(contextKey: string, force?: boolean): Promise<boolean>`
   - `triggerManualScreenshot(contextKey: string, tabIndex?: number): Promise<string>`
4. **`index.ts`**: 统一对外导出上述所有方法与类型。

### 4.4 前端：样式模块化重构 (CSS Modules)
将所有行内样式迁移至各组件对应的 CSS Module：
- `web-src/src/views/AuditView.module.css` -> 用于审计检索、日志分页与过滤面板
- `web-src/src/views/LifecycleView.module.css` -> 用于上下文卡片、标签页列表、预览弹窗
- `web-src/src/components/TopAppBar.module.css` -> 顶部导航栏、视图切换 Switcher、操作按钮
- `web-src/src/components/StatsOverview.module.css` -> 指标卡片网格
- `web-src/src/components/AuditCard.module.css` -> 单条审计条目与详情展开
- `web-src/src/components/SideDrawer.module.css` -> 抽屉侧边栏、DOM 快照与截图预览
- `web-src/src/components/ConfirmDialog.module.css` -> 模态确认对话框
所有颜色与排版变量均直接引用已在 `theme.css` 定义的 CSS 变量（如 `var(--color-bg-card)`、`var(--color-border)`）。

### 4.5 死代码与旧测试清理
1. 删除 `tools/action_tools.py`、`tools/browse_tools.py`、`tools/dialog_tools.py`、`tools/media_tools.py`。
2. 清理 `tools/__init__.py`，仅保留 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 以及各 `Handler`。
3. 删除 `tests/_test_async.py`（0 字节空文件）。
4. 删除 `tests/test_tools.py`（该测试仅覆盖已删除的旧版 V1 工具类；现有 `test_tools_v2.py` 与各 handler 测试已完全覆盖业务逻辑）。
5. 检查并清理 `main.py` 中遗留的历史别名（如 `self.api_audit_logs = ...` 若无需对外暴露可精简或保留）。

---

## 5. 留给构建者的实现细节 (Left to the Builder)
- CSS 类名的具体语义化命名（如 `.container`、`.filterRow`、`.previewImage` 等）。
- 离线/预览环境下若无真实图片时的 Mock SVG 生成保持现状并封装入 `api/audit.ts`。
- 构建前端时对产物哈希命名与 `views/browser/` 的同步复制。
