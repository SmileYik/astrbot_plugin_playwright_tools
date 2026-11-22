# 浏览器工具插件权限细分、上下文生命周期与外部服务基座设计

## 1. 意图与背景 (Intent & Why)

当前 `astrbot_plugin_playwright_tools` 作为面向大模型的浏览器自动化插件，在实际运行与多插件协作中暴露出以下架构与稳定性痛点：
1. **权限划分粗糙**：`_conf_schema.json` 仅定义了 6 种粗粒度操作，导致交互处理器中的 `select`, `hover`, `focus`, `blur`, `drag`, `press_key` 被强行捆绑在 `click` 或 `fill` 权限下，且视口截图与长截图混用单一 `screenshot` 权限，无法满足精细化安全管控。
2. **异常静默吞噬**：全工程存在约 40 处裸 `pass`，关键网络拦截、弹窗监听、资源释放与属性自适应探测缺乏分级留痕，为排障带来困难。
3. **Ref ID 重复复用**：`markdown_reader` 提取正文时在 JS 内部固定 `let nextRef = 1`，未实现跨页面/跨更新的单调递增，易导致大模型使用老引用误操作新页面元素。
4. **会话共享模式下的越权漏洞**：在 `session` 模式下，鉴权逻辑统一使用 `ctx.owner_id`。若管理员率先开启会话，普通群成员后续操作将直接继承管理员豁免权限，绕过白名单。
5. **缺少跨插件服务能力**：其他 AstrBot 插件缺乏对本插件 Playwright 实例的复用途径，需重复启动浏览器导致内存开销激增。且由于 AstrBot 插件相互隔离在独立目录，无法使用标准 Python `import` 静态导包，需对齐 AstrBot Star 实例寻址范式。

本设计的目的在于彻底解决上述权限漏洞与稳定性隐患，将本插件升级为 AstrBot 平台高可靠的浏览器中枢基座。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
- **细粒度权限管控**：将操作权限扩充并明确对齐至 12 种细分行为（含 read、click、fill、select、hover、focus、drag、press_key、scroll、screenshot、screenshot_full、download），严格字面匹配。
- **三级异常留痕体系**：建立良性忽略、DEBUG 现场还原、WARNING/ERROR 核心告警的分级机制。
- **PID 式 Ref ID 全局自增**：在上下文生命周期内单调递增 Ref ID（最大 1,000,000 循环回滚），无论网页刷新或重定向均不重置。
- **消除共享会话越权**：严格区分 `session` 模式（各操作者按自身 `sender_id` 鉴权）与 `personal` 模式（受邀协作者继承所有者凭据）。
- **AstrBot Star 规范的外部服务基座**：通过 `PlaywrightToolPlugin.service`（`PlaywrightServiceAPI`）向外暴露服务，支持第三方插件通过 `self.context.get_registered_star("PlaywrightTool").star_cls.service` 接入；提供按插件名复用原生 `BrowserContext`、支持 `async with service.context(...)` 自动上下文管理、原生网络与页面事件静默保活、独立空闲超时巡检与主动释放。
- **高并发安全保障**：确保上下文创建时双重检查锁定，且单个上下文内 Ref ID 提取原子互斥。
- **完善的技术文档**：在 README 中阐述“邀请协助”与“白名单放行”机制，在 `docs/EXTERNAL_API.md` 给出外部插件标准接入指南与完整示例。

### 非目标 (Non-Goals)
- 不改变对外暴露给大模型的四大复合工具基本名称（`pw_page`, `pw_read`, `pw_interact`, `pw_media`）。
- 不把上下文内的所有页面操作（点击、滚动等）强行互斥串行化，保持非 Ref 提取操作的高并发吞吐。
- 不引入重型代理对象封装 `BrowserContext`，向外部插件交付原生 Playwright 实例。

