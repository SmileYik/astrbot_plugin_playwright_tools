# 网页阅读排版、独立分页检索与审计系统增强设计文档 (Design Doc)

## 1. 背景与意图 (Intent and Why)

当前插件在供大模型 (AI Agent) 实际调用过程中，暴露出多项直接影响使用效果与用户体验的痛点：
1. **正文破碎且与交互控件杂糅**：
   - 当前 `core/page_extractor.py` 的 JS 提取脚本仅抓取前 20 个文本节点且截断至 200 字符，并对每句文本机械地附加 `[文本]` 前缀，丧失了完整的文章段落与章节层级；
   - 正文与可交互元素被扁平拼接入单个字符串，在包含大量控件（如 Wiki 上百个超链接）的网页中，分页切片被控件吞没，AI 翻页（如 `page=2`）后看到的全部是控件编号列表，完全无法阅读文章正文；
   - 交互元素文本中残留换行符（如 `"搜索GTNH中文维基\nCtrl K"`），破坏了单行规范与视觉结构。
2. **底层异常堆栈污染上下文**：
   - 当交互发生超时或被拦截时（例如页面内存在 HTML5 `<dialog open>` 遮挡点击），Playwright 的 `TimeoutError` 字符串直接携带多达数十行的底层调用与重试 Call log，全数返回给大模型，严重浪费上下文 Token 并干扰模型判断。
3. **缺乏后续操作指引**：
   - 工具返回信息末尾缺少对 AI 的下一步操作建议（如剩余正文页数、建议切换至元素视图、或提示关闭遮挡弹窗）。
4. **审计系统输出缺失与前端分页失效**：
   - 审计日志当前未记录大模型接收到的真实工具输出文本，仅写入固定占位符（如 `"页面打开成功"`、`"读取第 1 页成功"`）；且未持久化截图；
   - 审计管理前端页面（WebUI）中，由于后端 API 仅通过 `req.query` 提取参数，但在 AstrBot 真实运行环境下请求包装为 `DashboardRequest`（参数位于 `.args` 或 `._request.query_params`），导致参数提取始终落入默认值 `page=1`，前端分页翻页与条件检索完全失效。

**重构核心意图**：
以提升大模型阅读网页与交互执行的流畅度为核心，彻底重构页面内容提炼排版、引入独立分页与检索能力（方案 A）、清洗底层异常并注入操作建议；同时全面重构审计记录机制（记录真实输出与截图、可配限制）并修复 WebUI 分页，无需兼容旧写法。

---

## 2. 目标、非目标与反目标 (Goals, Non-goals, Anti-goals)

### 目标 (Goals)
1. **结构化正文提炼与元素清洗**：
   - 正文提取以 Markdown 格式组织标题（`#`, `##`, `###`）、正文段落、列表与表格，剔除机械重复的 `[文本]` 前缀；
   - 对元素内部文本进行换行归一化，支持通过配置 `element_multiline_separator` 自定义分隔符，默认使用 `' | '`，保留语意停顿且消除粘连歧义。
2. **方案 A：支持 `target` 模式的分页与检索**：
   - 在 `pw_page(action='read')` 与 `action='search'` 中增加 `target: 'all' | 'text' | 'elements'` 参数（默认 `'all'`）；
   - `target='all'`：正文在上，控件在下，整体按需分页；
   - `target='text'`：仅加载正文，独立分页与检索，不受控件数量影响；
   - `target='elements'`：仅加载带 Ref ID 的控件列表，独立分页与检索；
   - 检索时针对目标域（正文/元素/全部）进行精准匹配。
3. **异常精简清洗与智能操作引导**：
   - 拦截 Playwright 异常，提取简明核心原因（如“元素被遮挡”、“操作超时”），剥离数十行冗长 Call log（保留完整日志至后台文件）；
   - 工具返回结果末尾追加明确的 `[推荐操作: ...]` 引导（翻页提示、查阅元素提示、关闭遮挡模态提示等）。
4. **全生命周期审计记录与截图持久化**：
   - 在配置中提供 `audit_max_output_chars`（整型，默认 `0` 表示不限长度），截取模型实际接收的完整输出；
   - 在配置中提供 `audit_save_screenshots`（布尔型，默认 `true`），仅针对 `pw_media` 截图工具生效，将生成的截图单独持久化至 `data/audit_screenshots/` 并记录路径索引；
   - 新增安全静态图片代理路由，支持 Web 审计端按需拉取截图；
   - 修复 `api/audit_api.py` 的请求参数探测，彻底恢复 Web 审计界面的分页与过滤功能；
   - 更新 Web 界面（`web-src`）支持长文本检视与截图渲染，并重新构建到 `views/audit/`。

