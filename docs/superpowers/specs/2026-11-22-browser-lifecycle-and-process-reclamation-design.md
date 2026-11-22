# 浏览器上下文生命周期完整性、进程空闲回收与审计日志体系设计

## 1. 意图与背景 (Intent & Why)

当前 `astrbot_plugin_playwright_tools` 面向大模型与跨插件提供多租户浏览器会话管理能力。在日常长时间挂机运行与多插件协作场景中，经过对**主动释放**、**超时回收**、**强制退出/杀死**与**插件重载（卸载/禁用）**四个关键环节的系统审阅，暴露出以下稳定性与资源管理隐患：

1. **底层浏览器进程永久常驻与泄漏风险**：目前即使所有会话上下文（`BrowserContext`）均已通过用户指令、超时机制或 API 强杀释放，底层浏览器 OS 进程（Chromium/Camoufox）及 Playwright 驱动进程仍持续常驻内存，长时间无操作时造成显著内存资源浪费。
2. **崩溃失联无自愈机制**：若底层的浏览器 OS 进程由于内存超限（OOM）或宿主外部信号被意外终止，适配器未监听 `disconnected` 事件，内部仍保留旧的失效 `_browser` 句柄，导致后续会话创建持续抛出 `TargetClosedError`，陷入无法自愈的僵死状态。
3. **插件重载与退出缺乏超时熔断**：在 AstrBot 执行插件重载或终止时，`terminate()` 依次执行上下文关闭和适配器停止，但没有任何超时保护（`asyncio.wait_for`）。若遇到 CDP 挂起或页面假死，`terminate()` 将无限期挂起；AstrBot 超时报错后加载新插件，导致旧浏览器孤儿进程遗留，多次重载造成进程多重累积泄漏。同时缺乏 `atexit` 进程退出兜底与注销机制。
4. **内部辅助状态未伴随释放**：`ContextManager._creation_locks` 字典在上下文销毁后未被清理，随时间推移存在无界增长隐患；上下文关闭缺少超时熔断保护。
5. **审计与运行日志盲区**：
   - 插件终止/重载时，所有存量活跃上下文被静默关闭，在 `context_lifecycle_logs` 审计数据表中没有任何记录，管理员无法追溯会话生命周期终态；
   - 现有生命周期审计事件（`close`, `timeout`, `force_kill`）的 `details` 载荷缺失会话存活时长、标签页数量、终态 URL 等关键字段；
   - 终端控制台日志（`logger`）在上下文创建、主动关闭、超时回收、强制杀死等正常节点几乎完全静默，导致排障和运维观察困难。

本设计旨在完善上述四个环节的资源闭环控制，引入可配置的底层进程空闲回收、崩溃自愈、超时熔断兜底以及全链路审计与运行日志体系。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
- **底层进程空闲自动回收**：新增 `runtime.browser_idle_timeout_minutes` 配置项。当活跃上下文数量归零时启动空闲计时，超时后自动执行 `adapter.stop()` 释放底层 Chromium/Camoufox OS 进程；下次有操作请求时自动无感按需拉起。
- **进程崩溃感知与存量上下文自愈**：底层适配器挂载 `browser.on("disconnected")` 监听器并提供回调通知机制。当浏览器意外崩溃或被外部强杀时，主动通知 `ContextManager` 批量注销存量僵尸上下文并记入审计，适配器立即清理失效句柄，后续请求自动透明拉起全新浏览器实例。
- **重载与退出并发总超时熔断**：在上下文关闭、适配器停止以及 `terminate()` 整体流程中加入 5 秒并发总超时保护（`asyncio.wait_for` + `asyncio.gather`）；注册 Python `atexit` 钩子并在 `terminate()` 中成对注销，防止退出时残留孤儿进程与回调累积。
- **四大环节全链路审计留痕**：
  - **主动释放**：记录对应上下文的 `close`（或外部插件的 `release`）审计事件；
  - **超时回收**：记录对应上下文的 `timeout` 审计事件；
  - **强制退出/杀死**：记录对应上下文的 `force_kill` 审计事件与操作人 ID；
  - **插件重载/卸载/禁用**：在全局层面遍历所有活跃上下文，批量记录 `terminate` 审计事件，指明因插件重载/卸载而释放。
  - 审计事件的 `details` 均补充上下文存活总时长（秒）、关闭时标签页总数、最后访问 URL 等核心指标。
