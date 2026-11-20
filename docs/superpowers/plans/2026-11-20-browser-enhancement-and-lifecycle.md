# 浏览器增强、成熟正文提炼与会话生命周期管理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 升级网页自动化工具插件，提供基于 Mozilla Readability 启发式算法的成熟正文与高价值控件提炼，建立 SQLite 独立生命周期表与 Web 端会话生命周期管理页面（支持多标签页查看、手动截图与强制销毁），实现截图二进制直出与切页防抖 Bug 修复，支持多适配器体系（Camoufox + Playwright 原生驱动）以及扩展管理指令。

**Architecture:** 
1. 提取层：在浏览器端注入成熟的 Readability DOM 启发式密度评分算法，精准提炼文章/帖子主内容容器（支持 `div`+`<br>` 帖子形式），剔除噪声区域，并在 Python 端严格归一化换行排版；
2. 适配层：抽象 `BrowserAdapterBase`，构建 `AdapterFactory` 动态支持 `camoufox` 与原生 `playwright` 内核，透传窗口尺寸、UserAgent、无头模式与 GeoIP；
3. 数据与生命周期层：SQLite 新增 `context_lifecycle_logs`，`ContextManager` 深度埋点生命周期事件；Web 端在 `metadata.yaml` 注册并实现 `lifecycle` 管理视图；
4. 接口与指令层：图片接口直接直出二进制流；`main.py` 扩展 `/browser list`、`/browser list-all` 与 `/browser kill` 指令。

**Tech Stack:** Python 3.10+, Playwright, Camoufox, SQLite3, FastAPI / Starlette, React 18, TypeScript, Vite.

**Spec:** [`docs/superpowers/specs/2026-11-20-browser-enhancement-and-lifecycle-design.md`](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-20-browser-enhancement-and-lifecycle-design.md)

## Global Constraints

- 存储引擎：SQLite，数据库路径由配置项 `audit_db_path` 指定，默认 `data/audit.db`。
- 平台兼容：跨 Windows 与 Linux 运行，文件路径需做统一正斜杠或 `Path` 处理。
- 无数据库迁移负担：用户无生产历史存量数据，表结构若不存在则自动新建。
- 图片流：截图预览接口必须直接返回二进制流（带正确 `Content-Type`），不得使用 Base64。
- 被动清理：以天为单位（`file_retention_days`），在每次调用截图或下载工具时被动扫描清理超期文件。

## Review Focus

1. 贴吧/论坛类 HTML 包含大量嵌套 `div`、`<br>` 以及侧边栏推广，正文提炼不得丢失帖子文本，亦不得将侧边栏误判为主正文。
2. 连续空行排版：段落间最多允许连续两个换行 `\n\n`，列表项之间必须保持紧凑单换行 `\n`，严禁出现 3 个及以上连续空行。
3. 截图直出接口 `GET /audit/screenshot?path=...` 遇到目录越界（Path Traversal）攻击时必须严格阻断并返回 403。
4. 前端切页时，`TopAppBar` 的防抖逻辑不得再次触发 `setPage(1)` 导致用户被拉回第 1 页。
5. 管理员指令 `/browser list-all` 与 `/browser kill` 必须对普通用户调用执行严格权限校验拦截。

---

### Task 1: SQLite 生命周期表与 AuditLogger 扩展

**Files:**
- Modify: `core/audit_logger.py:20-60, 140-200`
- Test: `tests/test_audit_logger.py`

