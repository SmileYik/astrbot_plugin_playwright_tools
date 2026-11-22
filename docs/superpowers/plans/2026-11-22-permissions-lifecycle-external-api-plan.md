# 浏览器工具插件权限细分、上下文生命周期与外部服务基座实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底消除会话共享模式下的管理员越权漏洞与异常静默吞噬，实现 12 项细粒度权限严格校验、PID 式跨页面单调递增 Ref ID，以及基于 AstrBot Star 规范的跨插件 Playwright 共享服务基座。

**Architecture:** 
采用中心化基座扩展模式，在 `core/service_api.py` 中构建 `PlaywrightServiceAPI` 并由主插件挂载为 `self.service`，向外提供按插件名隔离、原生事件静默保活的原生 `BrowserContext`。在核心层引入基于 Key 的双重检查创建锁与 Ref ID 并发锁，实现上下文级独立空闲超时巡检与严格基于当前操作者的会话鉴权。

**Tech Stack:** Python 3.10+, Playwright / Camoufox, AstrBot Context & Star API, `unittest`, `asyncio`.

**Spec:** `docs/superpowers/specs/2026-11-22-permissions-lifecycle-external-api-design.md`

## Global Constraints

- 权限必须扩展为 12 项细粒度配置（read, click, fill, select, hover, focus, drag, press_key, scroll, screenshot, screenshot_full, download），严格按字面匹配不作隐式别名展开。
- Ref ID 在单个上下文生命周期内必须全局单调递增（类 Linux PID 机制，达 1,000,000 循环回滚至 1），跨页面跳转与刷新绝不重置。
- 在 `session` 模式下，工具调用与路由鉴权必须以当前操作者 `sender_id`（非 `ctx.owner_id`）为准；脱机重定向执行严格非管理员白名单校验。
- 外部插件专用上下文设置 `is_external=True`，跳过 `_route_guard` 路由拦截。
- 异常留痕遵循三级策略：纯反射自适应跳过，降级容错记录 DEBUG，资源释放与安全拦截记录 WARNING/ERROR 及上下文。
- 单元测试运行 `python -m unittest discover tests` 必须 100% 通过，不依赖端到端真实浏览器。

## Review Focus

1. **共享会话模式脱机重定向绕过**：管理员在会话中开启页面后，页面内延时 JS（`setTimeout`）触发未授权域名跳转，系统必须使用严格白名单拦截而非管理员特权放行。
2. **外部插件创建时序与并发竞态**：多个外部插件协程同时并发申请同一 `plugin_name` 时，必须通过 KeyedLock + Double-Checked Locking 保证仅创建唯一一个底层实例并安全共享。
3. **Ref ID 循环溢出与并发渲染覆盖**：并发调用 `extract_snapshot` 时，`ref_lock` 保证多任务间游标推进互斥，且达到 1,000,000 时平滑回滚至 1。
4. **外部插件空闲回收不误杀**：外部插件持续发起网络请求或创建标签页时，原生事件静默保活持续刷新 `last_active_time`，仅在彻底静默超过指定 `idle_timeout_seconds` 时才触发兜底回收。
5. **存量配置严格字面匹配**：历史配置仅勾选 `click` 的白名单规则，大模型发起 `hover` 或 `select` 时必须正确返回权限不足拦截提示，杜绝权限扩散。

---

### Task 1: 权限模式与处理器细分扩展 (`_conf_schema.json` & Handlers)

**Files:**
- Modify: `_conf_schema.json:42-66`
- Modify: `tools/handlers/interact_handler.py:150-350`
- Modify: `tools/handlers/media_handler.py:200-340`
- Modify: `core/security_manager.py:110-122`
- Test: `tests/test_conf_schema.py`
- Test: `tests/test_interact_handler.py`
- Test: `tests/test_media_handler.py`
- Test: `tests/test_security_manager.py`

**Interfaces:**
- Consumes: `_conf_schema.json` 中的 `whitelist_rules.items.allowed_actions`
- Produces: `allowed_actions` 包含 12 项权限：`read`, `click`, `fill`, `select`, `hover`, `focus`, `drag`, `press_key`, `scroll`, `screenshot`, `screenshot_full`, `download`。`interact_handler` 与 `media_handler` 各方法绑定对应独立权限。