- **终端运行日志（logger）贯通**：在所有创建、主动释放、超时回收、强杀、进程启动、进程空闲回收、崩溃失联及重载注销等关键节点，规范输出 `logger.info` / `logger.warning`。
- **上下文关联状态级联解绑**：上下文关闭时同步移除 `_creation_locks` 中对应的锁对象。

### 非目标 (Non-Goals)
- 不改变大模型四大复合工具（`pw_page`, `pw_read`, `pw_interact`, `pw_media`）的工具名称、参数形式与行为语义。
- 不修改前端 WebUI 控制台的 REST API 契约结构与返回格式。
- 单元测试不依赖真实的无头浏览器网络端到端测试，全部基于 Mock 与内存测试保障 100% 通过。

### 反向目标 (Anti-Goals)
- 严禁在仍有活跃上下文（未超时、未被主动关闭）存在时提前关闭底层浏览器进程。
- 严禁日志使用第三方日志框架（严禁 `import logging`），必须统一遵循 `from astrbot.api import logger`。
- 严禁出现绝对化词汇（如“彻底解决”、“根治泄漏”等），实事求是。
- 严禁因为单次关闭超时或页面挂起阻塞 AstrBot 的插件重载流程。

---

## 3. 约束条件 (Constraints)

- 必须兼容 Python 3.10+，适配 Playwright (Chromium/Firefox/WebKit) 与 Camoufox[geoip]。
- 必须严格遵循 AstrBot 的 Star 插件生命周期规范（`initialize`, `terminate`）。
- 维持既有 209 个单元测试 100% 通过，并为新增的生命周期与回收机制补充针对性单测。
- 同步更新 `README.md`、`metadata.yaml`、`_conf_schema.json`、`docs/ARCHITECTURE.md` 与 `CHANGELOG.md`。

---

## 4. 架构方案对比与选型 (Approaches)

### 方案一：ContextManager 状态机统管 + 周期轮询核验（已选定）
- **核心逻辑**：
  1. `ContextManager` 掌握所有上下文生命周期的创建与销毁。当活跃上下文数量降为 0 时，记录 `last_zero_context_time = time.time()`；有任何新上下文创建时重置为 `None`。
  2. 周期清理任务（将轮询检测间隔设为 30 秒）在轮询中调用 `context_manager.check_and_cleanup_idle_browser()`。若当前活跃上下文为 0，且距离 `last_zero_context_time` 已超过 `browser_idle_timeout_minutes * 60`，则安全调用 `await adapter.stop()` 退出底层浏览器进程。
  3. 四大环节的关闭逻辑统一收敛在 `ContextManager`：每个环节完成底层 `browser_context.close()` 后，统一由管理器触发 `_fire_lifecycle_log` 写入详细审计，并输出结构化 `logger.info`。
  4. 插件终止时，调用 `await context_manager.close_all_contexts(reason="terminate")`，采用并发总超时批量注销并写入 `terminate` 审计，随后带 5 秒超时停止适配器。
- **优缺点分析**：
  - **优点**：逻辑内聚在已有的调度核心中，没有后台异步计时任务动态取消带来的竞态条件，简单可靠且易于单测覆盖；各环节日志与审计格式完全统一。
  - **缺点**：空闲回收触发时间受轮询周期粒度影响（最大误差为轮询周期，如 30 秒），但对于分钟级（如 5 分钟）的进程级空闲回收完全无影响。

### 方案二：上下文归零事件驱动 + 动态延时协程任务（未选定）
- **核心逻辑**：每当最后一个上下文注销时，动态创建一个 `asyncio.create_task(self._delayed_browser_stop(...))`，若中途有新上下文进来则 `cancel()` 该任务。
- **优缺点分析**：
  - **缺点**：存在多并发请求下的协程取消、竞态挂起和未捕获 CancelledError 风险，增加了状态同步的复杂性。

---

## 5. 详细实现方案 (Detailed Design)

### 5.1 配置项扩展与主入口调整 (`_conf_schema.json`, `metadata.yaml`, `main.py`)