**Interfaces:**
- Consumes: `AuditLogger(db_path, max_output_chars)`
- Produces: 
  - `AuditLogger.log_lifecycle(session_id, context_key, owner_id, event_type, operator_id, session_name='', details=None) -> None`
  - `AuditLogger.query_lifecycle_logs(page=1, page_size=20, session_id='', event_type='', keyword='') -> tuple[list[dict], int]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit_logger.py
import pytest
import os
from core.audit_logger import AuditLogger

@pytest.mark.asyncio
async def test_lifecycle_logs_crud(tmp_path):
    db_file = str(tmp_path / "test_lifecycle.db")
    logger = AuditLogger(db_path=db_file)
    
    # 记录生命周期事件
    await logger.log_lifecycle(
        session_id="sess_100",
        context_key="sess_100:user_1",
        owner_id="user_1",
        event_type="create",
        operator_id="user_1",
        session_name="测试群",
        details={"adapter": "camoufox", "tab_count": 1}
    )
    
    items, total = await logger.query_lifecycle_logs(page=1, page_size=10, event_type="create")
    assert total == 1
    assert items[0]["event_type"] == "create"
    assert items[0]["owner_id"] == "user_1"
    assert "camoufox" in items[0]["details"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_audit_logger.py::test_lifecycle_logs_crud -v`
Expected: FAIL with `AttributeError: 'AuditLogger' object has no attribute 'log_lifecycle'`

- [ ] **Step 3: Implement `context_lifecycle_logs` table and methods in `core/audit_logger.py`**

在 `_ensure_db()` 中创建 `context_lifecycle_logs` 表，包含字段 `id`, `timestamp`, `event_type`, `session_id`, `session_name`, `context_key`, `owner_id`, `operator_id`, `details`。
实现 `log_lifecycle` 与 `query_lifecycle_logs` 方法。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_audit_logger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/audit_logger.py tests/test_audit_logger.py
git commit -m "feat(audit): add context_lifecycle_logs table and query methods"
```

---

### Task 2: 配置 Schema 扩展 (`_conf_schema.json`)

**Files:**
- Modify: `_conf_schema.json`
- Test: `tests/test_conf_schema.py`

**Interfaces:**
- Produces: JSON schema with browser adapter, window size, user agent, screenshot format, paths and retention days.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conf_schema.py
import json
import pytest

def test_conf_schema_contains_new_fields():
    with open("_conf_schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    
    expected_fields = [
        "browser_adapter",
        "playwright_browser_type",
        "browser_window_width",
        "browser_window_height",
        "browser_user_agent",
        "browser_headless",
        "camoufox_geoip",
        "screenshot_format",
        "screenshot_quality",
        "download_save_path",
        "screenshot_save_path",
        "file_retention_days",
    ]
    for field in expected_fields:
        assert field in schema, f"Missing field {field} in _conf_schema.json"
        assert "type" in schema[field]
        assert "default" in schema[field]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_conf_schema.py -v`
Expected: FAIL with `Missing field browser_adapter in _conf_schema.json`

- [ ] **Step 3: Update `_conf_schema.json` with all new configuration fields**

在 `_conf_schema.json` 中配置所有新增参数及其默认值与中文说明。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_conf_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json tests/test_conf_schema.py
git commit -m "feat(config): expand _conf_schema.json with adapter, media and retention fields"
```

---

### Task 3: 适配器架构与工厂实现 (`adapts/`)

**Files:**
- Modify: `adapts/base.py`, `adapts/camoufox_adapter.py`, `adapts/__init__.py`
- Create: `adapts/playwright_adapter.py`, `adapts/factory.py`
- Test: `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: `BrowserAdapterBase`
- Produces:
  - `PlaywrightAdapter(browser_type='chromium', headless=True, user_agent='', window_width=1280, window_height=720)`
  - `CamoufoxAdapter(headless=True, geoip=False, user_agent='', window_width=1280, window_height=720)`
  - `AdapterFactory.create(config: dict) -> BrowserAdapterBase`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adapter_factory.py
import pytest
from unittest.mock import patch, MagicMock
from adapts.factory import AdapterFactory
from adapts.camoufox_adapter import CamoufoxAdapter
from adapts.playwright_adapter import PlaywrightAdapter

def test_adapter_factory_create_camoufox():
    config = {
        "browser_adapter": "camoufox",
        "browser_headless": True,
        "camoufox_geoip": True,
        "browser_window_width": 1920,
        "browser_window_height": 1080,
    }
    adapter = AdapterFactory.create(config)
    assert isinstance(adapter, CamoufoxAdapter)
    assert adapter.headless is True
    assert adapter.geoip is True
    assert adapter.window_width == 1920
    assert adapter.window_height == 1080

