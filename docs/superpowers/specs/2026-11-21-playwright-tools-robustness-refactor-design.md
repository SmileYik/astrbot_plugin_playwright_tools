# Playwright 工具体系健壮性与架构重构设计文档

## 1. 意图与背景 (Intent & Why)

当前 `astrbot_plugin_playwright_tools` 插件在实际使用中暴露了一系列影响稳定性、安全性与代码质量的问题：
1. **Ref ID 冲突风险**：每次快照重新从 1 分配元素序号，当页面发生动态重排或切换页面后，大模型若沿用历史 Ref ID 会引发误触其他元素的隐患。
2. **密码审计安全泄露**：虽然配置项支持 `mask_password_inputs`，但仅在阅读器输出时脱敏；交互执行 `fill` 时，填入的敏感密码仍以明文形式记录进审计数据库 `audit.db` 与系统错误日志中。
3. **切面逻辑重复分散**：`PageHandler`、`InteractHandler`、`MediaHandler` 内部超过 15 个具体动作方法均重复书写上下文寻址、权限预检、异常捕获、Traceback 记录与审计写入等 20 多行模板代码，维护成本极高。
4. **历史死代码残留**：`core/page_extractor.py`（500+ 行）已被独立的 `readers/` 体系完全替代，但仍作为无用依赖残留于代码库与测试中。
5. **自定义 ARIA 解析脆弱**：当前的 `AriaSnapshotReader` 注入了大量自定义 JS 脚本递归遍历 DOM 模拟 ARIA 树；而 Playwright 官方原生现已提供高度成熟的 `aria_snapshot(mode='ai')` 与 `aria-ref=` 选择器引擎。
6. **缺乏页面就绪与快照失效机制**：导航与点击交互后未等待动态异步渲染，易抓取到未渲染完毕的空白页面；同时快照缺乏跨路由、跨交互与时间维度的自动失效策略。
7. **上下文创建泄漏隐患**：`ContextManager` 创建底层 `BrowserContext` 后若挂载路由或新建页面失败，未能自动回滚清理，导致孤儿浏览器上下文残留。

本项目旨在系统性解决上述问题，全面提升插件的健壮性、安全性与架构优雅度。无需考虑对历史版本的向后兼容。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **Ref ID 字符串化与上下文单调递增**：
   - 将所有工具参数与内部数据结构中的 `ref` 统一由 `int` 变更为 `str`；
   - `InlineMarkdownReader` 由 Context 统一管理单调递增计数器（支持最大安全阈值如 1,000,000 溢出回滚至 0），并向 DOM 注入 `data-astr-ref`；
   - `AriaSnapshotReader` 直接对接 Playwright 官方原生 `aria_snapshot(mode='ai')`，生成原生 `e1`、`e2` 格式并在交互时采用 `aria-ref=` 选择器定位。
2. **密码全链路脱敏**：
   - 交互填表动作中，若配置开启密码脱敏且目标组件为 `password` 类型，切面层统一将入参值转为 `******` 后再进入审计记录、返回提示信息与日志。
3. **基类模板方法切面收敛**：
   - 抽取 `BaseActionHandler`，通过统一的 `execute_action()` 模板方法集中复用上下文寻址、权限校验、密码脱敏、异常捕获、页面稳定等待及审计日志落库。
4. **死代码与废弃接口彻底清理**：
   - 移除 `core/page_extractor.py`、`tests/test_page_extractor.py` 及所有旧版兼容参数垫片。
5. **官方 ARIA 引擎原生替换**：
   - 彻底删除 `AriaSnapshotReader` 中 500 多行的注入 JS 遍历脚本，全面切换为 Playwright 官方接口。
6. **页面就绪等待与四重快照失效**：
   - 在页面导航与 `pw_read` 提取前，执行 `domcontentloaded` + `networkidle` 限时守卫（1.5秒超时熔断）；
   - 快照失效采用：(1) 主 Frame `framenavigated` 监听、(2) URL 比对、(3) 交互变更脏标记、(4) 60秒 TTL 过期。
7. **上下文创建失败自动回滚**：
   - `ContextManager._create_new_context` 增加严格的 `try...except` 异常清理，任何初始化步骤异常均自动关闭 `BrowserContext`。
