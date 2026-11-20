# Playwright 原生重构设计规范 (Playwright-Native Refactor Design Doc)

## 1. 背景与意图 (Intent and Why)

当前插件虽然命名为 `astrbot_plugin_playwright_tools`，但在过去的实现中严重脱离了 Playwright 本身：
1. **去 Playwright 化与裸 JS 滥用**：交互模块（`interact_handler.py`）充斥着大量的 `page.evaluate()` 字符串脚本，通过裸 JS `document.querySelector().click()` 模拟用户交互，完全绕过了 Playwright 的原生自动等待（Auto-waiting）和可操作性检查（Actionability checks），在现代前端单页应用（React/Vue 受控组件、动态渲染节点）中极易静默失效或点击无响应。
2. **与 Camoufox 错误强耦合**：整个代码库直接依赖 `camoufox`，未将 Camoufox 严格限制在“Playwright 浏览器实例启动器”的适配器职责内，上层无法无缝切换原生 Chromium/Firefox。
3. **类型系统退化**：核心模块通篇使用 `Any`，缺乏 `playwright.async_api`（`Page`, `BrowserContext`, `Browser`, `Locator` 等）强类型约束，不仅缺少 IDE 补全与静态检查，也极易引入私有属性导入错误。

**重构核心意图**：
根据项目原始需求规范（`InitialRequirementsList.md`），彻底重写 `adapts/`、`core/`、`tools/` 模块，**以原生 Playwright（`playwright.async_api`）为第一公民**，将 Camoufox 彻底降级为底层的单一适配器，全面发挥 Playwright 官方原生 Locator、自动等待和原生多租户 Context 的工程能力。

---

## 2. 目标、非目标与反目标 (Goals, Non-goals, Anti-goals)

### 目标 (Goals)
1. **全面 Playwright 原生化**：
   - 交互操作（点击、输入、下拉选择、悬停、聚焦/失焦、拖拽、滚动）100% 切换为 Playwright 原生 `page.locator(f'[data-astr-ref="{ref}"]').*` 方法调用。
   - 充分利用 Playwright 内置的可见性检测、滚动到可视区、自动等待与受信任事件触发。
2. **纯粹的适配器解耦**：
   - `adapts/base.py` 定义通用的 `BrowserAdapterBase`，其契约仅交付 Playwright 标准 `Browser` 实例与 `create_context()`。
   - `CamoufoxAdapter` 作为目前默认的浏览器内核实现，仅在适配器内部使用 `camoufox.async_api.AsyncCamoufox`，对外暴露标准的 Playwright `Browser`。
3. **标准 Playwright 多租户隔离**：
   - 全局单个 `Browser` 进程（常驻/懒加载），利用 Playwright 原生 `browser.new_context(storage_state=...)` 实现会话/个人级严格隔离（Cookie、Cache、Pages 独立），支持 `context.storage_state()` 导入导出。
4. **强类型与官方日志规范**：
   - 全模块引入 `from playwright.async_api import Page, BrowserContext, Browser, Locator` 静态类型注解。
   - 全模块规范使用 `from astrbot.api import logger`（平滑兼容本地独立测试环境）。
5. **硬性端到端验证门禁**：
   - 重构后的新代码必须通过 `tests/e2e/test_real_browser.py` 在本地真实 Camoufox 无头浏览器中的全链路检验。

### 非目标 (Non-goals)
- 本次重构不更换 WebUI 审计前端（`views/audit/`）及其后端 Web API 契约（`api/audit_api.py`）。
- 暂不接入原生 Chromium/WebKit（保留适配器接口扩展性，当前阶段专心打通 Camoufox）。

### 反目标 (Anti-goals)
- **严禁裸 JS 点击/输入**：除 `PageExtractor` 读取 DOM 骨架需要遍历 DOM 外，严禁在交互操作中使用 `document.querySelector().click()` 或手动派发 `Event('input')`。
- **严禁泄漏 Camoufox 专有对象**：除 `adapts/camoufox_adapter.py` 外，任何 `core/` 和 `tools/` 模块中严禁出现 `camoufox` 相关 import。
- **严禁引入脆弱的私有属性**：严禁导入 `playwright._impl` 等内部模块。

---

## 3. 详细架构设计 (Detailed Architecture)

### 3.1 模块分层与依赖关系