def test_adapter_factory_create_playwright():
    config = {
        "browser_adapter": "playwright",
        "playwright_browser_type": "firefox",
        "browser_headless": False,
        "browser_user_agent": "CustomUA/1.0",
    }
    adapter = AdapterFactory.create(config)
    assert isinstance(adapter, PlaywrightAdapter)
    assert adapter.browser_type == "firefox"
    assert adapter.headless is False
    assert adapter.user_agent == "CustomUA/1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adapter_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'adapts.playwright_adapter'`

- [ ] **Step 3: Implement `PlaywrightAdapter`, update `CamoufoxAdapter`, and implement `AdapterFactory`**

- `adapts/playwright_adapter.py`: 使用 `async_playwright`，在 `start()` 时启动 `getattr(playwright, self.browser_type).launch(headless=self.headless)`，并在 `create_context` 中应用 `viewport={'width': self.window_width, 'height': self.window_height}` 与 `user_agent`。
- `adapts/camoufox_adapter.py`: 在 `create_context` 中应用视口宽高与 `user_agent`。
- `adapts/factory.py`: 实现 `AdapterFactory.create(config)` 依据 `browser_adapter` 参数构建实例。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adapter_factory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add adapts/ tests/test_adapter_factory.py
git commit -m "feat(adapter): implement PlaywrightAdapter and AdapterFactory"
```

---

### Task 4: 成熟正文与高价值元素提炼算法升级 (`core/page_extractor.py`)

**Files:**
- Modify: `core/page_extractor.py`
- Test: `tests/test_page_extractor.py`

**Interfaces:**
- Consumes: `raw_elements`, `markdown_text`, `page_title`, `url`
- Produces: `PageExtractor.extract_snapshot(...)`, `PageExtractor.get_js_extractor_script()`, clean formatted Markdown without excess newlines.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_page_extractor.py
import pytest
from core.page_extractor import PageExtractor

def test_page_extractor_normalizes_excessive_newlines():
    extractor = PageExtractor()
    raw_md = "# 标题\n\n\n\n第一段\n\n\n\n第二段\n\n- 列表1\n\n- 列表2"
    snapshot, ref_map = extractor.extract_snapshot("测试", "http://example.com", [], raw_md)
    # 连续空行应折叠为最多双换行，且无 3 个以上连续 \n
    assert "\n\n\n" not in snapshot["markdown_text"]
    assert "第一段\n\n第二段" in snapshot["markdown_text"]

def test_page_extractor_filters_noisy_elements():
    extractor = PageExtractor()
    raw_elements = [
        {"tag": "a", "text": "登录", "role": "link"},
        {"tag": "a", "text": "_mc_btn_txt", "role": "link"},
        {"tag": "a", "text": "_mc_btn_txt", "role": "link"}, # 重复的作者名链接
        {"tag": "button", "text": "回复帖子", "role": "button"},
    ]
    snapshot, ref_map = extractor.extract_snapshot("测试", "http://example.com", raw_elements, "正文")
    # 重复噪音应该在单行化展示中过滤或去重
    assert "回复帖子" in snapshot["elements_text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_page_extractor.py -v`
Expected: FAIL on `assert "\n\n\n" not in snapshot["markdown_text"]`

- [ ] **Step 3: Upgrade `PageExtractor` implementation**

1. 在 `core/page_extractor.py` 中更新 `get_js_extractor_script()`：
   - 启发式评分计算主要内容容器（优先支持论坛正文 `.d_post_content`, `div` 容器与 `<br>` 解析，排除 `.sidebar, .login-box, nav, footer, header`）；
   - 提取列表时紧凑连接；
2. 在 `extract_snapshot` 中加入正则规整：
   - `md_clean = re.sub(r'\n{3,}', '\n\n', md_clean).strip()`；
   - 规整列表单换行与元素去重。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_page_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/page_extractor.py tests/test_page_extractor.py