### 非目标 (Non-goals)
- 不在常规非媒体操作（如 `click`, `fill`, `open`）中自动捕获视口截图，避免额外的执行延迟与存储激增。
- 本次重构不更换底层的 Playwright 原生 Locator 驱动与 Camoufox 适配器内核。
- 不引入复杂的第三方 HTML 排版解析库，正文 Markdown 转换由注入的精简 JS 遍历器完成。

### 反目标 (Anti-goals)
- **严禁向大模型输出底层 Call log 堆栈**：所有未处理异常必须精炼化。
- **严禁在 SQLite 审计库中内嵌大体积 Base64 图片**：截图必须独立落盘，数据库仅存路径索引。
- **严禁直接删除换行符**导致文本字面粘连（如“搜索GTNHCtrl K”）。

---

## 3. 方案对比与决策 (Approaches)

### 3.1 正文与控件阅读交互架构
- **方案 1 (选定)：统一 Action + `target` 参数过滤**
  - 在 `read` 和 `search` 中增加 `target: 'all' | 'text' | 'elements'`。
  - *权衡*：保持 API 接口极简紧凑，降低大模型选择工具的认知负荷；天然支持全量与分立两种阅读模式。
- **方案 2：分化为独立 Action** (`read_text`, `read_elements`, `search_text` 等)
  - *权衡*：Action 数量翻倍，Prompt 描述冗长，大模型易在简单概览任务中频繁纠结调用哪个 action。
  - *决策*：采纳 **方案 1**。

### 3.2 审计截图存储机制与范围
- **方案 1 (选定)：仅截图工具触发 + 文件落盘 + 路径引用**
  - 仅在调用 `pw_media` 截图时，将截图写入 `data/audit_screenshots/`，数据库仅存储文件相对路径。
  - *权衡*：SQLite 保持数十 KB/条的轻量体量，查询翻页毫秒级响应，避免高频截图导致单表暴增至数十 GB 甚至损坏；常规动作无额外截屏延迟。
- **方案 2：全量操作动作自动截图 + 数据库存 Base64**
  - *权衡*：每次动作增加 200~500ms 延迟，且单表体积急剧膨胀。
  - *决策*：采纳 **方案 1**。

### 3.3 审计记录架构与多租户快照
- **决策 1**：`PageExtractor` 保持纯无状态单例，所有提取产生的快照（正文、元素、映射表）均存放在会话的 `ManagedContext` 中，保障多租户并发安全。
- **决策 2**：`log_action` 在执行完成后统一传入模型接收到的真实返回值（`output_result`），并由 `AuditLogger` 根据 `audit_max_output_chars` 配置实施截断。

---

## 4. 详细模块设计与实现规范 (Detailed Specifications)

### 4.1 内容提炼引擎 (`core/page_extractor.py`)

#### 1. 结构化正文与控件分离提取 (JavaScript 注入端)
- **正文提炼**：
  - 遍历目标：`article, main, .mw-parser-output, section, [role="main"], body` 内的主要内容。
  - 节点转换映射：
    - `h1`: `# 标题`
    - `h2`: `## 标题`
    - `h3`, `h4`, `h5`: `### 标题`
    - `p`: 正文段落（保留完整段落文本，不再强行截断 200 字）
    - `ul, ol, li`: `- 列表项`
    - `blockquote`: `> 引用文本`
    - `table`: 提取简明表格行
  - 过滤掉纯导航、广告栏、版权 footer 及可交互控件本身。
- **控件提炼与换行归一化**：
  - 读取节点的 `innerText`；
  - 使用配置的 `element_multiline_separator`（默认 `' | '`）替换内部连续换行（`\r\n`, `\n`, `\r`），将多余空格折叠为单空格并 `trim()`；
  - 格式保持单行：`[{ref}] [{TAG}] "{text}"` 或 `[{ref}] [输入框] (placeholder="...")`。

