# Web 视图重构、适配器可执行文件配置与死代码清理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Web 视图截图 401 鉴权拦截、新增 `browser_executable_path` 浏览器自定义路径配置、重构前端为 CSS Modules + 集中式 API 层，并清理历史死代码。

**Architecture:** 后端提供携带宿主认证的 Data URL 截图支持与适配器可执行路径传参；前端使用 Vite 原生 CSS Modules 抽离行内样式，并通过独立 `src/api/` 抽象层统一 Bridge 通信与 Mock 回退；彻底移除旧版 V1 工具与废弃测试。

**Tech Stack:** Python 3.10+, Playwright, AstrBot Star / Dashboard Web API, React 18, TypeScript 5, Vite 5, CSS Modules.

**Spec:** [docs/superpowers/specs/2026-11-21-webview-refactor-browser-executable-design.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-21-webview-refactor-browser-executable-design.md)

## Global Constraints

- 保持单页应用（SPA）内部 Memory Router 与 localStorage 状态持久化机制不变。
- 零新增重型前端 npm 依赖（使用 Vite 原生支持的 `*.module.css`，不引入 Tailwind 等）。
- 保持后端 `/audit/screenshot` 向后兼容能力，支持 `format=raw` 二进制直出和 `format=data_url` JSON Base64 格式。
- Python 单元测试必须在沙箱或离线环境中 100% 通过（`python -m unittest discover tests`）。

## Review Focus

- 非法/不存在的截图文件路径或目录越界路径，必须返回标准 HTTP 400/403/404 错误响应而不是 500 崩溃。
- 用户配置包含首尾空格的 `browser_executable_path` 时，需 `strip()` 清理，为空串时不向 `launch()` 传递该参数。
- 前端离线/独立环境无 `window.AstrBotPluginView` 时，API 层必须优雅回退至 Mock 数据，防止界面抛出未捕获异常白屏。
- 截图生成为 Data URL 后，侧边栏抽屉与大图弹窗必须正常渲染预览，并支持 Blob 下载。
- 删除 V1 工具代码后，确保插件主程序 `main.py` 及其他模块中没有任何对其残留的引用或破损的导入。

---

### Task 1: 后端截图预览接口增强 (Data URL / Base64 支持)

**Files:**
- Modify: `api/audit_api.py:166-214`
- Test: `tests/test_audit_api.py:140-210`

**Interfaces:**
- Consumes: `AuditApiHandler.api_audit_screenshot(path: str = "")`
- Produces:
  - 默认或 `format in ("data_url", "base64", "")`: 返回 `json_response({"code": 0, "data": {"data_url": f"data:{media_type};base64,{b64}", "media_type": media_type, "filename": target_path.name}})`
  - `format in ("raw", "binary")`: 返回二进制流响应（FileResponse/Response）

- [ ] **Step 1: 在 `tests/test_audit_api.py` 编写测试用例**

```python
def test_screenshot_route_data_url_default(self):
    import tempfile, base64
    base_dir = Path(tempfile.gettempdir()) / "astrbot_test_audit_data"
    base_dir.mkdir(parents=True, exist_ok=True)
    self.handler.base_dir = base_dir

    test_png = base_dir / "test_data_url.png"
    fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest_data_url"
    with open(test_png, "wb") as f:
        f.write(fake_png_data)

    try:
        audit_api_module.request = None
        res = run_coro(self.handler.api_audit_screenshot(path=str(test_png)))
        data = res.get("data", {}) if isinstance(res, dict) else json.loads(res.body)["data"]
        expected_b64 = base64.b64encode(fake_png_data).decode("utf-8")
        self.assertEqual(data["media_type"], "image/png")
        self.assertEqual(data["data_url"], f"data:image/png;base64,{expected_b64}")
        self.assertEqual(data["filename"], "test_data_url.png")
    finally:
        if test_png.exists():
            test_png.unlink()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m unittest tests.test_audit_api.TestAuditApi.test_screenshot_route_data_url_default`
Expected: FAIL (返回了二进制流而非 data_url JSON 字典)

- [ ] **Step 3: 在 `api/audit_api.py` 中实现 `format` 参数处理与 Base64 编码**

在 `api_audit_screenshot` 中提取 `fmt = extract_query_param(req, "format", "data_url")`：
- 若 `fmt in ("raw", "binary")`，执行既有 `FileResponse` / `Response` 逻辑；
- 否则读取 `target_path` 二进制，Base64 编码为 `f"data:{media_type};base64,{b64}"`，通过 `json_response` 返回。

- [ ] **Step 4: 运行全部审计 API 测试验证通过**

Run: `python -m unittest tests/test_audit_api.py`
Expected: 全部测试 PASS

- [ ] **Step 5: Commit**

```bash
git add api/audit_api.py tests/test_audit_api.py
git commit -m "feat(api): support data_url format in api_audit_screenshot"
```

---

### Task 2: 适配器浏览器可执行文件路径选项 (`browser_executable_path`)