git commit -m "feat(extractor): implement readability density scoring and newline normalization"
```

---

### Task 5: 媒体管理升级：JPG/PNG 格式、质量与被动清理 (`tools/handlers/media_handler.py`)

**Files:**
- Modify: `tools/handlers/media_handler.py`
- Test: `tests/test_media_handler.py`

**Interfaces:**
- Consumes: `ContextManager`, `SecurityManager`, `AuditLogger`
- Produces: `MediaHandler(..., screenshot_format='png', screenshot_quality=80, file_retention_days=7, screenshot_dir=..., download_dir=...)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_media_handler.py
import pytest
import time
from pathlib import Path
from tools.handlers.media_handler import MediaHandler
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_passive_cleanup_removes_expired_files(tmp_path):
    download_dir = str(tmp_path / "downloads")
    screenshot_dir = str(tmp_path / "screenshots")
    Path(download_dir).mkdir()
    Path(screenshot_dir).mkdir()
    
    # 创建一个 10 天前的旧文件和一个今天的新文件
    old_file = Path(download_dir) / "old.zip"
    old_file.write_text("old")
    ten_days_ago = time.time() - (10 * 86400)
    import os
    os.utime(old_file, (ten_days_ago, ten_days_ago))
    
    new_file = Path(download_dir) / "new.zip"
    new_file.write_text("new")
    
    handler = MediaHandler(
        context_mgr=MagicMock(),
        security_mgr=MagicMock(),
        audit_logger=MagicMock(),
        download_dir=download_dir,
        screenshot_dir=screenshot_dir,
        file_retention_days=7
    )
    
    cleaned = await handler.cleanup_expired_files()
    assert not old_file.exists()
    assert new_file.exists()
    assert cleaned >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_media_handler.py -v`
Expected: FAIL with `AttributeError: 'MediaHandler' object has no attribute 'cleanup_expired_files'`

- [ ] **Step 3: Implement screenshot format/quality and passive cleanup in `MediaHandler`**

- 构造函数接收 `screenshot_format`, `screenshot_quality`, `screenshot_dir`, `file_retention_days`；
- 在 `screenshot_viewport` 与 `screenshot_full` 中传入 `type="jpeg" if self.screenshot_format in ("jpeg", "jpg") else "png"` 与 `quality` 参数；
- 实现 `cleanup_expired_files()` 扫描 `download_dir` 与 `screenshot_dir` 中 `mtime < now - retention_days * 86400` 的文件并删除；
- 在每次截图和下载入口被动调用 `cleanup_expired_files()`。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_media_handler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/handlers/media_handler.py tests/test_media_handler.py
git commit -m "feat(media): add format, quality options and passive file cleanup"
```

---

### Task 6: 会话生命周期追踪集成 (`core/context_manager.py`)

**Files:**
- Modify: `core/context_manager.py`
- Test: `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `AuditLogger.log_lifecycle`
- Produces:
  - `ContextManager.force_kill_context(context_key: str, operator_id: str) -> tuple[bool, str]`
  - `ContextManager.get_active_contexts_detail() -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context_manager.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.context_manager import ContextManager

@pytest.mark.asyncio
async def test_context_manager_records_lifecycle_and_details():
    mock_audit = MagicMock()
    mock_audit.log_lifecycle = AsyncMock()
    
    mgr = ContextManager(
        adapter=MagicMock(),
        security=MagicMock(),
        audit_logger=mock_audit
    )
    
    # 模拟新建上下文
    ctx = MagicMock()
    ctx.session_id = "sess_1"
    ctx.owner_id = "user_1"
    ctx.context_key = "sess_1:user_1"
    ctx.allowed_users = {"user_1"}
    ctx.browser_context.pages = [MagicMock(url="https://example.com", title=AsyncMock(return_value="Example"))]
    ctx.current_page = ctx.browser_context.pages[0]
    
    mgr.contexts["sess_1:user_1"] = ctx
    
    details = await mgr.get_active_contexts_detail()
    assert len(details) == 1
    assert details[0]["context_key"] == "sess_1:user_1"
    assert details[0]["tab_count"] == 1
    
    ok, msg = await mgr.force_kill_context("sess_1:user_1", operator_id="admin_user")
    assert ok is True
    assert "sess_1:user_1" not in mgr.contexts
    mock_audit.log_lifecycle.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_context_manager.py -v`
Expected: FAIL with `AttributeError: 'ContextManager' object has no attribute 'get_active_contexts_detail'`

- [ ] **Step 3: Implement lifecycle hooks, `get_active_contexts_detail` and `force_kill_context`**

在 `ContextManager` 中加入生命周期埋点（创建、关闭、邀请加入、超时销毁），并实现查询详情与强制销毁方法。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_context_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/context_manager.py tests/test_context_manager.py
git commit -m "feat(context): integrate lifecycle logging, context inspection and force-kill"
```