- [ ] **Step 1: 编写针对 12 项细分权限配置与动作绑定的单元测试**

在 `tests/test_conf_schema.py`、`tests/test_interact_handler.py` 和 `tests/test_media_handler.py` 中添加测试：
```python
def test_conf_schema_has_twelve_actions(self):
    actions = schema["security"]["items"]["whitelist_rules"]["templates"]["rule"]["items"]["allowed_actions"]["options"]
    self.assertEqual(len(actions), 12)
    self.assertIn("select", actions)
    self.assertIn("screenshot_full", actions)

def test_interact_handler_permission_mappings(self):
    # 验证 select_option 要求 'select'，hover 要求 'hover'，press_key 要求 'press_key'，drag 要求 'drag'，focus/blur 要求 'focus'
    pass

def test_media_handler_screenshot_full_permission(self):
    # 验证 screenshot_full 要求 'screenshot_full'，screenshot_viewport 要求 'screenshot'
    pass
```

- [ ] **Step 2: 运行测试验证失败**

运行: `.venv/bin/python -m unittest tests/test_conf_schema.py tests/test_interact_handler.py tests/test_media_handler.py`
预期: FAIL (缺少细分选项，权限仍为 `click`/`screenshot`)

- [ ] **Step 3: 更新 `_conf_schema.json` 与各 Handler 权限映射**

1. 在 `_conf_schema.json` 的 `allowed_actions` 扩展为 12 种配置。
2. 在 `tools/handlers/interact_handler.py` 中将 `select_option` 改为 `required_permission="select"`，`hover` 改为 `"hover"`，`focus` 与 `blur` 改为 `"focus"`，`drag` 改为 `"drag"`，`press_key` 改为 `"press_key"`。
3. 在 `tools/handlers/media_handler.py` 中将 `screenshot_full` 改为 `required_permission="screenshot_full"`。

- [ ] **Step 4: 运行测试验证全部通过**

运行: `.venv/bin/python -m unittest tests/test_conf_schema.py tests/test_interact_handler.py tests/test_media_handler.py`
预期: PASS

- [ ] **Step 5: 提交代码**

```bash
git add _conf_schema.json tools/handlers/interact_handler.py tools/handlers/media_handler.py tests/test_conf_schema.py tests/test_interact_handler.py tests/test_media_handler.py
git commit -m "feat(security): subdivide permissions for interact and media actions"
```

---

### Task 2: 消除会话共享模式下的管理员越权漏洞 (`base_handler.py` & `context_manager.py`)

**Files:**
- Modify: `core/context_manager.py:18-36,220-250`
- Modify: `tools/handlers/base_handler.py:165-250`
- Test: `tests/test_base_handler.py`
- Test: `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `BrowserSessionContext.current_operator_id: str`
- Produces: `base_handler.execute_action` 在 `mode == "session"` 时强制以 `sender_id` 进行鉴权；`_route_guard` 动态鉴权，在无动作人脱机跳转时强制按非管理员白名单基线校验。

- [ ] **Step 1: 编写复现共享会话下普通成员借用管理员所有者权限越权的测试用例**

在 `tests/test_base_handler.py` 中编写测试：
```python
async def test_session_mode_normal_user_denied_even_if_admin_is_owner(self):
    # 模拟 session 模式下，owner_id 为 admin，但当前 sender_id 为普通用户且目标域名不在其白名单
    # 必须鉴权失败并返回权限拒绝提示，绝不能放行
    pass

async def test_session_mode_route_guard_offline_redirect_strict_whitelist(self):
    # 模拟脱机延迟重定向在没有 current_operator_id 时按严格非管理员白名单校验
    pass
