# 页面提取策略模式、流式分页工具抽象与管理控制台增强设计规范

## 1. 概述与背景 (Intent & Why)

当前 `astrbot_plugin_playwright_tools` 插件在实际使用与控制台交互过程中发现了若干关键架构与体验痛点：
1. **生命周期视图无法展示活跃会话与日志 (Problem 1)**：
   - 前后端路由约定脱节：后端注册 `/{plugin_name}/lifecycle/active`，前端请求 `lifecycle/contexts`，导致 404；
   - 生命周期事件过滤 Bug：前端默认传参 `event_type=all`，后端在 SQL 组装时直接拼接 `WHERE event_type = 'all'`，导致历史审计事件匹配结果永远为空。
2. **Web API 响应双层嵌套与导出失效 (Problem 2)**：
   - 响应格式过度包裹：后端使用 `json_response({"code": 0, "data": {...}})`，叠加上 AstrBot 框架的封装以及前端解包逻辑，产生了 `{code: 0, data: {code: 0, data: ...}}` 的双层包裹；
   - 审计日志导出未触发文件保存：Bridge 拆包后返回数据不含外层 `code`，前端判定失败直接返回空字符串，且在 iframe 内直接模拟 `<a download>` 存在沙箱限制，未利用 AstrBot 宿主原生的 `bridge.download` 通道。
3. **白名单单域名限制 (Additional Problem)**：
   - 当前白名单规则中 `domain` 仅支持单个字符串，无法为同一组业务域名（如 `*.github.com` 与 `github.com`）批量配置相同权限。
4. **正文提取内容缺失与交互控件割裂 (Problem 3)**：
   - 目前正文提取与控件提取分为两个独立 Target：正文只提纯文本（丢失嵌入图片，且忽略按钮与输入框），控件列表仅有一连串失去上下文的 `[按钮] "点击下载"`；大模型在面对复杂的卡片式/网格式页面（如 GTNH 资源站、各类下载站、表单站）时，无法判断哪个按钮属于哪个章节或软件版本；
   - 用户需要可配置的提取机制，并希望将“长页面分页阅读与信息提炼”从杂糅的 `pw_page` 中解耦，抽象出独立的分页阅读工具，根据所选策略动态提供适配的阅读与分页实现。

本设计旨在彻底理顺 API 数据契约、修复生命周期与导出功能、升级白名单配置为多域名集合，并采用策略模式将长页面流式提炼与分页重构为专属的 `pw_read` 工具。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **API 数据契约单一化与一致性**：
   - 严格以后台接口定义为准，前端对齐后端路由（`/lifecycle/active` 等），后端杜绝注册冗余路由；
   - 彻底废除双层包裹，全量 API 响应扁平化为一层直出业务数据（如 `{"items": [...], "total": 10}`）；
   - 审计导出支持 AstrBot 原生 `bridge.download` 通道，提供标准文件下载。
2. **修复生命周期事件检索**：
   - 后端 `query_lifecycle_logs` 支持通配过滤，当 `event_type` 为 `all`、空字符串或未指定时忽略该条件。
3. **支持白名单多域名集合**：
   - 配置项从 `domain: string` 升级为 `domains: list[str]`，允许一个权限规则绑定一组域名/通配符；
   - 后端 `SecurityManager` 适配多域名集合匹配，并保持对旧配置单个 `domain` 的向下兼容。
4. **页面提取策略模式、密码安全开关与专属分页阅读工具**：
   - 配置文件增加 `content_extraction_mode`（`inline_markdown` vs `aria_snapshot`）；
   - 配置文件增加 `mask_password_inputs: bool` 开关，控制表单内 `type="password"` 组件的明文显示或星号脱敏；
   - 配置文件增加 `page_chunk_char_limit: int`（带滑块 500~8000），允许用户自定义长页面流式切分的单页字符/Token 预算；
   - 从 `pw_page` 中彻底剥离正文阅读逻辑，`pw_page` 精简为专注于页面生命周期控制（open, switch_tab, dialog, close）；
   - 独立抽象并注册专门的流式分页阅读工具 `pw_read`，根据配置分别由 `InlineMarkdownReader`（语义块分页，内联控件与图片）与 `AriaSnapshotReader`（区域树分页，祖先路径回填）驱动。