1. **配置架构扩展**：
   在 `runtime` 配置分组中新增：
   ```json
   "browser_idle_timeout_minutes": {
     "description": "无活跃上下文时底层浏览器进程空闲退出时长（分钟），超过此时间自动关闭浏览器 OS 进程释放内存。设置为 0 则保持常驻不退出。",
     "type": "integer",
     "default": 5,
     "minimum": 0,
     "maximum": 1440
   }
   ```
2. **周期轮询间隔优化**：
   在 `main.py` 的 `_periodic_cleanup_loop` 中，将休眠间隔从 300 秒调整为 30 秒，每次循环执行：
   - `await self.context_manager.cleanup_idle_contexts()`（回收超时的单个上下文）；
   - `await self.context_manager.check_and_cleanup_idle_browser()`（无上下文时回收底层浏览器进程）；
   - 定时触发 `audit_logger.cleanup_expired(self._retention_days)`（控制在每小时校验一次，避免频繁读库）。

3. **插件终止闭环 (`terminate`)**：
   ```python
   async def terminate(self):
       """插件销毁释放所有浏览器资源及取消轮询清理任务。"""
       # 1. 显式注销 atexit 钩子，防止热重载累积回调
       try:
           import atexit
           atexit.unregister(self._atexit_cleanup)
       except Exception as e:
           logger.debug(f"[PlaywrightTool] 注销 atexit 钩子异常: {e}")

       if self._cleanup_task and not self._cleanup_task.done():
           self._cleanup_task.cancel()
       try:
           # 2. 并发总超时批量关闭存量上下文并写入审计
           closed_count = await self.context_manager.close_all_contexts(reason="terminate")
           # 3. 超时熔断停止底层浏览器进程
           try:
               await asyncio.wait_for(self.adapter.stop(), timeout=5.0)
           except asyncio.TimeoutError:
               logger.warning("[PlaywrightTool] 停止浏览器适配器超时(5s)，强制释放句柄")
           logger.info(f"[PlaywrightTool] 插件重载/终止完成，共清理 {closed_count} 个存量上下文并停止浏览器进程")
       except Exception as e:
           logger.error(f"[PlaywrightTool] 终止释放异常: {e}")
   ```

4. **进程异常退出兜底 (`atexit`)**：
   在 `PlaywrightToolPlugin.__init__` 中注册 `atexit.register(self._atexit_cleanup)`，其实现为尽力而为（best-effort）防线：
   ```python
   def _atexit_cleanup(self) -> None:
       """解释器退出时的尽力而为兜底钩子。"""
       try:
           if hasattr(self, "adapter") and getattr(self.adapter, "is_running", False):
               logger.warning("[PlaywrightTool] 检测到 Python 解释器退出时底层浏览器仍处于运行状态")
       except Exception:
           pass
   ```

---

### 5.2 适配器状态感知与崩溃自愈 (`adapts/base.py`, `playwright_adapter.py`, `camoufox_adapter.py`)

1. **基类增强 (`BrowserAdapterBase`)**：
   - 增加 `is_running` 属性：返回 `bool(self.browser is not None and getattr(self.browser, "is_connected", lambda: True)())`。
   - 增加 `set_disconnect_callback(cb: Callable[[], Any])` 机制，支持外部注册崩溃断开事件监听。
2. **`PlaywrightAdapter` 与 `CamoufoxAdapter` 改造**：
   - 维护 `self._disconnect_callbacks: list[Callable]`。
   - 在 `start()` 启动成功后，为底层 `browser` 实例挂载断开监听：
     ```python
     if hasattr(self._browser, "on"):
         def _on_disconnected():
             logger.warning(f"[{self.__class__.__name__}] 检测到底层浏览器进程已断开/崩溃")
             self._browser = None
             for cb in self._disconnect_callbacks:
                 try:
                     res = cb()
                     if asyncio.iscoroutine(res):
                         asyncio.create_task(res)
                 except Exception as e:
                     logger.debug(f"[{self.__class__.__name__}] 执行断开回调异常: {e}")
         self._browser.on("disconnected", _on_disconnected)
     ```
   - 在 `create_context()` 中，先判断 `if not self.is_running: await self.start()`，若此前发生过崩溃则在此阶段透明重新拉起浏览器实例。
   - 在 `stop()` 中增强幂等性，加 `try...except` 保护且确保最后彻底清理 `_browser` 与 `_playwright_cm` 句柄。

---