#### 2. 快照数据模型与纯无状态设计 (`PageExtractor`)
```python
class PageExtractor:
    def __init__(self, max_page_char_length: int = 2500, multiline_separator: str = " | "):
        self.max_page_char_length = max_page_char_length
        self.multiline_separator = multiline_separator

    def extract_snapshot(
        self,
        page_title: str,
        url: str,
        raw_elements: list[dict],
        markdown_text: str = "",
    ) -> tuple[dict[str, str], dict[int, dict]]:
        """
        无状态提炼，返回快照字典与元素映射表：
        snapshot_data = {
            "title": page_title,
            "url": url,
            "markdown_text": markdown_text,
            "elements_text": elements_text,
            "full_text": full_text
        }
        """

    def format_page_chunk(
        self,
        snapshot_data: dict[str, str],
        target: str = "all",
        page_index: int = 1
    ) -> str:
        """根据目标域进行独立分页"""

    def search_snapshot(
        self,
        snapshot_data: dict[str, str],
        keyword: str,
        target: str = "all"
    ) -> str:
        """在目标域中检索匹配行"""
```

- **独立分页逻辑**：
  - `target='text'`：仅对 `markdown_text` 按行与字符限制分页，页脚提示：
    `--- [提示: 正文未完，剩余 X 页，可调用 pw_page(action='read', target='text', page=Y) 查看后续；或调用 target='elements' 查看操作元素] ---`
  - `target='elements'`：仅对 `elements_text` 按行与字符限制分页，页脚提示：
    `--- [提示: 元素未完，剩余 X 页，可调用 pw_page(action='read', target='elements', page=Y) 查看后续] ---`
  - `target='all'`：正文在上，控件在下，统一分页，页脚附带全局翻页引导。

---

### 4.2 异常信息清洗与智能引导规范

#### 1. 异常信息提取函数
在 `tools/handlers/interact_handler.py` 等模块中封装 `clean_playwright_error(e: Exception) -> str`：
- 检测 `TimeoutError` 与常见阻塞：
  - 若包含 `intercepts pointer events`：
    提炼并返回：`"操作超时 (10秒): 目标元素被页面弹层遮挡 (<{遮挡标签/类型}>)，建议先查阅并点击关闭按钮或关闭弹层。"`
  - 若包含 `waiting for locator` 且超时：
    提炼并返回：`"操作超时 (10秒): 未能定位到目标元素或元素不可见/不可点击，页面可能已刷新，请调用 pw_page(action='read') 重新获取最新元素。"`
- 彻底去除 Playwright 内部 `Call log:` 及后续所有重试堆栈，保证仅返回不超过 2 行的精准提示。完整日志依然使用 `logger.error` 记录到系统日志文件供管理员排查。

#### 2. 工具回复末尾操作建议 (`[推荐操作: ...]`)
- `pw_page:open`：成功打开后追加 `[推荐操作: 可调用 pw_page(action='read', target='text') 阅读正文，或 target='elements' 查看控件列表]`；
- `pw_page:read`：
  - 正文未完：提示 `pw_page(action='read', target='text', page=N+1)`；
  - 最后一页：提示 `正文已读完，若需交互可调用 target='elements' 或直接调用 pw_interact(action='click', ref=X)`；
- `pw_interact:click`：
  - 点击跳转或点击表单后，提示 `已执行点击。若页面发生跳转或内容刷新，可调用 pw_page(action='read') 查看最新视图`；
  - 点击被弹层拦截失败时，提示 `[推荐操作: 先调用 pw_page(action='read', target='elements') 寻找遮挡弹窗的关闭按钮或调用 pw_interact 点击关闭]`。

---

### 4.3 审计系统与配置增强 (`core/audit_logger.py`, `tools/tools.py`)

#### 1. 数据库结构定义与字段更新
`tool_audit_logs` 表结构保持轻量，字段如下：
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `timestamp`: TEXT (UTC 或本地时间)
- `session_id`, `session_name`, `context_key`, `sender_id`, `sender_name`: 多租户会话元数据
- `tool_name`: TEXT (如 `pw_page:read`, `pw_interact:click`)
- `url`: TEXT (操作时页面地址)
- `input_args`: TEXT (JSON 格式化入参)
- `output_result`: TEXT (大模型接收到的真实工具输出文本，受 `audit_max_output_chars` 限制)
- `screenshot_path`: TEXT (若为截图工具则记录相对路径，如 `data/audit_screenshots/shot_xxx.png`)
- `is_permitted`: INTEGER (1/0)
- `deny_reason`: TEXT
- `is_error`: INTEGER (1/0)
- `error_message`: TEXT (清洗后的简明错误)
- `execution_time_ms`: INTEGER (工具执行毫秒耗时)