---

### Task 7: Web API 升级：截图二进制直出与生命周期管理 API (`api/`)

**Files:**
- Modify: `api/audit_api.py`
- Create: `api/lifecycle_api.py`
- Test: `tests/test_audit_api.py`, `tests/test_lifecycle_api.py`

**Interfaces:**
- Produces:
  - `AuditApiHandler.api_audit_screenshot`: 直出二进制流 `Response(image_bytes, media_type=mime)`
  - `LifecycleApiHandler.register_routes(context, plugin_name)`
  - `LifecycleApiHandler.api_active_contexts`
  - `LifecycleApiHandler.api_lifecycle_logs`
  - `LifecycleApiHandler.api_manual_screenshot`
  - `LifecycleApiHandler.api_force_kill`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lifecycle_api.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from api.lifecycle_api import LifecycleApiHandler

@pytest.mark.asyncio
async def test_lifecycle_api_endpoints():
    mock_mgr = MagicMock()
    mock_mgr.get_active_contexts_detail = AsyncMock(return_value=[{"context_key": "k1", "tab_count": 2}])
    mock_audit = MagicMock()
    mock_audit.query_lifecycle_logs = AsyncMock(return_value=([], 0))
    
    handler = LifecycleApiHandler(context_mgr=mock_mgr, audit_logger=mock_audit)
    res = await handler.api_active_contexts()
    assert res["data"]["items"][0]["context_key"] == "k1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lifecycle_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.lifecycle_api'`

- [ ] **Step 3: Implement `LifecycleApiHandler` and binary stream in `AuditApiHandler.api_audit_screenshot`**

- `api/audit_api.py`: 读取目标图片直接返回 `starlette.responses.Response(content=f.read(), media_type=mime)` 或 `FileResponse`。
- `api/lifecycle_api.py`: 实现查询活跃上下文、分页查询生命周期历史、手动截图以及强行销毁。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lifecycle_api.py tests/test_audit_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/ tests/test_lifecycle_api.py tests/test_audit_api.py
git commit -m "feat(api): add LifecycleApiHandler and binary stream response for screenshot"
```

---

### Task 8: CLI 管理指令扩展与插件组装 (`main.py`)

**Files:**
- Modify: `main.py`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: `AdapterFactory`, `LifecycleApiHandler`, `ContextManager.get_active_contexts_detail`, `ContextManager.force_kill_context`
- Produces: Updated `/browser` command with `list`, `list-all`, `kill` subcommands.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plugin_main.py (新增指令测试)
import pytest
from unittest.mock import AsyncMock, MagicMock
from main import PlaywrightToolPlugin

@pytest.mark.asyncio
async def test_browser_cmd_list_and_kill():
    mock_ctx = MagicMock()
    plugin = PlaywrightToolPlugin(mock_ctx, config={})
    plugin.context_manager.get_active_contexts_detail = AsyncMock(return_value=[
        {"context_key": "sess_1:user_1", "session_id": "sess_1", "owner_id": "user_1", "allowed_users": ["user_1"], "tab_count": 1, "active_tab_url": "https://example.com"}
    ])
    
    event = MagicMock()
    event.session_id = "sess_1"
    event.get_sender_id.return_value = "user_1"
    event.is_admin.return_value = True
    event.plain_result = lambda text: text
    
    # 测试 /browser list
    results = [r async for r in plugin.browser_cmd(event, sub_cmd="list")]
    assert any("sess_1:user_1" in r for r in results)
    
    # 测试 /browser kill
    plugin.context_manager.force_kill_context = AsyncMock(return_value=(True, "已销毁"))
    results = [r async for r in plugin.browser_cmd(event, sub_cmd="kill", arg="sess_1:user_1")]
    assert any("已销毁" in r for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_main.py::test_browser_cmd_list_and_kill -v`
