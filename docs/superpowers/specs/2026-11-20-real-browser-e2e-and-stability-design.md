# 真实浏览器端到端集成测试与运行时稳定性设计规范

## 1. 背景与意图 (Intent and Why)

当前插件在实际运行（如大模型调用、容器或外部环境）中，容易由于未在真实浏览器环境充分验证而产生各类运行时异常（如 Playwright 属性错误、参数越界等）。此外，项目原有的测试均基于 `MagicMock`，无法检验真实的浏览器启动、页面导航、DOM 提取与用户交互。

本设计的核心目标是**去繁就简、实事求是**：
1. 规范化修正包导入，使代码在作为 AstrBot 插件运行和作为本地测试执行时均能正常导入，消除历史残留的导入错误。
2. 编写一套**基于本地真实 Camoufox 浏览器的端到端（E2E）集成测试集**，用本地测试页面真实测试 `pw_page`、`pw_interact`、`pw_media` 的核心交互。
3. 完善异常捕获与调用栈日志输出，出问题时能第一时间定位具体文件和行号。
4. 明确开发规范：每次修改工具代码后，必须在本机运行真实浏览器测试并确认通过。

---

## 2. 目标、非目标与反目标 (Goals, Non-goals, Anti-goals)

### 目标 (Goals)
1. **真实端到端测试 (`tests/e2e/test_real_browser.py`)**：在本地真实拉起 Camoufox 无头浏览器，对 `pw_page`、`pw_interact`、`pw_media` 进行全流程调用并断言实际 DOM 与渲染结果。
2. **本地测试页面 (Local Fixture)**：使用内置的独立 HTML 静态测试页（包含常用可交互元素、表单、弹窗、超长文本等），由本地轻量 HTTP 服务承载，不依赖外网，5-10 秒内稳定跑完。
3. **规范标准包导入**：统一采用标准的包路径导入（`from astrbot_plugin_playwright_tools...` 或规范相对导入），修正旧单测中的错误导入路径，使所有单元测试与集成测试全部绿灯通过。
4. **真实异常日志保全**：在关键执行点发生异常时，完整记录 `traceback.format_exc()` 到日志，不再仅给出一个无法排查的单行错误。
5. **极简依赖与规范更新**：提供标准的 `requirements.txt`（包含 `camoufox[geoip]`、`playwright`），在 `AGENT.md` 明确“改完必跑真实浏览器测试”的规范。

### 非目标 (Non-goals)
- 不做过度设计的导入兼容（如各种 try-except 双重防御），写对路径即可。
- 不搞复杂的版本锁定矩阵，Camoufox 与 Playwright 保持常规正常依赖。
- 不依赖外网站点进行测试。

### 反目标 (Anti-goals)
- 严禁假测试：测试代码中不得使用 Mock 替代真实浏览器。

---

## 3. 详细设计 (Detailed Design)

### 3.1 导入路径规范化
项目中代码属于包 `astrbot_plugin_playwright_tools`：
- 在 `tests/` 中的旧测试文件（如 `test_context_manager.py`、`test_page_handler.py` 等），将其错误的顶层导入 `from core...` / `from tools...` 统一修正为规范的包导入 `from astrbot_plugin_playwright_tools.core...`。
- 内部模块之间的相对导入保持清晰规范，无需添加额外的防御分支。

### 3.2 本地测试页面 (`tests/e2e/fixtures/`)
创建 `tests/e2e/fixtures/test_page.html`，包含以下测试用例所需的真实 DOM 结构：
- **页面基本信息**：标题 `<title>Playwright Tools E2E Test Page</title>` 及段落文本。
- **表单控件**：
  - `<input id="test-input" name="username" placeholder="请输入内容">`
  - `<select id="test-select"><option value="opt1">选项一</option><option value="opt2">选项二</option></select>`
  - `<button id="test-btn" onclick="document.getElementById('result').innerText='clicked'">点击测试</button>`
  - `<div id="result">初始状态</div>`
- **弹窗控件**：
  - `<button id="btn-alert" onclick="alert('测试弹窗内容')">触发Alert</button>`
- **多标签页控件**：
  - `<a id="link-new-tab" href="/newtab.html" target="_blank">打开新标签页</a>`
- **长页面**：
  - 多个高度区块（总高度 > 2500px），用于测试页面滚动与截图熔断。
同时提供简单的 `tests/e2e/fixtures/newtab.html`。

### 3.3 真实 E2E 集成测试 (`tests/e2e/test_real_browser.py`)
使用真实的 `CamoufoxAdapter(headless=True)`，内置后台轻量 HTTP 服务器承载测试页，测试链路涵盖：
1. **页面生命周期**：
   - `pw_page(action="open", url=...)`：加载页面，校验标题与可交互元素识别。
   - `pw_page(action="read", page=1)`：分页查看页面快照文本。
   - `pw_page(action="search", keyword="点击测试")`：检索目标关键词。
2. **元素交互操作**：
   - `pw_interact(action="fill", ref=..., text="Hello Playwright")`：验证文本输入。
   - `pw_interact(action="click", ref=...)`：验证按钮点击及页面内容变化。
   - `pw_interact(action="select", ref=..., value="opt2")`：验证下拉选择。
   - `pw_interact(action="scroll", direction="down", distance=500)`：验证页面滚动。
3. **弹窗应答**：
   - `pw_page(action="dialog", dialog_action="accept")`：预设弹窗自动接受。
   - 点击 Alert 按钮，验证弹窗被捕获应答，工具未阻塞。
4. **多标签页切换**：
   - 点击 `<a target="_blank">` 打开新标签页。
   - `pw_page(action="switch_tab", tab_index=2)` 切换到新页并验证。
   - `pw_page(action="switch_tab", tab_index=1)` 切回主页。
   - 修复 `tools/tools.py` 中 `_action_switch_tab` 缺省值为 1（保持 1-based 计数）。
5. **屏幕与长图截取**：
   - `pw_media(action="screenshot_viewport", target="chat")`：验证视口截图生成。
   - `pw_media(action="screenshot_full", target="chat")`：验证长截图生成。
6. **资源释放**：
   - `pw_page(action="close")`：验证关闭当前浏览器上下文，进程资源安全释放。

### 3.4 异常日志保全
在 `tools/handlers/` 中，捕获未预期异常时使用 `logger.error` 记录完整的 `traceback.format_exc()`，避免仅有一句简短错误导致无法定位具体行号；`_execute_with_timeout` 同步记录超时与漏网异常调用栈。

### 3.5 依赖与规范
1. 根目录补充标准 `requirements.txt`：
   ```text
   camoufox[geoip]
   playwright
   pyyaml
   ```
2. 更新 `AGENT.md`：
   明确开发硬性约束：“每次编写或修改工具代码后，必须在本机运行 `tests/e2e/test_real_browser.py` 并在真实 Camoufox 浏览器中测试通过。”