```

- [ ] **Step 2: 运行测试验证失败**

运行: `.venv/bin/python -m unittest tests/test_base_handler.py`
预期: FAIL (由于此前以 `ctx.owner_id` 鉴权，普通成员被错误放行)

- [ ] **Step 3: 实现严格基于操作者的鉴权分流与路由守卫脱机兜底**

1. 在 `core/context_manager.py` 的 `BrowserSessionContext` 增加 `current_operator_id: str = ""`。
2. 在 `tools/handlers/base_handler.py` 的 `execute_action` 中：
   - 若 `self.context_mgr.mode == "session"`，鉴权主体赋值为 `sender_id`，并设置 `ctx.current_operator_id = sender_id`。
   - 若 `self.context_mgr.mode == "personal"`，若 `sender_id in ctx.allowed_users` 则继承 `ctx.owner_id`，否则以 `sender_id` 自身鉴权。
3. 在 `_create_new_context` 的 `_route_guard` 中，若有 `ctx.current_operator_id` 则以此鉴权，若无则以空标识（严格非管理员白名单）校验导航请求。

- [ ] **Step 4: 运行测试验证全部通过**

运行: `.venv/bin/python -m unittest tests/test_base_handler.py tests/test_context_manager.py`
预期: PASS

- [ ] **Step 5: 提交代码**

```bash
git add core/context_manager.py tools/handlers/base_handler.py tests/test_base_handler.py tests/test_context_manager.py
git commit -m "fix(security): resolve admin privilege escalation in session mode"
```

---

### Task 3: PID 式 Ref ID 跨页面单调递增与并发加锁 (`markdown_reader.py` & `page_handler.py`)

**Files:**
- Modify: `core/readers/markdown_reader.py:40-160,390-425`
- Modify: `core/context_manager.py:18-50`
- Modify: `tools/handlers/page_handler.py:125-155`
- Test: `tests/test_page_handler.py`
- Test: `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `BrowserSessionContext.next_ref_id`, `BrowserSessionContext.ref_lock`
- Produces: `markdown_reader.get_js_extractor_script(start_ref: int)` 传入动态起始游标，JS 脚本自增打标并返回 `allocated_count`，Python 端在 `ref_lock` 保护下原子更新 `ctx.next_ref_id`。

- [ ] **Step 1: 编写 Ref ID 跨多次提取持续自增且循环回滚的测试用例**

在 `tests/test_page_handler.py` 中编写测试：
```python
async def test_ref_id_monotonic_across_reads_and_page_reloads(self):
    # 模拟多次 read_page，验证第二次阅读时分配的 Ref ID 紧接着上一次的末尾，绝不重置为 1
    pass

async def test_ref_id_concurrency_lock_protection(self):
    # 验证并发提炼正文时 ref_lock 确保提取与游标递增互斥
    pass
```

- [ ] **Step 2: 运行测试验证失败**

运行: `.venv/bin/python -m unittest tests/test_page_handler.py`
预期: FAIL (目前 JS 脚本写死从 1 开始分配)

- [ ] **Step 3: 实现 JS 提取器参数化与 Python 端 `ref_lock` 保护**

1. 在 `BrowserSessionContext` 确保包含 `ref_lock: asyncio.Lock`。
2. 改造 `core/readers/markdown_reader.py`：
   - `get_js_extractor_script(start_ref: int = 1)` 注入当前起始游标基准。
   - JS 内部对未打标交互元素分配 `start_ref + (count++)` 并挂载 `data-astr-ref`，返回结构包含 `allocated_count: count`。
3. 在 `PageHandler.read_page` 中：
   - 使用 `async with ctx.ref_lock:` 包裹快照提取。
   - 读取 `start_ref = ctx.next_ref_id`，提取后推进 `ctx.next_ref_id = (start_ref + allocated_count) % 1_000_000`（若为 0 滚回 1）。

- [ ] **Step 4: 运行测试验证全部通过**

运行: `.venv/bin/python -m unittest tests/test_page_handler.py tests/test_context_manager.py`
预期: PASS

- [ ] **Step 5: 提交代码**

```bash
git add core/readers/markdown_reader.py core/context_manager.py tools/handlers/page_handler.py tests/test_page_handler.py
git commit -m "feat(reader): implement monotonic PID-style Ref ID allocation with ref_lock"
```

---

### Task 4: 上下文独立空闲超时与创建并发防竞态 (KeyedLock & ContextManager)