**Files:**
- Modify: `_conf_schema.json:80-100`
- Modify: `adapts/base.py:13-30`
- Modify: `adapts/playwright_adapter.py:21-70`
- Modify: `adapts/factory.py:6-37`
- Test: `tests/test_conf_schema.py`
- Test: `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: `config.get("browser_executable_path", "")`
- Produces: `PlaywrightAdapter(..., executable_path=...)`，在 `browser_launcher.launch(**launch_kwargs)` 中注入 `executable_path`

- [ ] **Step 1: 在 `tests/test_conf_schema.py` 与 `tests/test_adapter_factory.py` 中编写测试用例**

在 `tests/test_conf_schema.py` 中增加断言 `browser_executable_path` 存在且类型为 `string`，默认值为 `""`；
在 `tests/test_adapter_factory.py` 中增加 `test_create_playwright_with_custom_executable_path` 测试，验证 `PlaywrightAdapter` 实例正确持有并向 `launch()` 传递 `executable_path`。

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m unittest tests/test_conf_schema.py tests/test_adapter_factory.py`
Expected: FAIL (配置项不存在或未接收 executable_path)

- [ ] **Step 3: 实现配置与适配器透传**

1. 在 `_conf_schema.json` 中添加：
```json
"browser_executable_path": {
  "type": "string",
  "description": "自定义浏览器二进制可执行文件路径 (留空则使用环境默认浏览器)",
  "default": ""
}
```
2. 在 `adapts/base.py` 中 `BrowserAdapterBase.__init__` 增加 `executable_path: str = ""`。
3. 在 `adapts/playwright_adapter.py` 中接收并在 `start()` 拼接 `launch_kwargs["executable_path"] = self.executable_path.strip()`（当且仅当非空时）。
4. 在 `adapts/factory.py` 中提取 `browser_executable_path = str(config.get("browser_executable_path", "") or "").strip()` 并传递给 `PlaywrightAdapter`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m unittest tests/test_conf_schema.py tests/test_adapter_factory.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json adapts/base.py adapts/playwright_adapter.py adapts/factory.py tests/test_conf_schema.py tests/test_adapter_factory.py
git commit -m "feat(adapter): add browser_executable_path configuration option"
```

---

### Task 3: 清理历史 V1 死代码与过期测试

**Files:**
- Delete: `tools/action_tools.py`
- Delete: `tools/browse_tools.py`
- Delete: `tools/dialog_tools.py`
- Delete: `tools/media_tools.py`
- Delete: `tests/_test_async.py`
- Delete: `tests/test_tools.py`
- Modify: `tools/__init__.py:1-13`
- Modify: `main.py:140-146`

**Interfaces:**
- Consumes: `tools/handlers/` 与 `tools/tools.py`
- Produces: 仅保留模块化 V2 工具；彻底消除废弃的 V1 单体类

- [ ] **Step 1: 清理 `tools/__init__.py`**

确认 `tools/__init__.py` 仅导出 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 以及 `PageHandler`、`InteractHandler`、`MediaHandler`，无任何 V1 工具引用。

- [ ] **Step 2: 删除废弃工具与空测试文件**

删除 `tools/action_tools.py`、`tools/browse_tools.py`、`tools/dialog_tools.py`、`tools/media_tools.py`；
删除 `tests/_test_async.py`、`tests/test_tools.py`。

- [ ] **Step 3: 运行全量单元测试确认无依赖中断**

Run: `python -m unittest discover tests`
Expected: 剩余全部单元测试通过（Ran ~133 tests, OK），没有任何 `ModuleNotFoundError` 或 `ImportError`。

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "chore(tools): remove legacy v1 dead tools and obsolete tests"
```

---

### Task 4: 前端通用 API 抽象层建设 (`web-src/src/api/`)

**Files:**
- Create: `web-src/src/api/client.ts`
- Create: `web-src/src/api/audit.ts`
- Create: `web-src/src/api/lifecycle.ts`
- Create: `web-src/src/api/index.ts`

**Interfaces:**
- Consumes: `window.AstrBotPluginView || window.AstrBotPluginPage`
- Produces:
  - `fetchAuditLogs(params: AuditQueryParams): Promise<AuditLogsResponse>`
  - `fetchAuditStats(): Promise<AuditStats>`
  - `clearAuditLogs(): Promise<boolean>`
  - `exportAuditLogs(format: "json" | "csv"): Promise<any>`
  - `fetchScreenshot(path: string): Promise<string>` (返回 Data URL)
  - `fetchContexts(): Promise<LifecycleContextItem[]>`
  - `fetchAllContexts(): Promise<LifecycleContextItem[]>`
  - `fetchLifecycleLogs(params: LifecycleLogQueryParams): Promise<LifecycleLogResponse>`
  - `killContext(contextKey: string, force?: boolean): Promise<boolean>`
  - `triggerManualScreenshot(contextKey: string, tabIndex?: number): Promise<string>`

- [ ] **Step 1: 实现 `web-src/src/api/client.ts`**

封装统一 Bridge 获取器、`apiRequest<T>()` 方法，内置超时、网络错误捕获与 Mock 回退开关。