```
[AstrBot Runtime / FunctionTool]
            │
            ▼
[tools/tools.py (PwPageTool, PwInteractTool, PwMediaTool)]
            │
            ▼
[tools/handlers/ (PageHandler, InteractHandler, MediaHandler)]
    (完全基于 playwright.async_api: Page, Locator)
            │
            ▼
[core/ (ContextManager, SecurityManager, PageExtractor, AuditLogger)]
    (ManagedContext 维护原生 BrowserContext 与 Page 映射)
            │
            ▼
[adapts/ (BrowserAdapterBase, CamoufoxAdapter)]
    (启动/维护 Playwright Browser 进程，交付 BrowserContext)
```

---

### 3.2 适配器层 (`adapts/`)

#### 1. `adapts/base.py`
```python
from abc import ABC, abstractmethod
from playwright.async_api import Browser, BrowserContext

class BrowserAdapterBase(ABC):
    @abstractmethod
    async def start(self) -> None:
        """启动底层浏览器进程并初始化 Playwright Browser 实例。"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """安全关闭所有上下文与底层浏览器进程。"""
        pass

    @abstractmethod
    async def create_context(self, storage_state_path: str | None = None) -> BrowserContext:
        """创建全新隔离的 Playwright BrowserContext。"""
        pass

    @property
    @abstractmethod
    def browser(self) -> Browser | None:
        """获取当前活跃的 Playwright Browser 实例。"""
        pass
```

#### 2. `adapts/camoufox_adapter.py`
- 仅在此模块动态导入 `from camoufox.async_api import AsyncCamoufox`。
- `start()`：创建并进入 `AsyncCamoufox(headless=..., geoip=...)`，获取 Playwright `Browser` 实例。
- `create_context()`：调用 `self._browser.new_context(storage_state=...)`，返回原生 `BrowserContext`。
- `stop()`：调用 `__aexit__` 退出并回收资源。

---

### 3.3 核心服务层 (`core/`)

#### 1. `core/context_manager.py`
- 定义数据结构 `ManagedContext`：
  ```python
  @dataclass
  class ManagedContext:
      session_id: str
      owner_id: str
      browser_context: BrowserContext  # 原生 Playwright BrowserContext
      current_page: Page              # 原生 Playwright Page
      allowed_users: set[str] = field(default_factory=set)
      last_active_time: float = field(default_factory=time.time)
      ref_map: dict[int, dict] = field(default_factory=dict)
      dialog_action: dict | None = None
      last_dialog_message: str | None = None
  ```
- `resolve_context(session_id, sender_id) -> tuple[ManagedContext | None, str]`:
  - 判定个人模式（`(session_id, owner_id)`）与会话模式（`session_id`）；
  - 若已存在且未超时，直接复用；
  - 若不存在，调用 `adapter.create_context(storage_state_path)`，创建原生上下文及首个页面 `await browser_context.new_page()`，并挂载基础安全路由与弹窗监听；
  - 定时轮询清理空闲超时上下文（调用 `await managed_ctx.browser_context.close()` 释放资源）。

#### 2. `core/page_extractor.py`
- 执行单次 JS 评估（`get_js_extractor_script()`）：
  - 遍历当前可视与可交互 DOM 节点（`button`, `input`, `select`, `a`, `textarea` 等）；
  - 自动向元素打上属性：`el.setAttribute('data-astr-ref', refId)`；
  - 提取语义化骨架信息：`tag`, `type`, `name`, `text`, `placeholder`, `value`, `href` 等；
  - 提取页面可见文本段落；
- `extract_snapshot(...)`：构建低 Token、高清晰度的精炼文本摘要给大模型，同时维护 `ref_map[ref_id] = el_info`。

#### 3. `core/security_manager.py`
- 负责 URL 白名单（支持通配符 `*.example.com`）、管理员放行规则（Admin Bypass）及工具动作白名单；
- 配合 Playwright 页面事件（`page.on("framenavigated")` / 导航拦截），拦截非法跳转。

#### 4. `core/audit_logger.py`
- 采用 SQLite 异步记录完整调用链（时间戳、会话、发送者、工具名、目标 URL、入参 JSON、结果摘要、是否报错、耗时），支持 Web API 查询与统计。

---

### 3.4 处理器层 (`tools/handlers/`)

全面重构为**基于 Playwright 原生 Locator 体系**：

#### 1. `tools/handlers/interact_handler.py`
- **点击 (`click`)**：
  ```python
  locator = page.locator(f'[data-astr-ref="{ref}"]')
  await locator.click(timeout=timeout_ms)
  ```