### 非目标 (Non-Goals)
- 不改变底层浏览器适配器架构（Playwright / Camoufox）的生命周期管理机制。
- 不修改底层的动作交互工具（`pw_interact`）的操作语意与参数规范。
- 不引入外部庞大的第三方 HTML 清洗重量级库，保持纯 Python 与轻量 JavaScript 注入执行。

### 反目标 (Anti-Goals)
- 严禁在单一函数中通过大量 `if extraction_mode == 'xxx'` 堆砌分支逻辑，必须通过面向对象策略模式彻底解耦。
- 严禁在字符截断中硬切断 Markdown 语法标记或 ARIA 节点（如截断在 `[Ref:` 中途）。
- 严禁在后台制造功能相同但路径不同的“影子路由”。

---

## 3. 约束条件 (Constraints)
- **AstrBot 插件兼容性**：必须严格符合 AstrBot Web API 注册与 FunctionTool 规范。
- **长文本上下文经济性**：单页提炼内容 Token 消耗需可控（默认约 1500~2000 字符/页），具备明确的分页指示语指导 AI 继续翻页或操作。
- **Ref ID 映射连续性**：无论是 Markdown 模式还是 ARIA 模式，页面内可交互元素均必须分配连续且唯一的全局 `ref` 编号，无缝与 `pw_interact` 联动。

---

## 4. 技术方案与技术决策 (Approaches & Trade-offs)

### 4.1 API 契约与数据流
- **决策**：完全废弃 `{code: 0, data: {...}}`，后端直接使用 `json_response(data_dict)` 返回单层数据字典；错误时统一使用 `error_response(message)`。
- **权衡**：放弃传统的某些 RPC 式 `code` 包装，换取与 AstrBot Bridge 及现代 RESTful 前端规范的零成本天然贴合。

### 4.2 工具体系重构
- **原设计**：`pw_page` 包含 `open`, `read`, `search`, `switch_tab`, `dialog`, `close`，职责过载且分页逻辑与页面生命周期严重耦合。
- **新设计**：
  - `pw_page`：仅保留 `open`, `switch_tab`, `dialog`, `close`。当 `open` 成功后返回简洁概要：“页面已加载，请调用 `pw_read` 阅读正文或查看组件”。
  - `pw_read`：专属长内容流式分页阅读工具（参数：`page: int = 1`, `keyword: str = ""`）。在插件启动时，根据配置的策略动态注册其说明文档与底层实现。
  - `pw_interact` & `pw_media`：保持不变。

---

## 5. 详细架构与技术规格 (Detailed Design)

### 5.1 生命周期 API 与前端对齐 (Problem 1)

1. **路由规范**：
   - 保持后端 `LifecycleApiHandler` 既有路由：
     - `/{plugin_name}/lifecycle/active` (GET)：获取活跃上下文明细
     - `/{plugin_name}/lifecycle/logs` (GET)：获取生命周期审计事件
     - `/{plugin_name}/lifecycle/screenshot` (POST)：手动截图
     - `/{plugin_name}/lifecycle/kill` (POST)：强制销毁上下文
   - 前端 `web-src/src/api/lifecycle.ts` 修正：
     将 `lifecycle/contexts` 改为 `lifecycle/active`，彻底解决 404 错误。
2. **SQL 条件过滤修正** (`core/audit_logger.py`)：
   ```python
   # 当 event_type 为 "all"、空字符串或 None 时，不追加过滤条件
   if event_type and event_type.strip() and event_type.strip().lower() != "all":
       conditions.append("event_type = ?")
       params.append(event_type.strip())
   ```

### 5.2 API 响应单层扁平化与导出下载修复 (Problem 2)