### 反向目标 (Anti-Goals)
- 严禁外部插件的上下文与大模型的对话上下文混用命名空间，防止工具互相干扰。
- 严禁通过简单的捕获异常加 print 替代标准化的 `astrbot.api.logger`。
- 严禁外部插件异常挂起或忘记释放时导致底层浏览器进程无限期泄漏（必须有巡检兜底）。

---

## 3. 约束条件 (Constraints)

- 必须兼容 Python 3.10+ 及 Playwright / Camoufox 驱动。
- 必须遵循 AstrBot Star 插件生命周期（`initialize`, `terminate`）与跨插件实例发现机制。
- 不破坏现有前端 WebUI 控制台的接口契约与数据结构。
- 单元测试套件全量通过，不依赖端到端真实浏览器环境。

---

## 4. 架构方案对比与选型 (Approaches)

### 方案 A：中心化基座扩展与 Star 实例接入（已选定）
- **核心设计**：在插件入口 `PlaywrightToolPlugin` 上挂载公共服务实例 `self.service = PlaywrightServiceAPI(...)`。外部插件通过 AstrBot 的 `context.get_registered_star("PlaywrightTool").star_cls.service` 获得服务句柄。外部插件作为专用命名租户注册在统一的 `ContextManager` 中，底层复用同一 Adapter 驱动；统一后台定时器轮询大模型与外部插件上下文独有的 `idle_timeout_seconds`。
- **优点**：完全契合 AstrBot 插件生态架构（无静态导包摩擦），架构高度内聚，资源统一调度回收，无需两套并行管理逻辑，维护成本低。
- **权衡**：需要 `ContextManager` 具备区分外部上下文与会话上下文的抽象能力。

### 方案 B：分层双轨独立池（未选定）
- **核心设计**：将外部插件上下文单独抽离为 `ExternalContextManager`，独立字典、独立定时器与独立回收队列，物理隔离大模型与外部插件。
- **缺点**：存在重复代码、双倍轮询开销，且运维控制台无法集中展示全局浏览器实例。

---

## 5. 详细实现方案 (Detailed Design)

### 5.1 权限细分与鉴权架构

#### 1. 权限项扩展 (`_conf_schema.json`)
白名单规则 `allowed_actions` 扩展为 12 种细分权限：
```json
{
  "options": [
    "read",
    "click",
    "fill",
    "select",
    "hover",
    "focus",
    "drag",
    "press_key",
    "scroll",
    "screenshot",
    "screenshot_full",
    "download"
  ],
  "labels": [
    "读取文本 (read)",
    "点击交互 (click)",
    "输入表单 (fill)",
    "下拉选择 (select)",
    "鼠标悬停 (hover)",
    "焦点控制 (focus)",
    "元素拖拽 (drag)",
    "键盘按键 (press_key)",
    "页面滚动 (scroll)",
    "视口截图 (screenshot)",
    "全页长截图 (screenshot_full)",
    "下载文件 (download)"
  ]
}
```

#### 2. 工具处理器权限对齐
- `interact_handler.py`:
  - `click` -> `required_permission="click"`
  - `fill_form` -> `required_permission="fill"`
  - `select_option` -> `required_permission="select"`
  - `hover` -> `required_permission="hover"`
  - `focus` & `blur` -> `required_permission="focus"`
  - `drag` -> `required_permission="drag"`
  - `press_key` -> `required_permission="press_key"`
  - `scroll` -> `required_permission="scroll"`
- `media_handler.py`:
  - `screenshot_viewport` -> `required_permission="screenshot"`
  - `screenshot_full` -> `required_permission="screenshot_full"`
  - `download_file` -> `required_permission="download"`

#### 3. 严格字面匹配升级策略 (Strict Literal Matching)
- 系统对 `allowed_actions` 实行严格字面匹配校验，不进行向后隐式别名展开（即历史勾选的 `click` 仅包含点击，不自动赋予 `hover`/`select`/`drag`；历史的 `screenshot` 仅包含视口截图，不自动赋予 `screenshot_full`）。
- 管理员升级插件后，若需非管理员访问长截图或高级交互动作，必须在 WebUI 控制台中重新勾选。