8. **文档与 SKILL 同步更新**：
   - 更新 `skills/playwright-tool/SKILL.md`、`docs/ARCHITECTURE.md` 与 `CHANGELOG.md`。
9. **上架合规之统一 Logger 导入**：
   - 彻底移除 `tools/tools.py`、`page_handler.py`、`interact_handler.py`、`media_handler.py` 及相关文件中对标准库 `logging` 的回退引入，严格仅通过 `from astrbot.api import logger` 获取日志器。
10. **上架合规之专属数据持久化目录**：
   - 调整所有持久化资源（审计数据库、下载文件、截图、审计截图）的默认路径至 AstrBot 插件规范目录：`data/plugin_data/astrbot_plugin_playwright_tools/`。同步更新 `_conf_schema.json` 与 `main.py` 默认值。

### 非目标 (Non-Goals)
- 不保留任何对历史版本调用格式的向下兼容层（如兼容整型 ref 或旧版参数别名）。
- 不新增四大独立复合工具（`pw_page`, `pw_read`, `pw_interact`, `pw_media`）之外的新工具。
- 不引入耗时且不稳定的真实浏览器端到端（e2e）测试（遵循 `AGENTS.md`，使用 100% 覆盖的单元测试）。

### 反向目标 (Anti-Goals)
- 禁止硬等待无超时的 `networkidle`，避免 WebSocket/长轮询导致整个工具卡死。
- 禁止在审计数据库中泄露任何密码明文。
- 禁止引入黑盒动态参数反射或难以单测 Mock 的隐式逻辑。

---

## 3. 约束条件 (Constraints)

- **环境规范**：Python 3.12，Playwright 1.62.0，Camoufox，运行于 Linux / Sandbox。
- **平台合规约束**：
  1. 日志必须且只能从 `astrbot.api` 导入（`from astrbot.api import logger`），严禁使用 Python 内置 `logging` 模块或其他第三方日志库。
  2. 插件生成的所有持久化数据（审计数据库、下载文件、截图等）必须存放于 `data/plugin_data/astrbot_plugin_playwright_tools/` 专属目录下，严禁散落在根 `data/` 目录。
- **架构规范**：所有复合工具必须统一维护 `_actions` 字典分发；执行具备全局超时保护。
- **测试规范**：执行 `.venv/bin/python -m unittest discover tests`，必须保证 100% 通过且无回归。
- **文档规范**：表达严谨简洁，不出现绝对化词汇（如“彻底xxx”、“根治xxx”），实事求是。

---

## 4. 技术方案选型 (Approaches Considered)

针对横切关注点（鉴权、审计、日志、脱敏、稳定等待）的收敛，讨论了三种方案：

| 方案 | 核心实现 | 优势 | 劣势 | 结论 |
|---|---|---|---|---|
| **方案一：基类模板方法模式** (BaseActionHandler) | 提取基类 `BaseActionHandler`，提供统一的 `execute_action()` 模板方法分发所有具体动作。 | 执行链路透明显式，易于单测与调试，状态共享直观，无反射黑盒。 | 每个动作需通过基类调度。 | **选中 (Selected)** |
| **方案二：声明式切面装饰器模式** (Action Decorator) | 使用 `@action_guard` 装饰各 Handler 方法，通过入参反射自动织入切面。 | 方法声明简洁美观。 | 依赖参数反射与闭包，遇不同签名或 Mock 测试时易出现隐式异常，调试定位成本高。 | 放弃 (Rejected) |
| **方案三：复合工具门面层拦截** (Tool Facade Middleware) | 在 `tools/tools.py` 的 `PwTool.call` 集中拦截，Handler 降级为纯底层驱动。 | 外层入口高度集中。 | 缺乏纵深防御，绕开门面直接调用 Handler 时将遗漏安全鉴权与审计。 | 放弃 (Rejected) |

---

## 5. 详细架构与关键模块设计 (Detailed Design)

### 5.1 Ref ID 架构与双阅读器设计
1. **Ref 标识全链路字符串化**：
   - `PW_INTERACT_SCHEMA` 与 `PW_MEDIA_SCHEMA` 中的 `ref` 定义为 `type: "string"`；
   - `InteractHandler` 与 `MediaHandler` 的相关方法形参变更为 `ref: str`。
