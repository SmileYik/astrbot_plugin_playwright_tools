# 浏览器上下文生命周期完整性、进程空闲回收与审计日志体系实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐浏览器上下文在主动释放、超时回收、强杀与插件重载/卸载四大环节的资源释放与审计日志闭环，实现底层浏览器进程的空闲自动回收与崩溃自愈，彻底杜绝孤儿进程泄漏。

**Architecture:** 
1. 在 `BrowserAdapterBase` 引入状态感知 (`is_running`) 与断开事件回调机制 (`set_disconnect_callback`)，底层浏览器意外崩溃时通知上层注销存量僵尸上下文并自愈；
2. 由 `ContextManager` 状态机统管活跃上下文与无上下文空闲时间戳 (`last_zero_context_time`)，在周期巡检中基于配置 `browser_idle_timeout_minutes` 自动停止底层浏览器 OS 进程；
3. 四大生命周期环节全量补齐 `logger.info` 与写入 `context_lifecycle_logs`（补充存活时长、标签页数量、终态 URL 等细节）；
4. 插件 `terminate()` 使用 `asyncio.gather` 与 5 秒并发总超时熔断批量清理存量会话并停止适配器，成对维护 `atexit` 钩子避免孤儿进程累积。

**Tech Stack:** Python 3.10+, Playwright, Camoufox, SQLite3, asyncio, AstrBot Star Plugin Framework

**Spec:** `docs/superpowers/specs/2026-11-22-browser-lifecycle-and-process-reclamation-design.md`

## Global Constraints

- 日志输出严格使用 `from astrbot.api import logger`，严禁使用外部日志库（禁止 `import logging`）。
- 文档与日志严禁使用绝对化词汇（如“彻底解决”、“根治”等），实事求是。
- 严禁在存在活跃上下文时提前终止底层浏览器进程。
- 单测必须 100% 通过（`python -m unittest discover tests`），不使用真实网络与真实 E2E 浏览器测试。

## Review Focus

1. 浏览器意外断开（`browser.on("disconnected")`）触发时，存量上下文必须全部标记失效并写入审计，清空缓存后下次请求能重新拉起新实例。
2. 上下文全部释放后，空闲超过 `browser_idle_timeout_minutes` 必须自动停止底层适配器并清理时间戳；若有新请求则无感启动。
3. `close_all_contexts(reason="terminate")` 必须在 5 秒并发总超时内完成，不能因单个页面阻塞而拖垮 AstrBot 插件重载。
4. 插件重载时，`__init__` 注册的 `atexit` 钩子必须在 `terminate()` 中显式 `unregister`，防止回调函数随重载多次累加。
5. 所有上下文关闭路径必须清理对应的 `_creation_locks`，杜绝字典无限内存泄漏。

---

### Task 1: 配置项扩展与适配器断开感知增强 (`_conf_schema.json`, `metadata.yaml`, `adapts/`)

**Files:**
- Modify: `_conf_schema.json`
- Modify: `metadata.yaml`
- Modify: `adapts/base.py`
- Modify: `adapts/playwright_adapter.py`
- Modify: `adapts/camoufox_adapter.py`
- Test: `tests/test_adapter_factory.py`
- Test: `tests/test_conf_schema.py`

- [x] **Step 1: 编写适配器断开感知与配置项单测**
  - 在 `tests/test_conf_schema.py` 中增加对 `runtime.browser_idle_timeout_minutes` 默认值（5）、类型（integer）及取值范围（0~1440）的断言校验。
  - 在 `tests/test_adapter_factory.py` 中增加对 `is_running` 属性、`set_disconnect_callback` 注册与底层 `disconnected` 事件触发时回调执行的测试用例。
- [x] **Step 2: 运行测试验证失败**
  - 执行 `python -m unittest tests/test_conf_schema.py tests/test_adapter_factory.py`，确认测试因缺少对应配置与属性而失败。
- [x] **Step 3: 扩展配置 Schema 与 metadata**
  - 在 `_conf_schema.json` 的 `properties.runtime.properties` 中添加 `browser_idle_timeout_minutes` 配置项。
  - 在 `metadata.yaml` 中补充对应配置声明。