### 5.3 上下文管理器生命周期调度 (`core/context_manager.py`)

1. **新增核心属性与崩溃回调注册**：
   - `browser_idle_timeout_minutes: int`：进程空闲超时分钟数。
   - `last_zero_context_time: float | None`：记录活跃上下文归零的时间戳。
   - 初始化时调用 `self.adapter.set_disconnect_callback(self._on_browser_disconnected)`。
   - 当收到浏览器崩溃断开通知时，`ContextManager` 立即执行：
     ```python
     def _on_browser_disconnected(self):
         """底层浏览器崩溃断开时的即时自愈清理。"""
         logger.warning(f"[ContextManager] 收到浏览器崩溃断开通知，立即失效清理 {len(self.contexts)} 个存量活跃上下文")
         for k, ctx in list(self.contexts.items()):
             self._fire_lifecycle_log(
                 session_id=ctx.session_id,
                 context_key=self._format_context_key(k),
                 owner_id=ctx.owner_id,
                 event_type="terminate",
                 operator_id="system",
                 session_name=ctx.session_name,
                 operator_name="system",
                 owner_name=ctx.owner_name,
                 details={"reason": "browser_crash"},
             )
         self.contexts.clear()
         self._creation_locks.clear()
         self.user_active_pointer.clear()
         self.last_zero_context_time = None
     ```
2. **四环节日志与审计全覆盖实现**：
   - **`close_user_context` (主动释放)**：
     - 调用前提取目标上下文的存活时长、当前标签页数与活跃 URL；
     - 包装 5 秒超时执行 `await asyncio.wait_for(ctx.browser_context.close(), timeout=5.0)`；
     - 清理 `self._creation_locks.pop(key, None)`；
     - 记录审计：`event_type="close"`，`details={"duration_seconds": round(now - ctx.created_time, 1), "tab_count": len(ctx.pages), "final_url": active_url}`；
     - 输出日志：`logger.info(f"[ContextManager] 用户主动关闭上下文: {context_key} (所有者: {ctx.owner_id}, 存活: {duration}s)")`；
     - 若 `len(self.contexts) == 0`，则 `self.last_zero_context_time = time.time()`。
   - **`cleanup_idle_contexts` (超时回收)**：
     - 超时关闭包装 5 秒超时；
     - 清理对应 `_creation_locks`；
     - 记录审计：`event_type="timeout"`，`details={"idle_seconds": ..., "duration_seconds": ..., "tab_count": ..., "final_url": ...}`；
     - 输出日志：`logger.info(f"[ContextManager] 空闲超时回收上下文: {context_key} (空闲时长: {idle_min}m, 存活: {duration}s)")`；
     - 若清空后上下文为 0，设置 `self.last_zero_context_time = time.time()`。
   - **`force_kill_context` (强杀)**：
     - 超时保护与清理 `_creation_locks`；
     - 记录审计：`event_type="force_kill"`，`details={"operator": operator_id, "duration_seconds": ..., "tab_count": ..., "final_url": ...}`；
     - 输出日志：`logger.info(f"[ContextManager] 操作人 {operator_id} 强制终止上下文: {context_key}")`；
     - 若清空后上下文为 0，设置 `self.last_zero_context_time = time.time()`。
   - **`release_external_context` (外部插件主动释放)**：
     - 类似主动释放，记录 `event_type="release"` 与 `logger.info`；若归零则记录空闲时间戳。
   - **`close_all_contexts(reason="terminate")` (插件重载/卸载)**：
     - 采用并发总超时模型：
       ```python
       async def close_all_contexts(self, reason: str = "terminate") -> int:
           """并发总超时批量关闭所有存量活跃上下文并写入 terminate 审计日志。"""
           if not self.contexts:
               return 0
           items = list(self.contexts.items())
           count = len(items)
           now = time.time()

           async def _close_single(k, ctx):
               try:
                   if hasattr(ctx, "browser_context") and ctx.browser_context:
                       res = ctx.browser_context.close()
                       if hasattr(res, "__await__"):
                           await res
               except Exception as e:
                   logger.debug(f"[ContextManager] 批量关闭单个上下文异常: {e}")

               # 写入 terminate 审计
               if self.audit_logger:
                   try:
                       await self.audit_logger.log_lifecycle(
                           session_id=ctx.session_id,
                           context_key=self._format_context_key(k),
                           owner_id=ctx.owner_id,
                           event_type="terminate",
                           operator_id="system",
                           session_name=ctx.session_name,
                           operator_name="system",
                           owner_name=ctx.owner_name,
                           details={"reason": reason, "duration_seconds": round(now - ctx.created_time, 1)},
                       )
                   except Exception as le:
                       logger.debug(f"[ContextManager] 记录批量终止审计异常: {le}")

           # 并发关闭并在外层施加单一的 5.0 秒总超时熔断保护
           try:
               await asyncio.wait_for(
                   asyncio.gather(*[_close_single(k, c) for k, c in items], return_exceptions=True),
                   timeout=5.0,
               )
           except asyncio.TimeoutError:
               logger.warning("[ContextManager] 批量关闭所有活跃上下文总耗时超过 5 秒，强制结束等待")

           self.contexts.clear()
           self._creation_locks.clear()
           self.user_active_pointer.clear()
           self.last_zero_context_time = None
           logger.info(f"[ContextManager] 已完成批量关闭所有活跃上下文 (共 {count} 个, 原因: {reason})")
           return count
       ```
