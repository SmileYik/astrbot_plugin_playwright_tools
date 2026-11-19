# 插件设计文档：astrbot_plugin_playwright_tools (v2 重构与增强)

## 1. 目标与背景 (Intent & The Why)

本插件旨在为 `AstrBot` 提供一套基于 `Playwright`（首选 `Camoufox` 反指纹引擎）的高性能、安全可控的浏览器自动化工具。
本次重构针对大模型交互效率、工具集收敛、操作能力补齐与超时保护进行全面升级：
1. **类型化工具注册**：由原先的方法装饰器注册重构为继承 `FunctionTool` 的类型化面向对象注册（`context.add_llm_tools`）。
2. **统一命名与大工具聚合**：采用 `pw_` 统一前缀，将原先 10 余个分散的原子工具收敛聚合成 3 个复合大工具（`pw_page`、`pw_interact`、`pw_media`），大幅节省模型 Token 并降低多工具选择歧义。
3. **补齐关键交互**：新增鼠标悬停（hover）、元素聚焦/失焦（focus/blur）、元素拖拽（drag）、键盘按键（press_key）。
4. **截图双重熔断**：区分视口截图与长截图，支持最大像素与时间双重熔断截断，防止长页面卡死渲染。
5. **单工具执行超时保护**：全局配置工具执行超时，避免网络挂起或异常阻塞会话。
6. **提示词动态注入**：通过 `@filter.on_llm_request()` 支持可配置的系统提示词注入。
7. **长内容关键词检索**：在长页面分页基础上，新增基于关键词的局部高亮检索能力。
8. **完善项目文档**：按照 [AGENT.md](../../../AGENT.md) 补齐 `docs/` 项目文档。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals & Anti-Goals)

### 2.1 目标 (Goals)
1. **聚合与类型化**：暴露 `pw_page`, `pw_interact`, `pw_media` 3 个强类型工具，参数采用结构化 JSON Schema 定义。
2. **健壮性与超时兜底**：每个工具执行均受 `tool_execution_timeout_seconds` 保护；长截图受最大高度像素与时间熔断保护。
3. **交互完整性**：支持 Web 现代应用的全部主流操作（点击、输入、选择、滚动、悬停、拖拽、聚焦/失焦、按键、弹窗预设）。
4. **低 Token 与精准定位**：依赖 `data-astr-ref` DOM 属性直接定位，结合分页与关键字定位。
5. **安全与审计无缝保留**：继承原有的域名通配符白名单、顶层导航路由守卫、多租户个人/会话上下文隔离与 SQLite 审计。

### 2.2 非目标 (Non-Goals)
1. 不搞复杂的多进程浏览器集群或远程 CDP 代理连接。
2. 不开发特定网站的逆向爬虫或绕过验证码逻辑。

### 2.3 反目标 (Anti-Goals)
1. 严禁暴露未过滤的原始 HTML。
2. 严禁越权向普通用户注入管理员 Cookie 或泄露凭据。
3. 严禁因单个网页死锁导致 AstrBot 事件循环永久挂起。

---

## 3. 技术约束与规范 (Constraints)
1. **面向对象工具注册**：必须符合 AstrBot `>= v4.5.1` 的 `FunctionTool` 子类规范与 `context.add_llm_tools(...)`。
2. **文档风格**：严格依照 `AGENT.md`，文档与注释凝练简洁，不啰嗦。
3. **提示词注入规范**：遵循 AstrBot 官方文档推荐，通过 `@filter.on_llm_request()` 挂载，配置为空串时不注入。
4. **版本同步**：`metadata.yaml` 与 `main.py` 严格保持版本与描述同步。

---

## 4. 架构备选方案评估 (Approaches)

### 备选方案 1：`FunctionTool` 门面分发器 + 模块化 Handlers —— **[已选定]**
- **结构划分**：
  - `tools/handlers/`：分别负责页面导航（`page_handler.py`）、DOM 交互（`interact_handler.py`）、媒体与下载（`media_handler.py`）。
  - `tools/schemas.py`：集中维护 3 个大工具的 JSON Schema 定义。
  - `tools/tools.py`：实现 `PwPageTool`、`PwInteractTool`、`PwMediaTool`，统一包裹超时控制、鉴权与审计记录。
  - `main.py`：注册工具实例与系统提示词钩子。
- **权衡**：模块职责分明，易于独立单元测试，代码清晰符合极简原则。

### 备选方案 2：大单体工具模块（Monolithic Tools） —— **[已放弃]**
- **权衡**：所有参数、分发与底层 Playwright 调用揉在单一文件中，迅速超过 1000 行，不易维护。

### 备选方案 3：动态元编程工厂（Dynamic Metaclass Factory） —— **[已放弃]**
- **权衡**：过度抽象，增加调用栈与排查调试成本，违背简单原则。

---

## 5. 详细系统设计 (Detailed System Design)