- [x] **Step 4: 改造浏览器适配器基类与实现类**
  - 在 `adapts/base.py` 中添加 `is_running` 属性与 `set_disconnect_callback(cb)` 方法。
  - 在 `adapts/playwright_adapter.py` 与 `adapts/camoufox_adapter.py` 中实现 `_disconnect_callbacks` 列表、挂载 `browser.on("disconnected", ...)` 并在断开时执行回调且将 `self._browser = None`。
  - 在 `create_context()` 中通过 `if not self.is_running: await self.start()` 支持崩溃透明重启。
- [x] **Step 5: 运行单测验证通过**
  - 执行 `python -m unittest tests/test_conf_schema.py tests/test_adapter_factory.py`，确保测试通过。
- [x] **Step 6: 提交 Task 1 变更**
  - 配置项与适配器增强代码已就绪并通过完整单测。

---

### Task 2: 上下文管理器状态机、自愈与并发超时关闭 (`core/context_manager.py`)

**Files:**
- Modify: `core/context_manager.py`
- Test: `tests/test_context_manager.py`

- [x] **Step 1: 编写上下文管理器状态机与自愈回收单测**
  - 在 `tests/test_context_manager.py` 中添加测试：
    1. 测试收到底层断开通知 `_on_browser_disconnected` 时注销所有存量上下文并写入 `terminate` (reason=browser_crash) 审计；
    2. 测试 `close_all_contexts(reason="terminate")` 并发关闭与 5.0 秒全局超时熔断；
    3. 测试 `check_and_cleanup_idle_browser()` 在有/无上下文及超时前后的状态迁移；
    4. 测试 `close_user_context`、`cleanup_idle_contexts`、`force_kill_context`、`release_external_context` 均会清理 `_creation_locks`，丰富 `details` 载荷并打出 `logger.info`。
- [x] **Step 2: 运行测试验证失败**
  - 执行 `python -m unittest tests/test_context_manager.py`，确认测试按预期失败。
- [x] **Step 3: 实现上下文管理器生命周期增强**
  - 在 `ContextManager.__init__` 中新增 `browser_idle_timeout_minutes` 参数，维护 `self.last_zero_context_time`，并向 `adapter` 注册 `_on_browser_disconnected`。
  - 实现 `_on_browser_disconnected` 方法：记录警告日志，批量记录 `terminate` 审计并清空 `contexts`、`_creation_locks`、`user_active_pointer`。
  - 实现 `check_and_cleanup_idle_browser()` 方法：当上下文归零超过阈值且适配器处于运行态时，带 5 秒超时执行 `await adapter.stop()`。
  - 实现 `close_all_contexts(reason="terminate")` 方法：使用 `asyncio.gather` 并发关闭所有上下文，并在外层施加 5.0 秒超时熔断；批量记录 `terminate` 审计。
  - 在 `close_user_context`、`cleanup_idle_contexts`、`force_kill_context`、`release_external_context` 中：
    - 采集存活时长 `duration_seconds`、标签页数 `tab_count`、终态 `final_url` 送入审计 `details`；
    - 执行 `self._creation_locks.pop(key, None)`；
    - 输出规范的 `logger.info`；
    - 在上下文归零时更新 `self.last_zero_context_time = time.time()`。
- [x] **Step 4: 运行单测验证通过**
  - 执行 `python -m unittest tests/test_context_manager.py`，确保全部单测通过。
- [x] **Step 5: 提交 Task 2 变更**
  - 上下文管理器核心状态机与并发自愈机制已完成并验证。

---

### Task 3: 审计日志兼容与多维生命周期记录检索 (`core/audit_logger.py`)

**Files:**
- Modify: `core/audit_logger.py`
- Test: `tests/test_audit_logger.py`