1. **后端 API 单层数据输出**：
   - `api_audit_logs` 返回 `json_response({"items": items, "total": total, "page": page, "page_size": page_size})`
   - `api_audit_stats` 返回 `json_response(stats_dict)`
   - `api_active_contexts` 返回 `json_response({"items": active_items, "total": len(active_items)})`
   - `api_lifecycle_logs` 返回 `json_response({"items": logs, "total": total, "page": page, "page_size": page_size})`
   - `api_audit_export` 返回 `json_response({"content": content, "format": fmt})`，或者直接返回文本流附件。
2. **前端数据接收与导出修复**：
   - `web-src/src/types.ts`：更新泛型响应结构，支持单层对象；
   - `web-src/src/api/audit.ts`：
     - 增加 `bridge.download` 支持：检测 `window.AstrBotPluginPage?.download`，优先调用原生下载接口；
     - `exportAuditLogs` 容错：直接提取返回的文本内容，兼容单层返回；
   - `web-src/src/views/AuditView.tsx`：收到内容后若降级至 Blob 下载，以 UTF-8 编码安全生成并点击下载。

### 5.3 白名单多域名集合改造 (Additional Problem)

1. **配置 Schema 调整** (`_conf_schema.json`)：
   ```json
   "whitelist_rules": {
     "type": "template_list",
     "description": "网站白名单",
     "hint": "添加非管理员允许访问的网站通配规则及对应权限",
     "default": [],
     "templates": {
       "rule": {
         "name": "白名单规则",
         "display_item": "domains",
         "items": {
           "domains": {
             "type": "list",
             "description": "目标域名/通配符列表",
             "hint": "输入域名或通配符（如 *.github.com、github.com），本规则内的所有操作权限均应用于该域名集合",
             "default": []
           },
           "allowed_actions": {
             "type": "list",
             "description": "允许的操作行为",
             "default": ["read", "screenshot"],
             "options": ["read", "click", "fill", "scroll", "screenshot", "download"],
             "labels": ["读取正文 (read)", "点击交互 (click)", "输入表单 (fill)", "页面滚动 (scroll)", "页面截图 (screenshot)", "下载文件 (download)"]
           }
         }
       }
     }
   }
   ```
2. **安全管理器实现** (`core/security_manager.py`)：
   ```python
   def _match_rule(self, host: str, rule: dict) -> bool:
       domains = rule.get("domains")
       if not domains:
           # 兼容旧配置中的单个 domain 字段
           old_dom = rule.get("domain")
           domains = [old_dom] if old_dom else []
       elif isinstance(domains, str):
           domains = [domains]
       return any(self._is_domain_match(host, str(d)) for d in domains if str(d).strip())
   ```

### 5.4 配置增强：密码脱敏开关与分页字符预算

1. **配置 Schema 调整** (`_conf_schema.json`)：
   - **安全与隐私配置**（`security` 分组内追加）：
     ```json
     "mask_password_inputs": {
       "type": "bool",
       "description": "脱敏密码输入框",
       "hint": "开启后，页面中 type='password' 的表单组件内容将被脱敏为 ******，防止敏感密码泄露给大模型；关闭后将输出实际明文内容",
       "default": true
     }
     ```
   - **运行时与阅读配置**（`runtime` 分组内追加）：
     ```json
     "content_extraction_mode": {
       "type": "string",
       "description": "页面正文提炼模式",
       "hint": "选择大模型阅读网页时使用的正文提取与结构化策略",
       "default": "inline_markdown",
       "options": ["inline_markdown", "aria_snapshot"],
       "labels": [
         "内联交互 Markdown (Inline Markdown) [推荐]",
         "无障碍语义树快照 (ARIA Snapshot)"
       ],
       "subtitles": [
         "将正文排版、嵌入图片与带 Ref 编号的可交互元素内联融合成一篇结构化文档，所见即所得",
         "基于浏览器原生 Accessibility Tree 生成角色层级树，结构严密但呈树状层级"
       ]
     },
     "page_chunk_char_limit": {
       "type": "int",
       "description": "分页字符预算",
       "hint": "单页正文提炼的最大字符预算（建议 1000 ~ 4000），超过此预算将在保持语义块完整性的前提下自动切分至下一页",
       "default": 2000,
       "slider": {
         "min": 500,
         "max": 8000,
         "step": 100
       }
     }
     ```