- **表单填写 (`fill_form`)**：
  ```python
  locator = page.locator(f'[data-astr-ref="{ref}"]')
  await locator.fill(text, timeout=timeout_ms)
  ```
  （原生 `fill` 会自动先聚焦、清空输入框，再模拟真实键盘输入，完美触发 React/Vue 的受控状态同步更新）
- **下拉选择 (`select_option`)**：
  ```python
  locator = page.locator(f'[data-astr-ref="{ref}"]')
  await locator.select_option(value=value, timeout=timeout_ms)
  ```
- **悬停 (`hover`)**：
  ```python
  locator = page.locator(f'[data-astr-ref="{ref}"]')
  await locator.hover(timeout=timeout_ms)
  ```
- **元素拖拽 (`drag`)**：
  ```python
  source = page.locator(f'[data-astr-ref="{ref}"]')
  target = page.locator(f'[data-astr-ref="{target_ref}"]')
  await source.drag_to(target, timeout=timeout_ms)
  ```
- **聚焦 / 失焦 (`focus` / `blur`)**：
  ```python
  locator = page.locator(f'[data-astr-ref="{ref}"]')
  await locator.focus(timeout=timeout_ms)
  # blur
  await locator.evaluate("el => el.blur()")
  ```
- **按键 (`press_key`)**：
  ```python
  await page.keyboard.press(key)
  ```
- **页面滚动 (`scroll`)**：
  ```python
  delta = amount if direction == "down" else -amount
  await page.mouse.wheel(0, delta)
  ```

#### 2. `tools/handlers/page_handler.py`
- `open_url`：`await page.goto(url, wait_until="domcontentloaded", timeout=30000)`，随后调用 `page_extractor` 提取首屏快照；
- `read_page`：支持分页返回页面骨架，支持动态翻页；
- `search_page`：基于当前 DOM 提取结果快速检索关键词匹配项；
- `switch_tab`：Playwright 原生多标签页切换：`ctx.current_page = ctx.browser_context.pages[tab_index - 1]`；
- `handle_dialog`：原生 `page.on("dialog", on_dialog)` 预设应答策略（`dialog.accept(prompt_text=...)` / `dialog.dismiss()`）；
- `close_browser`：主动释放当前用户的 `BrowserContext`（`await ctx.browser_context.close()`）。

#### 3. `tools/handlers/media_handler.py`
- 视口截图：`await page.screenshot(full_page=False, type="jpeg", quality=80)`；
- 长截图与熔断：`await page.screenshot(full_page=True)`，若超出限制或高度过大则自适应降级为视口截图；
- 文件下载：使用 Playwright 原生事件：
  ```python
  async with page.expect_download(timeout=timeout_ms) as download_info:
      # 触发下载的动作
  download = await download_info.value
  await download.save_as(target_path)
  ```

---

### 3.5 门面分发层 (`tools/tools.py`)

- 暴露给 AstrBot 的三大标准 `FunctionTool[AstrAgentContext]`：
  1. `pw_page`: 管理页面打开、快照阅读、搜索、标签页切换、弹窗预设与关闭；
  2. `pw_interact`: 管理点击、表单填写、下拉选择、悬停、聚焦/失焦、拖拽、按键与滚动；
  3. `pw_media`: 管理视口截图、整页长截图与文件下载。
- 采用字典分发 `_actions`，移除冗长 `if-elif`；
- 所有动作由 `_execute_with_timeout` 守护，确保单次调用超时强制终止并保全 Traceback。

---

## 4. 依赖项与测试验证规范

### 4.1 依赖项清单 (`requirements.txt`)
```text
camoufox[geoip]
playwright
pyyaml
```

### 4.2 验证门禁
1. **单元测试集 (`tests/`)**：
   - 包含适配器基础测试、上下文管理隔离测试、安全白名单测试、提取器测试、Handlers 原生 Mock 测试与门面工具测试。
2. **端到端集成测试集 (`tests/e2e/test_real_browser.py`)**：
   - 本地启动轻量级 `LocalTestServer`；
   - 真实拉起无头 Camoufox 驱动，执行打开页面、元素读取、输入、点击（验证 DOM 内容变化）、下拉选取、原生弹窗捕捉、标签页切换（`target="_blank"` 并在 `pages` 间切换）、整页/视口截图、安全释放全生命周期；
   - **硬性约束**：全部测试必须在本地 Windows 当前环境 100% 绿灯通过，无控制台异常与残留僵尸进程。