#### 4. 越权漏洞修复 (`base_handler.py` & `context_manager.py`)
在 `base_handler.execute_action` 中：
- 若 `context_mgr.mode == "session"`：鉴权主体始终为当前操作者 `sender_id`。即使首个创建者为管理员，普通群员执行任何操作也必须通过自身白名单检查。在执行动作前，将 `ctx.current_operator_id = sender_id` 设为当前操作者。
- 若 `context_mgr.mode == "personal"`：
  - 若 `sender_id == ctx.owner_id`，以 `sender_id` 鉴权。
  - 若 `sender_id in ctx.allowed_users`（受邀协作者），继承 `ctx.owner_id` 鉴权凭证执行协助。
  - 否则拒绝访问。
- `_route_guard` 路由拦截守卫：
  - 若当前有正在执行的动作协程，使用 `ctx.current_operator_id` 进行导航鉴权。
  - 若属于脱机/延迟跳转（无活跃动作执行人），一律按严格的非管理员域名白名单基线进行校验，杜绝任何逃逸漏洞。

---

### 5.2 上下文独立空闲超时与并发安全

#### 1. 数据结构扩展 (`BrowserSessionContext`)
```python
@dataclass
class BrowserSessionContext:
    session_id: str
    owner_id: str
    browser_context: "BrowserContext"
    current_page: "Page"
    pages: list["Page"] = field(default_factory=list)
    allowed_users: set[str] = field(default_factory=set)
    created_time: float = field(default_factory=time.time)
    last_active_time: float = field(default_factory=time.time)
    idle_timeout_seconds: float = 600.0   # 独立超时设置
    is_external: bool = False             # 是否为外部插件托管
    plugin_name: str = ""                 # 外部插件标识
    current_operator_id: str = ""         # 当前动作操作者（用于会话模式鉴权绑定）
    ref_lock: asyncio.Lock = field(default_factory=asyncio.Lock) # Ref ID 专属并发锁
    next_ref_id: int = 1
```

#### 2. 上下文创建并发控制 (KeyedLock + Double-Checked Locking)
在 `ContextManager` 中：
```python
self._creation_locks: dict[Any, asyncio.Lock] = {}
self._global_lock = asyncio.Lock()

async def _get_lock_for_key(self, key: Any) -> asyncio.Lock:
    async with self._global_lock:
        if key not in self._creation_locks:
            self._creation_locks[key] = asyncio.Lock()
        return self._creation_locks[key]
```
在 `resolve_context` 与外部获取接口中：
```python
if key not in self.contexts:
    lock = await self._get_lock_for_key(key)
    async with lock:
        if key not in self.contexts:
            ctx = await self._create_new_context(...)
            self.contexts[key] = ctx
```

#### 3. 全局统一巡检循环
`_periodic_cleanup_loop` 巡检所有上下文：
只要 `now - ctx.last_active_time > ctx.idle_timeout_seconds`，安全关闭底层 `browser_context` 并从 `contexts` 移除，审计并记录生命周期日志。

---

### 5.3 跨插件服务基座架构 (`PlaywrightServiceAPI`)

在 `core/service_api.py` 中定义服务中枢并在 `PlaywrightToolPlugin.__init__` 中挂载为 `self.service`：