### 5.1 目录结构
```text
astrbot_plugin_playwright_tools/
├── adapts/
│   ├── base.py                 # BrowserAdapter 抽象基类
│   └── camoufox_adapter.py     # Camoufox 驱动实现
├── core/
│   ├── context_manager.py      # 多租户上下文管理与导航守卫挂载
│   ├── security_manager.py     # 域名通配符、行为权限判定
│   ├── page_extractor.py       # DOM 精简、Ref ID 映射、分页与关键词检索
│   └── audit_logger.py         # SQLite 异步审计记账与过期清理
├── tools/
│   ├── handlers/
│   │   ├── page_handler.py     # open, read, search, switch_tab, dialog, close
│   │   ├── interact_handler.py # click, fill, select, hover, focus, blur, drag, press, scroll
│   │   └── media_handler.py    # screenshot_viewport, screenshot_full, download
│   ├── schemas.py              # PwPage, PwInteract, PwMedia 参数 JSON Schema
│   └── tools.py                # PwPageTool, PwInteractTool, PwMediaTool (FunctionTool)
├── docs/
│   ├── README.md               # 插件详细中文使用文档
│   ├── ARCHITECTURE.md         # 架构与扩展说明
│   └── superpowers/...         # 计划与规格设计
├── _conf_schema.json           # WebUI 配置项
├── main.py                     # 插件入口、指令与 FunctionTool 注册
├── metadata.yaml               # 插件元信息
└── AGENT.md
```

### 5.2 三大复合工具规范 (Tools Specification)

#### 1. `pw_page` (页面控制与视图)
- **描述**：管理浏览器页面的打开、内容读取、关键字搜索、标签页切换、弹窗响应与关闭。
- **参数 Schema**：
  - `action` (string, 必须): `["open", "read", "search", "switch_tab", "dialog", "close"]`
  - `url` (string, 可选): 网页地址 (action=open)
  - `page` (integer, 可选): 页码编号 (action=read)
  - `keyword` (string, 可选): 页面检索关键字 (action=search)
  - `tab_index` (integer, 可选): 目标标签页序号 (action=switch_tab)
  - `dialog_action` (string, 可选): 弹窗响应策略 `'accept'` 或 `'dismiss'` (action=dialog)
  - `prompt_text` (string, 可选): 弹窗文本输入 (action=dialog)

#### 2. `pw_interact` (DOM 元素与键鼠交互)
- **描述**：对页面元素进行点击、输入、选择、鼠标悬停、聚焦/失焦、拖拽、键盘按键及滚动。
- **参数 Schema**：
  - `action` (string, 必须): `["click", "fill", "select", "hover", "focus", "blur", "drag", "press_key", "scroll"]`
  - `ref` (integer, 可选): 目标元素 Ref ID 编号
  - `text` (string, 可选): 输入文本内容 (action=fill)
  - `value` (string, 可选): 下拉选择值 (action=select)
  - `target_ref` (integer, 可选): 拖拽目标元素 Ref ID (action=drag)
  - `key` (string, 可选): 键盘按键名称如 'Enter', 'Escape', 'Tab' (action=press_key)
  - `direction` (string, 可选): 滚动方向 `'down'` 或 `'up'` (action=scroll)
  - `amount` (integer, 可选): 滚动像素数 (action=scroll)

#### 3. `pw_media` (视觉与下载交付)
- **描述**：执行当前视口截图、长截图或下载文件。
- **参数 Schema**：
  - `action` (string, 必须): `["screenshot_viewport", "screenshot_full", "download"]`
  - `target` (string, 可选): 交付目标 `'chat'` (发送至聊天) 或 `'ai'` (返回 base64 给大模型)
  - `ref` (integer, 可选): 目标下载链接 Ref ID (action=download)

### 5.3 新增核心机制

1. **关键词快速查询 (Search)**：
   - 在 `PageExtractor` 中新增 `search_snapshot(keyword: str) -> str`。
   - 过滤包含关键词的文本块与带 `data-astr-ref` 的可操作项，高亮输出匹配上下文，免去大模型翻页负担。
2. **长截图双重熔断与视口截图**：
   - 视口截图：`page.screenshot(full_page=False)`。
   - 长截图：`page.screenshot(full_page=True)`。
   - 熔断机制：在截图前读取 `document.body.scrollHeight`。若高度超过 `screenshot_max_height_px`（默认 8000 像素），强制设置视口或裁剪截取前 8000 像素；若截图耗时超过 `screenshot_timeout_seconds`（默认 15s），自动超时回退为当前视口截图并输出截断提示。
3. **单工具执行全局超时保护**：
   - 每个 Tool 在 `call()` 内部均使用 `asyncio.wait_for(..., timeout=tool_timeout)` 包裹。
   - 超时后立即终止当前动作并返回：`"操作超时：执行超过 {timeout} 秒限制，已强制终止。"`。
4. **提示词注入配置**：
   - 配置项 `system_prompt_injection`（默认空字符串）。
   - 在 `main.py` 挂载 `@filter.on_llm_request()`；当配置非空时，将该提示词安全追加至 `req.system_prompt`。

### 5.4 配置 Schema 扩展 (`_conf_schema.json`)
新增/调整项：
- `tool_execution_timeout_seconds` (int, default: 30)
- `screenshot_max_height_px` (int, default: 8000)
- `screenshot_timeout_seconds` (int, default: 15)
- `system_prompt_injection` (text, default: "")

---

## 6. 留给构建者的实现细节 (Left to the Builder)
1. 针对 `hover`、`focus`、`blur`、`drag`、`press_key` 的 JavaScript 降级容错实现。
2. `docs/` 下 `README.md` 与 `ARCHITECTURE.md` 的凝练编写。
3. 单元测试全量迁移与扩充（覆盖 3 个新工具的所有 action 分支）。