#### 2. 配置项定义 (`_conf_schema.json` & `metadata.yaml`)
- `audit_max_output_chars`:
  - 类型：`integer`，默认值：`0`（0 代表不限制字符数）。
  - 描述：“审计日志中单条工具输出记录的最大字符上限，设为 0 表示不限制完整保存。”
- `audit_save_screenshots`:
  - 类型：`boolean`，默认值：`true`。
  - 描述：“是否在审计中将截图工具产生的截图文件单独持久化并关联记录。”
- `element_multiline_separator`:
  - 类型：`string`，默认值：`" | "`。
  - 描述：“页面可操作元素内部换行时的分隔替换文本，默认为 ' | '。”

#### 3. 真实输出与截图落地处理
- 当大模型调用 `pw_media(action='screenshot_viewport' | 'screenshot_full')` 且 `audit_save_screenshots=true` 时：
  - 图片数据落盘至 `data/audit_screenshots/shot_{timestamp}_{uuid}.png`；
  - 审计记录中的 `screenshot_path` 写入该相对路径；
  - 当模型同时指定 `target='ai'` 时，大模型接收 base64 文本，审计中的 `output_result` 记录提示文本 `[图片已持久化存储至 {screenshot_path}]`，避免庞大的 base64 字符占用数据库。

#### 4. Web API 请求参数多层探测修复与静态截图路由 (`api/audit_api.py`)
- **请求参数安全提取工具函数**：
```python
def extract_query_param(req: Any, key: str, default: Any = None) -> Any:
    if not req:
        return default
    # 1. PluginRequest.query (PluginMultiDict)
    if hasattr(req, "query") and hasattr(req.query, "get"):
        val = req.query.get(key)
        if val is not None:
            return val
    # 2. DashboardRequest.args (RequestArgs)
    if hasattr(req, "args") and hasattr(req.args, "get"):
        val = req.args.get(key)
        if val is not None:
            return val
    # 3. Starlette Request.query_params / _request.query_params
    query_params = getattr(req, "query_params", None) or getattr(getattr(req, "_request", None), "query_params", None)
    if query_params and hasattr(query_params, "get"):
        val = query_params.get(key)
        if val is not None:
            return val
    return default
```
- **新增安全截图文件接口**：
  - 路由：`GET /{plugin_name}/audit/screenshot`
  - 入参：`path` 或 `id`
  - 安全检查：严格校验路径必须以 `data/audit_screenshots/` 开头，杜绝任何 `..` 路径穿越；文件存在时使用 `FileResponse` 返回图片。

---

### 4.4 Web 管理端视觉优化 (`web-src/` & `views/audit/`)

1. **真实输出检视**：
   - 卡片与右侧抽屉直接展示真实的 `output_result`，支持语法高亮风格文本、一键复制、超长折叠。
2. **截图预览与弹窗**：
   - 当 `screenshot_path` 存在时，卡片内显示截图缩略图徽标，右侧抽屉内通过截图接口直接预览图片，点击可全屏查看大图。
3. **分页与查询对齐**：
   - 前端分页器联动后端多条件检索，支持每页条数切换（10/20/50/100）及上一页/下一页；
   - 修复前端离线模拟模式的代码，确保无 Bridge 时纯前端分页切片也能正常工作。
4. **编译发布**：
   - 修改源码后执行打包，产物直接同步覆盖输出至 `views/audit/`。

---

## 5. 留给构建者实现的内容 (What's Left to the Builder)

1. **JS 抽取脚本的文本选择器微调**：针对主流网站（Wiki, GitHub, 文档类站点）的 CSS 主容器类名做合理兼容（如 `.markdown-body`, `.content`, `article` 等）。
2. **Playwright 错误关键字正则微调**：根据实际交互报错日志完善常见的错误提炼正则映射表。
3. **前端样式微调**：截图图片加载占位骨架屏与暗色主题细节适配。
4. **单元测试集补全**：在 `tests/` 下补充针对新独立分页、换行清洗、多源参数提取与异常清洗的单元测试。