3. **底层进程空闲检测与回收 (`check_and_cleanup_idle_browser`)**：
   ```python
   async def check_and_cleanup_idle_browser(self) -> bool:
       """检查无活跃上下文时是否达到底层浏览器进程空闲退出阈值，若超时则关闭底层浏览器进程。"""
       if self.browser_idle_timeout_minutes <= 0:
           return False
       if len(self.contexts) > 0:
           self.last_zero_context_time = None
           return False
       if not getattr(self.adapter, "is_running", False):
           self.last_zero_context_time = None
           return False
       if self.last_zero_context_time is None:
           self.last_zero_context_time = time.time()
           return False

       idle_seconds = time.time() - self.last_zero_context_time
       threshold_seconds = self.browser_idle_timeout_minutes * 60
       if idle_seconds >= threshold_seconds:
           logger.info(f"[ContextManager] 无活跃上下文已达 {round(idle_seconds / 60, 1)} 分钟，触发底层浏览器进程空闲回收")
           try:
               await asyncio.wait_for(self.adapter.stop(), timeout=5.0)
           except Exception as e:
               logger.warning(f"[ContextManager] 底层浏览器进程回收异常: {e}")
           self.last_zero_context_time = None
           return True
       return False
   ```
4. **上下文创建与进程拉起 (`_create_new_context`)**：
   - 创建成功后，重置 `self.last_zero_context_time = None`。
   - 输出日志：`logger.info(f"[ContextManager] 成功创建浏览器上下文: {key} (所有者: {owner_id}, 模式: {self.mode})")`。

---

### 5.4 审计日志升级 (`core/audit_logger.py`)

- `context_lifecycle_logs` 的 `event_type` 允许录入 `terminate`、`close`、`timeout`、`force_kill`、`release`、`create`、`join`、`switch` 等事件类型。
- `log_lifecycle` 方法确保持久化存储完整的 JSON 字符串到 `details` 列中。
- `query_lifecycle_logs` 支持按新增的 `terminate` 事件类型进行过滤和搜索。

---

## 6. 对构建者的授权与技术决策 (What's Left to the Builder)

构建者已在审阅环节确定以下关键实现决策：
1. **崩溃断开感知与自愈**：由 `BrowserAdapterBase` 暴露 `set_disconnect_callback` 回调，`ContextManager` 监听断开并在崩溃时主动清理存量活跃上下文、记录 `terminate` (reason="browser_crash") 审计，清空僵死对象，使后续操作能无缝拉起新浏览器进程。
2. **`atexit` 机制与重载解绑**：在插件 `__init__` 中注册，在 `terminate()` 中显式 `atexit.unregister` 消除回调累积；`_atexit_cleanup` 采用 best-effort 方式记录警告。
3. **`close_all_contexts` 并发总超时**：采用 `asyncio.gather(*[...], return_exceptions=True)` 配合全局外层单一 5 秒 `asyncio.wait_for` 熔断，确保即使多个页面或 CDP 挂起，总耗时也不会累加超出 5 秒。
4. **测试与日志微调**：单测 mock 编写方式与中文日志微调由构建者自决。