- [x] **Step 1: 编写生命周期审计记录扩充单测**
  - 在 `tests/test_audit_logger.py` 中新增用例，测试向 `context_lifecycle_logs` 录入 `event_type="terminate"` 记录，并校验 `details` 包含 `duration_seconds`、`reason`、`final_url` 等结构化 JSON。
  - 测试通过 `query_lifecycle_logs(event_type="terminate")` 能精确查出对应终止审计。
- [x] **Step 2: 运行测试验证**
  - 执行 `python -m unittest tests/test_audit_logger.py`，观察行为并确认待优化点。
- [x] **Step 3: 完善审计日志记录器**
  - 确保 `AuditLogger.log_lifecycle` 能完整且安全序列化包含多维字典的 `details`。
  - 完善 `query_lifecycle_logs` 的过滤条件与容错。
- [x] **Step 4: 运行单测验证通过**
  - 执行 `python -m unittest tests/test_audit_logger.py`，确保全部单测通过。
- [x] **Step 5: 提交 Task 3 变更**
  - 生命周期审计日志扩充与 terminate 搜索支持已完成并验证。

---

### Task 4: 主插件生命周期闭环、周期巡检优化与 atexit 防护 (`main.py`)

**Files:**
- Modify: `main.py`
- Test: `tests/test_plugin_main.py`

- [x] **Step 1: 编写主插件生命周期与定时回收测试**
  - 在 `tests/test_plugin_main.py` 中添加测试：
    1. 测试插件初始化时正确解析 `runtime.browser_idle_timeout_minutes` 并传入 `ContextManager`；
    2. 测试 `_periodic_cleanup_loop` 会调用 `check_and_cleanup_idle_browser()`；
    3. 测试 `terminate()` 调用 `close_all_contexts("terminate")`、带 5 秒超时调用 `adapter.stop()`，并注销 `atexit` 钩子。
- [x] **Step 2: 运行测试验证失败**
  - 执行 `python -m unittest tests/test_plugin_main.py`，确认测试因缺少上述逻辑而失败。
- [x] **Step 3: 改造主插件入口**
  - 读取配置 `browser_idle_timeout_minutes`，默认 5 分钟，传递给 `ContextManager`。
  - 在 `__init__` 中注册 `atexit.register(self._atexit_cleanup)`，定义 `_atexit_cleanup` 安全兜底。
  - 优化 `_periodic_cleanup_loop`：休眠间隔调整为 30 秒，每次循环调用 `cleanup_idle_contexts()` 和 `check_and_cleanup_idle_browser()`，审计日志过期清理按天/小时节流调用。
  - 改造 `terminate()`：先通过 `atexit.unregister(self._atexit_cleanup)` 注销钩子；再调用 `await self.context_manager.close_all_contexts(reason="terminate")`；最后在 5.0 秒超时熔断下执行 `await self.adapter.stop()`。
- [x] **Step 4: 运行单测验证通过**
  - 执行 `python -m unittest tests/test_plugin_main.py`，确保全部测试通过。
- [x] **Step 5: 提交 Task 4 变更**
  - 主插件入口生命周期闭环、定时进程空闲回收与 atexit 防护已就绪并通过验证。

---

### Task 5: 全量测试回归与技术文档同步 (`README.md`, `docs/`, `CHANGELOG.md`)

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [x] **Step 1: 运行全量单元测试套件**
  - 运行 `python -m unittest discover tests`，确保全工程所有单测（原有 209 个及新增测试）100% 通过。
- [x] **Step 2: 同步更新项目架构文档 (`docs/ARCHITECTURE.md`)**
  - 补充底层浏览器进程空闲回收时序、崩溃断开自愈时序与四大环节生命周期审计/日志图表。
- [x] **Step 3: 同步更新使用说明 (`README.md`)**
  - 在运行与配置章节补充 `browser_idle_timeout_minutes` 配置说明与空闲回收行为。
- [x] **Step 4: 更新变更日志 (`CHANGELOG.md`)**
  - 记录新增进程空闲回收、崩溃感知自愈、全环节生命周期审计与运行日志增强项。
- [x] **Step 5: 提交 Task 5 变更**
  - 确认所有文档与最终验证状态均已就绪。