Expected: FAIL (sub_cmd list/kill 未处理)

- [ ] **Step 3: Wire `AdapterFactory`, `LifecycleApiHandler`, and implement `list`, `list-all`, `kill` subcommands in `main.py`**

在 `main.py` 中使用 `AdapterFactory` 初始化适配器；初始化并注册 `LifecycleApiHandler`；完善 `/browser list`、`/browser list-all`（管理员校验）、`/browser kill`。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plugin_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_plugin_main.py
git commit -m "feat(cli): add /browser list, list-all and kill subcommands and wire lifecycle api"
```

---

### Task 9: Web 前端双视图与交互升级 (`web-src/` & `metadata.yaml`)

**Files:**
- Modify: `metadata.yaml`
- Modify: `web-src/src/App.tsx`, `web-src/src/components/TopAppBar.tsx`, `web-src/src/components/SideDrawer.tsx`
- Create: `web-src/src/views/LifecycleView.tsx`, `web-src/src/components/Navbar.tsx`
- Modify: `web-src/vite.config.ts`

**Interfaces:**
- Produces: Built frontend outputs in `views/audit` and `views/lifecycle`.

- [ ] **Step 1: Update `metadata.yaml` to declare `lifecycle` view**

在 `metadata.yaml` 的 `views` 列表中添加 `name: lifecycle`, `title: 会话生命周期管理`。

- [ ] **Step 2: Fix debounce bug in `web-src/src/components/TopAppBar.tsx` & `App.tsx`**

- `TopAppBar.tsx`: 仅在 `searchInput !== keyword` 时调用 `onKeywordChange(searchInput)`；
- `App.tsx`: 使用 `useCallback` 包装 `onKeywordChange`，切页操作时不改变函数引用，防止重新触发重置页码。

- [ ] **Step 3: Update screenshot display in `SideDrawer.tsx`**

直接将 `screenshotUrl` 设置为 `/api/v1/plugins/extensions/astrbot_plugin_playwright_tools/audit/screenshot?path=${encodeURIComponent(path)}`，浏览器通过原生 Cookies 携带鉴权直接加载二进制图片流。

- [ ] **Step 4: Implement `LifecycleView.tsx` and Navigation**

- `LifecycleView`: 展示所有活跃会话卡片、各标签页列表、激活页指示；提供“手动截图”与“强制销毁”按钮；
- 页面顶部增加视图切换导航条（审计日志 / 会话生命周期）。

- [ ] **Step 5: Build frontend assets and verify bundle**

Run: `cd web-src && npm run build`
Expected: 构建成功，静态文件输出至 `views/audit`。

- [ ] **Step 6: Commit**

```bash
git add metadata.yaml web-src/ views/
git commit -m "feat(ui): add LifecycleView, fix pagination bounce-back, and stream binary screenshot"
```

---

### Task 10: 端到端集成验证与全量回归测试

**Files:**
- Test: All unit and integration test files under `tests/`

- [ ] **Step 1: Run full pytest test suite**

Run: `pytest tests/ -v`
Expected: 所有的测试全部通过（100% PASS）。

- [ ] **Step 2: Verify git status and clean working tree**

Run: `git status`
Expected: Working tree clean, all files staged or committed.

- [ ] **Step 3: Commit integration completion**

```bash
git commit --allow-empty -m "chore(release): complete browser tools enhancement and lifecycle management"
```