2. **`InlineMarkdownReader`（Markdown 模式）**：
   - 依赖 `BrowserSessionContext` 维护的 `next_ref_id: int`（初始值 1，最大值 1,000,000，溢出回滚为 0）；
   - 在执行内容提取时，将当前上下文分配的单调递增数值转换为字符串注入 DOM `data-astr-ref`；
   - `ctx.ref_map[ref_str]` 记录元素元数据（tag, type, text, name, placeholder 等）。
3. **`AriaSnapshotReader`（ARIA 模式）**：
   - 移除旧版基于 JavaScript 递归遍历 DOM 并手动注入属性的全部私有逻辑；
   - 调用 Playwright 原生方法：`await page.locator(':root').aria_snapshot(mode='ai')`；
   - 官方输出的 YAML 节点自动带有 `[ref=e1]`、`[ref=e2]` 等标识；
   - 快照提取时通过轻量正则表达式提取该 YAML 中出现的所有 ref 标识字符串（如 `e1`），并登记至 `ctx.ref_map[ref_str]`，确保存在性校验与定位协同；
   - 在 `InteractHandler` 中，若定位时匹配到以 `e` 开头或官方格式的 Ref ID，通过 `page.locator(f"aria-ref={ref}")` 执行原生定位，否则回退到 `page.locator(f'[data-astr-ref="{ref}"]')`。

### 5.2 密码全链路去敏流水线 (Password Masking Pipeline)
1. **密码类型探测**：
   - `InteractHandler.fill_form` 中，先根据 `ctx.ref_map.get(ref)` 检查 `type == 'password'`；
   - 若元数据未标记（如 ARIA 模式），则通过当前 Locator 快速探测 `await locator.get_attribute("type") == "password"`；
2. **脱敏流向控制**：
   - 若探测为密码且系统配置 `mask_password_inputs=True`：
     - **审计日志输入参数**：`{"ref": ref, "text": "******"}`；
     - **大模型返回消息**：提示文本使用 `已成功在密码输入框 [{ref}] 填入内容`，避免回显真实输入值；
     - **系统错误日志**：发生异常时异常信息及 traceback 过滤或脱敏密码文本。

### 5.3 `BaseActionHandler` 模板方法设计
在 `tools/handlers/base_handler.py` 中实现基类：
```python
class BaseActionHandler:
    def __init__(self, context_mgr, security_mgr, audit_logger, mask_password_inputs=True):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger
        self.mask_password_inputs = mask_password_inputs

    async def execute_action(
        self,
        session_id: str,
        sender_id: str,
        action_name: str,
        target_resource: str,
        action_coro_fn: Callable[[BrowserSessionContext, Page], Awaitable[str]],
        input_args: dict[str, Any],
        required_permission: str,
        session_name: str = "",
        sender_name: str = "",
        wait_stabilize: bool = False,
    ) -> str:
        # 1. 寻址并校验上下文
        # 2. 检查 SecurityManager 权限 (失败记审计并返回拒绝提示)
        # 3. 若 wait_stabilize=True，调用页面稳定等待
        # 4. 执行业务协程 action_coro_fn(ctx, page)
        # 5. 处理密码脱敏参数
        # 6. 成功落库审计并返回结果
        # 7. 捕获未预期异常，清洗 Playwright 报错，记录调用栈，落库错误审计并返回简洁错误
```
`PageHandler`、`InteractHandler`、`MediaHandler` 均继承自 `BaseActionHandler`，内部方法如 `click`、`fill_form` 仅需专注于核心 Locator 调用，大幅缩减代码量并消除重复。

### 5.4 页面稳定等待与四重快照失效机制
1. **稳定等待封装 (`wait_page_stable`)**：
   - 先等待 `domcontentloaded`（超时 10s）；
   - 随后执行带有熔断保护的 `page.wait_for_load_state("networkidle", timeout=1500)`；
   - 若在 1.5s 内未完全达到网络空闲（常见于 WebSocket、音视频流或长轮询请求），捕获超时异常并平滑降级放行，保证操作不卡死。