```python
class PlaywrightServiceAPI:
    """供其他 AstrBot 插件接入的 Playwright 共享浏览器基座服务。"""

    def __init__(self, plugin: "PlaywrightToolPlugin", context_mgr: ContextManager):
        self._plugin = plugin
        self._context_mgr = context_mgr
        self._ready_event = asyncio.Event()

    @property
    def ready(self) -> bool:
        """底层浏览器引擎是否已完成初始化并就绪。"""
        return self._ready_event.is_set()

    def set_ready(self):
        self._ready_event.set()

    async def get_browser_context(
        self,
        plugin_name: str,
        idle_timeout_minutes: int | None = None,
        clean: bool = False,
        timeout: float = 30.0,
    ) -> BrowserContext:
        """获取指定外部插件专用的原生 Playwright BrowserContext。"""
        ...

    async def release_browser_context(self, plugin_name: str) -> bool:
        """外部插件主动释放专用的 BrowserContext。"""
        ...

    @asynccontextmanager
    async def context(
        self,
        plugin_name: str,
        idle_timeout_minutes: int | None = None,
        clean: bool = False,
        timeout: float = 30.0,
    ) -> AsyncIterator[BrowserContext]:
        """异步上下文管理器模式：获取 BrowserContext，在代码块执行完毕退出时自动触发主动释放。"""
        ctx = await self.get_browser_context(
            plugin_name, idle_timeout_minutes=idle_timeout_minutes, clean=clean, timeout=timeout
        )
        try:
            yield ctx
        finally:
            await self.release_browser_context(plugin_name)
```

#### 1. 外部插件调用范式 (Star 实例寻址)
```python
from astrbot.api.star import Star

class ExamplePlugin(Star):
    async def do_something(self):
        meta = self.context.get_registered_star("PlaywrightTool")
        if not meta or not meta.star_cls:
            raise RuntimeError("请先启用 astrbot_plugin_playwright_tools 插件")
        
        service = meta.star_cls.service
        # 模式一：长期/多次复用
        b_ctx = await service.get_browser_context("my_plugin_name", idle_timeout_minutes=15)
        page = await b_ctx.new_page()
        await page.goto("https://example.com")
        
        # 模式二：临时任务自动释放
        async with service.context("my_plugin_name") as b_ctx:
            page = await b_ctx.new_page()
            await page.goto("https://example.com")
            # 退出代码块后自动回收
```

#### 2. 外部插件专用网络放行
外部插件属于平台受信任的后端代码，在创建其专用上下文时设置 `is_external=True`，**跳过挂载 `_route_guard` 路由拦截守卫**。这既保障了第三方插件能自由调用各类业务接口，又避免了底层海量网络静态资源路由进入 Python 层的性能损耗。

#### 3. 原生事件静默感知
在为外部插件创建 `BrowserContext` 时，自动挂载事件监听：
```python
def _attach_activity_tracker(b_ctx: BrowserContext, session_ctx: BrowserSessionContext):
    def _touch():
        session_ctx.touch()

    b_ctx.on("page", lambda p: _touch())
    b_ctx.on("request", lambda req: _touch())
    b_ctx.on("response", lambda resp: _touch())
```

---

### 5.4 PID 式 Ref ID 全局自增与并发提取

#### 1. Python 侧调度 (`markdown_reader.py` & `page_handler.py`)
提取快照时加锁：
```python
async def extract_snapshot(self, page: Any, context: BrowserSessionContext) -> PageSnapshot:
    async with context.ref_lock:
        start_ref = context.next_ref_id
        script = self.get_js_extractor_script(start_ref)
        data = await page.evaluate(script)
        allocated_count = int(data.get("allocated_count", 0))
        # 递增游标（达 1,000,000 循环）
        context.next_ref_id = (start_ref + allocated_count) % 1_000_000
        if context.next_ref_id == 0:
            context.next_ref_id = 1
        return self._build_snapshot(data, page)
```

#### 2. JavaScript 提取脚本改造
- 不再固定 `let nextRef = 1`，而是将 Python 传入的 `start_ref` 作为起始基准。
- 对未打标（无 `data-astr-ref`）的可交互元素依序赋值 `start_ref + (count++)`，并挂载 `data-astr-ref` 属性。
- 即使页面经历动态局部加载，已打标元素保持旧 Ref，新进入 DOM 元素沿用自增 Ref。
- 返回字典新增 `allocated_count: count`。