### 5.5 页面提取策略模式与独立流式分页阅读工具 `pw_read` (Problem 3)

#### 5.5.1 策略基类抽象 (`core/readers/base.py`)
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class PageSnapshot:
    title: str
    url: str
    raw_content: Any
    ref_map: dict[int, dict]
    total_pages: int
    chunks: list[str]

class BasePageReader(ABC):
    """网页正文提取与流式分页抽象策略基类。"""

    def __init__(self, chunk_char_limit: int = 2000, mask_passwords: bool = True):
        self.chunk_char_limit = chunk_char_limit
        self.mask_passwords = mask_passwords

    @abstractmethod
    async def extract_snapshot(self, page: Any, url: str) -> PageSnapshot:
        """从 Playwright 页面中提取全量结构化快照并建立 Ref ID 映射。"""
        pass

    @abstractmethod
    def format_chunk(self, snapshot: PageSnapshot, page_index: int) -> str:
        """格式化输出指定页码的分页切片文本，附带清晰的翻页指示。"""
        pass

    @abstractmethod
    def search(self, snapshot: PageSnapshot, keyword: str) -> str:
        """在快照内容中检索关键词并输出包含上下文与相关 Ref 的片段。"""
        pass

    @abstractmethod
    def get_tool_metadata(self) -> dict[str, Any]:
        """返回适配当前策略的 FunctionTool 名称、描述及参数 Schema。"""
        pass
```

#### 5.5.2 策略实现 A：`InlineMarkdownReader` (`core/readers/markdown_reader.py`)
- **注入提取逻辑**：
  - 单遍阅读顺序深度遍历 DOM；
  - 遇到标题提取为 `# ## ###`，段落提取为文本，列表提取为 `- `，表格提取为 Markdown 表格；
  - 遇到 `<img>` 提取为 `![alt](src)`；
  - 遇到可交互元素（button, a, input, select, textarea, [role=button]）即时嵌入上下文，生成 `[Ref: X] [按钮: 文本]` 或 `[Ref: X] [链接: 文本]`，并为其绑定唯一自增 `Ref ID`；
  - **密码框脱敏判定**：检查 `input[type="password"]`，若 `mask_passwords == True`，则其渲染形式为 `[Ref: X] [输入框 (type="password", value="******")]`；若为 False 则如实输出其明文 value；
  - 生成 `list[SemanticBlock]`（标题块、段落块、列表块、卡片块）。
- **分页模型**：
  - 累加 Block 长度至配置的 `self.chunk_char_limit`，仅在 Block 边界处切断；
  - 切断处若处在某级标题下，下页首部追加上下文提示行：`提示: 接上页内容（当前位置: 父章节标题）`；
  - 尾部附带明确状态：`[分页: 1/N，共 N 页。若需交互调用 pw_interact(ref=...)，翻页调用 pw_read(page=2)]`。

#### 5.5.3 策略实现 B：`AriaSnapshotReader` (`core/readers/aria_reader.py`)
- **提取与定位绑定机制 (架构决议)**：
  - 为确保 `pw_interact` 底层 `page.locator('[data-astr-ref="{ref}"]')` 无需任何侵入性改动，`AriaSnapshotReader` 采用**客户端 DOM 语义映射器 (Client-side ARIA DOM Walker)**：
    1. 在浏览器端通过 JavaScript 递归计算节点计算属性（Computed Role, Accessible Name, Level, State）；
    2. 遍历过程中，对所有可交互角色节点（button, link, textbox, combobox, checkbox 等）直接在真实 DOM 节点上注入 `data-astr-ref="{ref}"` 自增属性；
    3. **密码框处理**：对于 `textbox` 且底层为 password 输入框的组件，当 `mask_passwords == True` 时其 value 或 text 均替换为 `******`；
    4. 同步生成与 Playwright 原生 ARIA Snapshot 兼容的 YAML 格式层级树文本，并在节点行后标注 `[ref=X]`。