2. **四重快照自动失效**：
   - **路由事件监听**：在上下文初始化及新标签页挂载时，监听 `page.on("framenavigated", lambda frame: on_frame_nav(frame))`，当且仅当主 Frame 发生导航变更时，将 `ctx.is_snapshot_dirty = True`、`ctx.current_snapshot = None`、`ctx.ref_map = {}`；
   - **URL 状态比对**：在 `read_page` 读取快照前，比较 `page.url` 与 `ctx.current_snapshot.url`，若发生偏离立即标记为脏并清空缓存；
   - **交互脏标记**：在 `InteractHandler` 中执行任何状态变更动作（`click`、`fill`、`select`、`press_key` 等）后，置 `ctx.is_snapshot_dirty = True`；
   - **TTL 衰减**：`PageSnapshot` 记录 `timestamp`，若当前时间距离快照创建时间超过 60 秒，自动失效并重新提取。

### 5.5 上下文创建异常回滚机制
在 `core/context_manager.py` 的 `_create_new_context` 中应用严密的资源生命周期保护：
```python
browser_ctx = None
try:
    browser_ctx = await self.adapter.create_context(storage_state_path=state_to_inject)
    # 挂载路由守卫
    # 创建首个 page
    # 挂载事件监听
    # 构造 BrowserSessionContext
    return ctx
except Exception as e:
    if browser_ctx is not None:
        try:
            await browser_ctx.close()
        except Exception:
            pass
    raise e
```
确保无论在路由绑定、新建页面还是监听器注册阶段发生任何异常，新申请的底层 `BrowserContext` 均会被及时销毁，杜绝孤儿进程与内存泄漏。

### 5.6 死代码清理范围
- 删除 `core/page_extractor.py`（528 行）；
- 删除 `tests/test_page_extractor.py`（216 行）；
- 清理 `main.py` 与 `PageHandler` 中对 `PageExtractor` 的引用与别名参数；
- 清理 `tools/handlers/page_handler.py` 中旧版向后兼容的 `search_page` 遗留接口。

### 5.7 平台合规：统一 Logger 导入治理
- 违规现状：`tools/tools.py` 与各 Handlers 中存在 `try: from astrbot.api import logger except ImportError: import logging` 的回退逻辑，不符合发布审核要求。
- 治理方案：全面移除 `import logging`，强制统一为 `from astrbot.api import logger`。在离线单测环境下，由测试初始化入口（或各单测模块的头部）统一向 `sys.modules["astrbot"]` 与 `sys.modules["astrbot.api"]` 注入 Mock Logger，兼顾平台合规与单测独立运行。

### 5.8 平台合规：持久化专属路径迁移
- 违规现状：当前持久化路径散落于 `data/audit.db`、`data/downloads`、`data/screenshots`、`data/audit_screenshots`。
- 治理方案：将所有持久化默认根路径迁移至 `data/plugin_data/astrbot_plugin_playwright_tools/`：
  - 审计数据库：`data/plugin_data/astrbot_plugin_playwright_tools/audit.db`
  - 下载保存目录：`data/plugin_data/astrbot_plugin_playwright_tools/downloads`
  - 截图保存目录：`data/plugin_data/astrbot_plugin_playwright_tools/screenshots`
  - 审计截图保存目录：`data/plugin_data/astrbot_plugin_playwright_tools/audit_screenshots`
- 同步更新：更新 `_conf_schema.json` 中的各路径默认值、`main.py` 的配置回退默认值以及 `MediaHandler` 的初始化默认参数。

---

## 6. 构建与落地指引 (What's Left to the Builder)

由构建执行者负责的技术细节包括：
1. **单测套件重构与覆盖**：
   - 移除已删除文件的测试用例；
   - 为 `BaseActionHandler` 编写涵盖鉴权拦截、脱敏、异常包装及正常执行的单元测试；
   - 调整针对 `interact_handler`、`page_handler`、`media_handler` 的已有单测，适配字符串 Ref ID 与新签名；
   - 编写针对 Context 失败资源清理及快照 4 重失效机制的单元测试。
2. **Schema 与 SKILL 同步**：
   - 更新 `tools/schemas.py` 内部 `ref` 字段的 JSON Schema 为 `type: string`；
   - 更新 `skills/playwright-tool/SKILL.md`，明确 Ref ID 为字符串形式（如 `"1"`、`"e1"`），保持与大模型提示词高度一致。