**Files:**
- Modify: `core/context_manager.py:53-220,530-580`
- Test: `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `BrowserSessionContext.idle_timeout_seconds: float`, `is_external: bool`, `plugin_name: str`
- Produces: `ContextManager.resolve_context` 与 `get_or_create_external_context` 采用双重检查锁；`cleanup_idle_contexts` 按每个上下文独有的 `idle_timeout_seconds` 执行精准淘汰。

- [ ] **Step 1: 编写独立超时判定与并发创建锁的单元测试**

在 `tests/test_context_manager.py` 中编写测试：
```python
async def test_contexts_with_different_idle_timeouts_cleaned_properly(self):
    # ctx1 超时 5 秒，ctx2 超时 300 秒，时间推进 10 秒后仅 ctx1 被回收
    pass

async def test_concurrent_context_creation_produces_single_instance(self):
    # 使用 asyncio.gather 同时发起 10 次获取同一 key 的请求，底层 create_context 仅执行 1 次
    pass
```

- [ ] **Step 2: 运行测试验证失败**

运行: `.venv/bin/python -m unittest tests/test_context_manager.py`
预期: FAIL (当前为全局统一硬编码超时，且无创建锁)

- [ ] **Step 3: 实现 KeyedLock 与独立超时淘汰逻辑**

1. `BrowserSessionContext` 增加 `idle_timeout_seconds: float = 600.0`。
2. `ContextManager` 引入 `self._creation_locks: dict[Any, asyncio.Lock]` 与 `self._global_lock = asyncio.Lock()`，在创建前按 key 获取专用锁并执行 double-checked 验证。
3. 更新 `cleanup_idle_contexts`，逐个比较 `now - ctx.last_active_time > ctx.idle_timeout_seconds`，对超期上下文安全调用 `browser_context.close()` 并从 `contexts` 移除。

- [ ] **Step 4: 运行测试验证全部通过**

运行: `.venv/bin/python -m unittest tests/test_context_manager.py`
预期: PASS

- [ ] **Step 5: 提交代码**

```bash
git add core/context_manager.py tests/test_context_manager.py
git commit -m "feat(runtime): add per-context idle timeout and keyed creation lock"
```

---

### Task 5: 跨插件服务基座实现 (`core/service_api.py` & `main.py`)

**Files:**
- Create: `core/service_api.py`
- Modify: `core/context_manager.py:220-280`
- Modify: `main.py:160-210,335-349`
- Test: `tests/test_service_api.py`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: `ContextManager`, `PlaywrightToolPlugin`
- Produces: `PlaywrightServiceAPI` 暴露 `ready`, `get_browser_context`, `release_browser_context`, `context()`。外部插件设置 `is_external=True`，跳过 `_route_guard` 并自动挂载原生网络/页面事件保活监听。

- [ ] **Step 1: 编写针对 `PlaywrightServiceAPI` 的完整功能单元测试**

新建 `tests/test_service_api.py`：
```python
async def test_external_service_lifecycle_and_reuse(self):
    # 首次获取新建，再次获取幂等返回同一 BrowserContext
    pass

async def test_external_service_async_context_manager(self):
    # 测试 async with service.context(...) as ctx 退出后自动释放
    pass

async def test_external_service_activity_tracker_resets_last_active(self):
    # 测试触发 page/request 原生事件时自动 touch 更新活跃时间
    pass

async def test_external_context_skips_route_guard(self):
    # 验证 is_external=True 时不挂载 _route_guard
    pass