- [ ] **Step 2: 实现 `web-src/src/api/audit.ts` 与 `web-src/src/api/lifecycle.ts`**

将原散落在 `AuditView.tsx` 与 `LifecycleView.tsx` 中的 API 请求（包括 `/audit/logs`、`/audit/stats`、`/audit/clear`、`/audit/export`、`/lifecycle/contexts`、`/lifecycle/contexts/all`、`/lifecycle/logs`、`/lifecycle/kill`、`/lifecycle/screenshot`）抽取为强类型函数。
`fetchScreenshot(path)` 内部调用 `apiGet("audit/screenshot", { path, format: "data_url" })` 并返回 `res?.data?.data_url || res?.data_url`。

- [ ] **Step 3: 实现 `web-src/src/api/index.ts` 集中导出**

导出全部 API 函数与入参/出参接口类型。

- [ ] **Step 4: 验证 TypeScript 类型检查**

Run: `npx --prefix web-src tsc --noEmit`
Expected: 检查通过，无类型报错。

- [ ] **Step 5: Commit**

```bash
git add web-src/src/api/
git commit -m "feat(web): extract centralized api client layer"
```

---

### Task 5: 前端 CSS Modules 重构与视图解耦

**Files:**
- Create: `web-src/src/views/AuditView.module.css`
- Create: `web-src/src/views/LifecycleView.module.css`
- Create: `web-src/src/components/TopAppBar.module.css`
- Create: `web-src/src/components/StatsOverview.module.css`
- Create: `web-src/src/components/AuditCard.module.css`
- Create: `web-src/src/components/SideDrawer.module.css`
- Create: `web-src/src/components/ConfirmDialog.module.css`
- Modify: `web-src/src/views/AuditView.tsx`
- Modify: `web-src/src/views/LifecycleView.tsx`
- Modify: `web-src/src/components/TopAppBar.tsx`
- Modify: `web-src/src/components/StatsOverview.tsx`
- Modify: `web-src/src/components/AuditCard.tsx`
- Modify: `web-src/src/components/SideDrawer.tsx`
- Modify: `web-src/src/components/ConfirmDialog.tsx`

**Interfaces:**
- Consumes: `web-src/src/api/index.ts` 与各组件的 `*.module.css`
- Produces: 干净无内联 `style={{ ... }}` 的 JSX，全面绑定新 API 模块

- [ ] **Step 1: 建立各组件专属 CSS Module 文件**

提取 Flexbox 布局、卡片间距、字体与颜色变量绑定，写入 7 个 `.module.css`。

- [ ] **Step 2: 重构 `SideDrawer.tsx` 与 `AuditCard.tsx`**

1. 引入 `styles from './SideDrawer.module.css'`，替换内联样式；
2. 引入 `fetchScreenshot`；获取截图时调用 `fetchScreenshot(item.screenshot_path)` 得到 Data URL；
3. `<img src={screenshotDataUrl} />` 正常渲染；点击在当前弹窗查看或通过 Blob URL 下载。

- [ ] **Step 3: 重构 `LifecycleView.tsx`**

1. 引入 `styles from './LifecycleView.module.css'`；
2. 将原直接调用 `bridge.apiGet / apiPost` 的逻辑全部替换为调用 `fetchContexts`、`fetchAllContexts`、`fetchLifecycleLogs`、`killContext` 与 `triggerManualScreenshot`；
3. 手动截图结果拿到 `screenshot_path` 后通过 `fetchScreenshot` 获取 Data URL 赋给 `previewScreenshotUrl`。

- [ ] **Step 4: 重构 `AuditView.tsx`、`TopAppBar.tsx`、`StatsOverview.tsx` 与 `ConfirmDialog.tsx`**

1. 替换全部行内样式为 CSS Module class；
2. `AuditView.tsx` 切换至调用 `fetchAuditLogs`、`fetchAuditStats`、`clearAuditLogs` 与 `exportAuditLogs`。

- [ ] **Step 5: 执行前端编译构建**

Run: `npm --prefix web-src run build`
Expected: TypeScript 校验通过，Vite 编译成功，构建文件输出至 `views/browser/` 目录下。

- [ ] **Step 6: Commit**

```bash
git add web-src/ views/browser/
git commit -m "refactor(web): migrate inline styles to css modules and wire api layer"
```

---

### Task 6: 全链路集成验证与交付

**Files:**
- Modify: `CHANGELOG.md` (记录变更)

- [ ] **Step 1: 运行全量后端测试**

Run: `python -m unittest discover tests`
Expected: 全部测试通过，覆盖适配器路径、API 格式转换与工具操作。

- [ ] **Step 2: 验证静态资源完整性**

检查 `views/browser/index.html` 以及 `views/browser/assets/*.js`、`*.css` 是否存在且格式正确，确认无语法缺失。

- [ ] **Step 3: 更新 CHANGELOG.md 并 Commit**

```bash
git add CHANGELOG.md
git commit -m "chore(release): complete webview refactor, browser binary path and cleanup"
```