---

### 5.5 三级异常留痕与规范治理

1. **允许跳过（静默 pass）**：
   - 内部反射探测：`inspect.signature` 参数嗅探、可选字段适配。
2. **DEBUG 留痕（非致命容错降级）**：
   - 发送者群昵称读取异常 -> `logger.debug(f"[PlaywrightTool] 获取发送者昵称降级: {e}")`
   - 输入框密码类型探测异常 -> `logger.debug(f"[PlaywrightTool] 探测密码框类型异常: {e}")`
   - 页面等待稳定状态超时（`networkidle`） -> 忽略超时异常，非超时记录 debug。
3. **WARNING/ERROR 留痕（关键生命周期与通信）**：
   - 顶层路由守卫 `_route_guard` 中断/放行异常 -> `logger.warning(f"[PlaywrightTool] 路由守卫拦截异常: {e}")`
   - 上下文/页面 `close()` 释放异常 -> `logger.warning(f"[PlaywrightTool] 关闭浏览器上下文异常: {e}")`
   - 弹窗监听回调崩溃 -> `logger.warning(f"[PlaywrightTool] 响应浏览器弹窗异常: {e}")`
   - 审计数据库写入异常 -> `logger.error(f"[PlaywrightTool] 审计写入失败: {e}", exc_info=True)`

---

## 6. 文档编写规范

1. **`README.md` 补充**：
   - **“邀请协助”机制及其设计理由**：
     - *业务痛点与理由*：在个人隔离模式（`personal`）下，每个用户的浏览器上下文彼此物理隔离，保障了极高的隐私性。然而在实际群聊协作中，用户经常遇到多步表单填报、复杂排障或需要他人代操作的场景。若为协助而将全局切换为共享模式，会导致私密 Cookie 和会话暴露给全群；若直接向群友透露账号密码，存在严重凭证泄露风险。
     - *解决的问题与机制*：设计了基于最小特权的“定向受控委托”协助通道。上下文所有者通过 `/browser invite <UID>` 显式单向授权指定协作者进入当前上下文。协作者可以在不接触底层 Cookie/凭据明文的前提下代为点击和填表，任务完成后可随时回收或随会话关闭而失效，完美兼顾了协同办公的便利性与多租户隐私防线。
   - **“白名单放行”机制及其设计理由**：
     - *安全威胁与理由*：在群聊等开放环境中，普通用户可直接驱动大模型使用浏览器工具。大模型具备自主推导 URL、自主点击跳转和表单提交的能力，极易受到 Prompt 注入攻击或被恶意诱导：例如发起 SSRF 攻击访问局域网服务（如 `127.0.0.1`、内网路由器、云平台元数据 `169.254.169.254`）、跳转钓鱼挂马网站、或在不可信页面中静默下载未知二进制文件。
     - *解决的问题与机制*：确立了“域名通配过滤 + 动作行为细粒度掩码”的双重熔断机制。非管理员仅能在严格限定的白名单域名范围内冲浪，且即使在白名单域名内，也只能执行管理员显式勾选的行为（如只读、视口截图，严控表单输入与文件下载）。顶层路由守卫直接在网络层拦截一切非法跳转，为大模型在开放场景的安全运行提供坚不可摧的边界防护。
2. **`docs/EXTERNAL_API.md`**：
   - 外部插件基于 `context.get_registered_star("PlaywrightTool").star_cls.service` 的接入范式说明。
   - `get_browser_context`、`release_browser_context` 与 `async with service.context()` 完整用法示例。
   - 原生事件静默心跳与差异化空闲回收机制说明。

---

## 7. 构建者自决部分 (What's Left to the Builder)

- `KeyedLock` 的具体内存清理策略（可在无等待协程时弱引用清除或字典保留）。
- 各测试用例中对 `allocate_ref_id`、细分权限和并发冲突模拟的具体 Mock 实现。