- **分页模型**：
  - 以 Landmark / Region / Section 为顶层分块单元；
  - 在分块行数或字符数达到 `self.chunk_char_limit` 预算阈值时切断，并在下一页首部回填祖先树桩路径（Ancestor Breadcrumbs），确保每个分页都是自闭合、无孤儿节点的层级树；
  - 尾部附带树遍历进度与翻页提示。

#### 5.5.4 工具解耦、快照缓存与流式阅读 (`tools/tools.py`)
1. **快照生命周期与缓存更新策略 (架构决议)**：
   - **快照缓存绑定在会话上下文 (ContextItem) 中**，包含：`current_snapshot: PageSnapshot | None`、`snapshot_url: str` 与 `is_snapshot_dirty: bool`。
   - **脏标记失效时机**：
     - 当调用 `pw_page(action='open')` 或 `pw_page(action='switch_tab')` 时，清空旧快照并重置状态；
     - 当大模型通过 `pw_interact` 成功触发可能引起 DOM 变动的行为（如 click, fill, select, press_key）后，将当前上下文标记为 `is_snapshot_dirty = True`。
   - **按需懒提炼 (Lazy Extraction on Read)**：
     - `pw_read` 执行时，若检测到快照为空、或处于脏状态 (`is_snapshot_dirty == True`)、或页面 URL 发生变更、或入参 `refresh == True`，则重新执行当前策略的 `extract_snapshot` 并清除脏标记；
     - 若快照有效且无变更，直接返回指定 `page` 的切片缓存。这样既保证多页流式阅读（`page=1 -> page=2`）时 Ref 编号与分页切片的绝对稳定与毫秒级极速响应，又保证在交互发生后 AI 再次阅读时能自动感知最新页面状态。
2. **`pw_page` 精简**：
   - 动作：`open`, `switch_tab`, `dialog`, `close`。
   - `open_url` 执行成功后，仅返回导航成功简讯与引导：
     ```text
     页面已成功打开！
     页面标题: {title}
     页面地址: {url}
     [推荐操作: 请调用 pw_read(page=1) 流式阅读正文排版并获取可交互控件 Ref 编号]
     ```
3. **`pw_read` 独立注册**：
   - 接受参数：
     - `page: int = 1`：阅读指定切片分页；
     - `keyword: str = ""`：在全量快照中高亮检索并定位片段；
     - `refresh: bool = False`：强制跳过缓存重新抓取当前活动页面。
   - 工具描述由 Reader 的 `get_tool_metadata()` 动态生成，准确告知大模型当前是 Markdown 模式还是 ARIA 树模式，以及如何结合 `pw_interact` 操作 `ref`。

---

## 6. 开发者自裁事项 (What's Left to the Builder)
1. **语义块的细微 DOM 容错规则**：在特殊复杂网页中若某些非标准元素缺少语义标签，允许作为通用段落或内联元素降级处理。
2. **ARIA Snapshot 在低版本浏览器内核下的降级**：若运行环境不支持 `aria_snapshot`，内部优雅降级到 Accessibility 树遍历提取。
3. **前端样式微调**：在控制台中为单层数据渲染提供良好的空状态与加载状态显示。

---

## 7. 质量保证与测试策略
- **单元测试**：
  - 测试 `BasePageReader` 与两种具体 Reader 的提炼与分页逻辑，包括图文内联、元素不被中途腰斩测试；
  - 测试 `SecurityManager` 对 `domains: list[str]` 的通配匹配与旧 `domain` 兼容性；
  - 测试 `LifecycleApiHandler` 路由与 `all` 事件类型过滤；
  - 测试全量 API 返回的单层数据格式。
- **集成测试**：
  - 模拟大模型调用 `pw_page(action='open')` -> `pw_read(page=1)` -> `pw_read(page=2)` -> `pw_interact(action='click', ref=X)` 完整闭环链路。