```

- [ ] **Step 2: 运行测试验证失败**

运行: `.venv/bin/python -m unittest tests/test_service_api.py`
预期: FAIL (`service_api` 不存在)

- [ ] **Step 3: 实现 `PlaywrightServiceAPI` 并挂载至 `PlaywrightToolPlugin.service`**

1. 编写 `core/service_api.py`，实现 `PlaywrightServiceAPI` 及其就绪事件等待、上下文获取/释放与 `@asynccontextmanager def context()`。
2. 挂载原生 `on("page")`、`on("request")`、`on("response")` 事件心跳。
3. 在 `ContextManager` 中创建外部上下文时设置 `is_external=True` 并跳过 `_route_guard`。
4. 在 `main.py` 的 `PlaywrightToolPlugin.__init__` 中实例化 `self.service = PlaywrightServiceAPI(...)`，并在 `initialize()` 完成时调用 `self.service.set_ready()`。

- [ ] **Step 4: 运行测试验证全部通过**

运行: `.venv/bin/python -m unittest tests/test_service_api.py tests/test_plugin_main.py`
预期: PASS

- [ ] **Step 5: 提交代码**

```bash
git add core/service_api.py core/context_manager.py main.py tests/test_service_api.py tests/test_plugin_main.py
git commit -m "feat(api): implement PlaywrightServiceAPI for cross-plugin browser sharing"
```

---

### Task 6: 三级异常处理与日志留痕全工程治理

**Files:**
- Modify: `core/context_manager.py`
- Modify: `core/readers/markdown_reader.py`
- Modify: `core/readers/aria_reader.py`
- Modify: `core/audit_logger.py`
- Modify: `tools/handlers/base_handler.py`
- Modify: `tools/handlers/interact_handler.py`
- Modify: `tools/handlers/page_handler.py`
- Modify: `tools/handlers/media_handler.py`
- Modify: `adapts/playwright_adapter.py`
- Test: `tests/test_audit_logger.py`
- Test: `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `astrbot.api.logger`
- Produces: 梳理消除 40 余处裸 `pass`，按三级规范分别打印 DEBUG 或 WARNING/ERROR。

- [ ] **Step 1: 编写验证异常捕获留痕的测试用例**

在 `tests/test_context_manager.py` 与相关单测中打桩异常并断言 `logger.warning` / `logger.debug` 被调用。

- [ ] **Step 2: 运行测试验证失败**

运行: `.venv/bin/python -m unittest tests/test_context_manager.py`
预期: FAIL (当前很多地方直接 pass，无日志输出)

- [ ] **Step 3: 逐一重构全工程的裸 `pass`**

1. 将所有关闭清理（如 `close()`）、路由守卫报错、弹窗监听崩溃改为 `logger.warning`。
2. 将非关键属性探测（如群昵称提取失败、密码框嗅探失败）改为 `logger.debug`。
3. 仅保留纯内部反射探测（如 `inspect.signature`）的确定性分支。

- [ ] **Step 4: 运行全量单测验证全部通过**

运行: `.venv/bin/python -m unittest discover tests`
预期: PASS

- [ ] **Step 5: 提交代码**

```bash
git add core/ tools/ adapts/ tests/
git commit -m "refactor(logging): replace silent bare pass statements with graded debug and warning logs"
```

---

### Task 7: 技术文档与说明更新 (`README.md` & `docs/EXTERNAL_API.md`)

**Files:**
- Modify: `README.md`
- Create: `docs/EXTERNAL_API.md`
- Modify: `metadata.yaml`
- Modify: `tests/test_plugin_main.py:100`

**Interfaces:**
- Consumes: 设计规范中的业务理由与接口规范
- Produces: `README.md` 包含“邀请协助”与“白名单放行”设计理由与 12 项权限说明；`docs/EXTERNAL_API.md` 包含完整的外部插件接入指南与代码示例；修复测试中对 `metadata.yaml` 版本的断言。

- [ ] **Step 1: 编写文档并修正版本断言测试**

1. 在 `README.md` 详尽阐明“邀请协助”（解决个人隔离模式受控委托）与“白名单放行”（防 SSRF 与恶意交互）的**设计背景与业务理由**，并更新 12 种权限表格。
2. 创建 `docs/EXTERNAL_API.md`，提供通过 `self.context.get_registered_star("PlaywrightTool").star_cls.service` 接入的代码样例、生命周期与自动释放范式。
3. 同步修复 `tests/test_plugin_main.py` 中的版本比对断言，确保与 `metadata.yaml` 同步。

- [ ] **Step 2: 运行全量单测验证 100% 通过**

运行: `.venv/bin/python -m unittest discover tests`
预期: 194+ tests PASS, 0 failures, 0 errors.

- [ ] **Step 3: 提交代码**

```bash
git add README.md docs/EXTERNAL_API.md metadata.yaml tests/test_plugin_main.py
git commit -m "docs: explain rationale for invite and whitelist features, add external API docs"
```
