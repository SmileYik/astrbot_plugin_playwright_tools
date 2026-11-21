# 页面提取策略模式、流式分页工具抽象与管理控制台增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构页面信息提取与浏览体系，抽象独立流式分页阅读工具 `pw_read` 并支持内联交互 Markdown 与 ARIA 树双策略；修复生命周期 404 与日志空查 Bug，扁平化 Web API 为单层结构并支持宿主原生文件下载；支持白名单多域名配置与密码脱敏开关。

**Architecture:** 采用策略模式构建 `BasePageReader` 抽象，分别实现语义块级切分的 `InlineMarkdownReader`（原位嵌入控件与图片）与带祖先回填的 `AriaSnapshotReader`（客户端 DOM 语义映射与 Ref 注入）；从 `pw_page` 中剥离正文阅读逻辑，独立注册动态适配的 `pw_read` 并依托 Context 脏标记实现稳定连续分页与按需刷新；修正前后端路由契约，全面推行单层字典响应。

**Tech Stack:** Python 3.12/3.13, Playwright, AstrBot Plugin API, React 18, TypeScript, Vite, SQLite3, unittest.

**Spec:** `docs/superpowers/specs/2026-11-21-page-reader-and-dashboard-enhancements-design.md`

## Global Constraints

- 严格遵循后台已注册的 Web API 路由路径，前端对齐后端（如 `/lifecycle/active`），后端绝不重复注册功能重叠的影子路由。
- 全量 Web API 响应去除 `{code: 0, data: {...}}` 双层嵌套，扁平化为单层直接返回业务数据字典。
- 无论使用何种提炼策略，可交互元素均必须分配连续且唯一的全局整数 Ref ID，且底层定位必须与 `page.locator('[data-astr-ref="{ref}"]')` 无缝兼容。
- 所有的长文本切分必须在保持语义块（Block）或自闭合子树结构完整的前提下进行，严禁硬截断 Markdown 语法或 ARIA 树行。
- 白名单规则全面支持 `domains: list[str]`，并保持向下兼容旧配置中的单 `domain: str`。

## Review Focus

1. **密码脱敏边界**：表单内的 `type="password"` 输入框在 `mask_password_inputs=True` 时其值必须被脱敏为 `******`，但在 `mask_password_inputs=False` 时必须如实输出明文。
2. **多页翻页编号稳定性**：用户在同一页面中连续调用 `pw_read(page=1)` 和 `pw_read(page=2)` 时，底层快照必须命中缓存，不得重新触发全页面扫描或重排 Ref ID。
3. **交互后脏快照自动感知**：调用 `pw_interact` 执行点击/输入后，上下文必须置为脏状态；后续调用 `pw_read` 时必须自动拉取最新 DOM，绝不返回陈旧快照。
4. **生命周期全部事件检索**：请求 `lifecycle/logs?event_type=all` 或空字符串时，SQL 不得包含 `WHERE event_type = 'all'`，必须返回全部事件类型。
5. **Bridge 原生下载通道降级**：在 AstrBot Dashboard iframe 环境中导出日志优先调用 `window.AstrBotPluginPage.download`，若不可用则无缝降级为 Blob URL 本地下载。

---

### Task 1: 生命周期 Web API 路由对齐与 SQL 过滤修复 (Problem 1)

**Files:**
- Modify: `core/audit_logger.py:348-366`
- Modify: `web-src/src/api/lifecycle.ts:10-26`
- Test: `tests/test_audit_logger.py`
- Test: `tests/test_lifecycle_api.py`

**Interfaces:**
- Consumes: `AuditLogger.query_lifecycle_logs(page, page_size, session_id, event_type, keyword)`
- Produces: 修复当 `event_type in ("", "all", None)` 时忽略类型过滤，前端 `fetchActiveContexts` 统一请求 `lifecycle/active`

- [ ] **Step 1: 编写生命周期 SQL 过滤修复的失败测试**

在 `tests/test_audit_logger.py` 中添加测试用例：
```python
async def test_query_lifecycle_logs_event_type_all_returns_all(self):
    await self.logger.log_lifecycle("s1", "c1", "u1", "created", "u1")
    await self.logger.log_lifecycle("s1", "c1", "u1", "closed", "u1")
    logs, total = await self.logger.query_lifecycle_logs(event_type="all")
    self.assertEqual(total, 2)
    logs_empty, total_empty = await self.logger.query_lifecycle_logs(event_type="")
    self.assertEqual(total_empty, 2)
    logs_specific, total_specific = await self.logger.query_lifecycle_logs(event_type="created")
    self.assertEqual(total_specific, 1)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/Scripts/python.exe -m unittest tests/test_audit_logger.py`
Expected: FAIL with `AssertionError: 0 != 2`（因为之前查询了 `event_type = 'all'`）

- [ ] **Step 3: 修复 `core/audit_logger.py` 中的过滤逻辑**

在 `core/audit_logger.py` 的 `query_lifecycle_logs` 方法中，忽略 `all`、空字符串或全空格：
```python
if event_type and event_type.strip() and event_type.strip().lower() != "all":
    conditions.append("event_type = ?")
    params.append(event_type.strip())
```

- [ ] **Step 4: 修复前端 `web-src/src/api/lifecycle.ts` 路由调用**

在 `web-src/src/api/lifecycle.ts` 的 `fetchActiveContexts` 中将请求 endpoint 修正为 `lifecycle/active`：
```typescript
export async function fetchActiveContexts(
  includeAll: boolean = false
): Promise<ActiveContextItem[]> {
  const endpoint = "lifecycle/active";
  try {
    const res = await apiGet<any>(endpoint);
    if (res && Array.isArray(res.items)) {
      return res.items;
    }
    if (res && res.data && Array.isArray(res.data.items)) {
      return res.data.items;
    }
  } catch (err) {
    console.warn(`[LifecycleAPI] ${endpoint} error:`, err);
  }
  return [];
}
```

- [ ] **Step 5: 验证测试通过**

Run: `.venv/Scripts/python.exe -m unittest tests/test_audit_logger.py tests/test_lifecycle_api.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/audit_logger.py web-src/src/api/lifecycle.ts tests/test_audit_logger.py
git commit -m "fix: align lifecycle active endpoint and fix event_type=all filter"
```

---

### Task 2: Web API 单层扁平化与审计导出下载通道升级 (Problem 2)

**Files:**
- Modify: `api/audit_api.py:121-148`
- Modify: `api/lifecycle_api.py:94-147`
- Modify: `web-src/src/types.ts:36-40`
- Modify: `web-src/src/api/audit.ts:21-86`
- Modify: `web-src/src/api/lifecycle.ts:40-60`
- Modify: `web-src/src/views/AuditView.tsx:110-130`
- Test: `tests/test_audit_api.py`
- Test: `tests/test_lifecycle_api.py`

**Interfaces:**
- Consumes: `api_audit_logs`, `api_audit_stats`, `api_audit_export`, `api_active_contexts`, `api_lifecycle_logs`
- Produces: 单层响应直出 `{items, total, page, page_size}` 或 `{total, allowed, ...}`；`exportAuditLogs` 优先调用 `bridge.download`。

- [ ] **Step 1: 编写单层数据响应契约的失败测试**

在 `tests/test_audit_api.py` 中更新或添加断言：
```python
async def test_audit_logs_single_layer_contract(self):
    res = await self.handler.api_audit_logs()
    # 验证不再返回嵌套的 {"code": 0, "data": {...}}，而是直接返回业务字段
    data = res.body if hasattr(res, "body") else res
    import json
    if isinstance(data, (bytes, bytearray)):
        data = json.loads(data.decode("utf-8"))
    self.assertIn("items", data)
    self.assertIn("total", data)
    self.assertNotIn("code", data)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/Scripts/python.exe -m unittest tests/test_audit_api.py`
Expected: FAIL（原实现返回了 `{"code": 0, "data": {...}}`）

- [ ] **Step 3: 扁平化 `api/audit_api.py` 与 `api/lifecycle_api.py` 响应**

修改 `api/audit_api.py`：
- `api_audit_logs` 返回 `json_response({"items": items, "total": total, "page": page, "page_size": page_size})`
- `api_audit_stats` 返回 `json_response(stats)`
- `api_audit_export` 返回 `json_response({"content": content, "format": fmt})`
修改 `api/lifecycle_api.py`：
- `api_active_contexts` 返回 `json_response({"items": active_items, "total": len(active_items)})`
- `api_lifecycle_logs` 返回 `json_response({"items": logs, "total": total, "page": page, "page_size": page_size})`

- [ ] **Step 4: 更新前端数据模型与导出 Bridge 对接**

1. 修改 `web-src/src/types.ts` 中的 `ApiResponse<T>`，使其可以直接兼容单层数据：
   ```typescript
   export type ApiResponse<T> = T & { code?: number; data?: T; message?: string };
   ```
2. 修改 `web-src/src/api/audit.ts`：
   - 更新 `fetchAuditLogs` 与 `fetchAuditStats` 直接读取 `res.items` / `res.total`；
   - 更新 `exportAuditLogs`：
     ```typescript
     export async function exportAuditLogs(
       format: "json" | "csv" = "json"
     ): Promise<{ content: string; format: string }> {
       const bridge = (window as any).AstrBotPluginPage || (window as any).AstrBotPluginView;
       if (bridge && typeof bridge.download === "function") {
         try {
           const filename = `audit-logs-${new Date().toISOString().slice(0, 10)}.${format}`;
           await bridge.download("audit/export", { format }, filename);
           return { content: "[DOWNLOADED_BY_BRIDGE]", format };
         } catch (err) {
           console.warn("[AuditAPI] bridge.download failed, falling back to apiGet:", err);
         }
       }
       const res = await apiGet<any>("audit/export", { format });
       const content = (res && typeof res.content === "string") ? res.content : (res && res.data) ? res.data : (typeof res === "string" ? res : "");
       return { content, format };
     }
     ```
3. 修改 `web-src/src/views/AuditView.tsx` 的 `handleExport`：
   如果 `result.content === "[DOWNLOADED_BY_BRIDGE]"` 则直接提示导出成功；否则以 UTF-8 Blob 触发本地下载。

- [ ] **Step 5: 运行后端单元测试**

Run: `.venv/Scripts/python.exe -m unittest tests/test_audit_api.py tests/test_lifecycle_api.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/audit_api.py api/lifecycle_api.py web-src/src/types.ts web-src/src/api/audit.ts web-src/src/api/lifecycle.ts web-src/src/views/AuditView.tsx tests/test_audit_api.py
git commit -m "refactor: flatten web api responses to single-layer and support bridge.download"
```

---

### Task 3: 白名单规则支持多域名列表集合 (Additional Problem)

**Files:**
- Modify: `_conf_schema.json:26-70`
- Modify: `core/security_manager.py:47-115`
- Test: `tests/test_security_manager.py`
- Test: `tests/test_conf_schema.py`

**Interfaces:**
- Consumes: `rule.get("domains")` (list of strings) or fallback `rule.get("domain")` (string)
- Produces: `SecurityManager.is_url_allowed_navigation` 与 `check_permission` 对 `domains` 列表内任一匹配即生效。

- [ ] **Step 1: 编写多域名白名单规则匹配的失败测试**

在 `tests/test_security_manager.py` 中添加测试用例：
```python
def test_whitelist_rules_multi_domains_match(self):
    rules = [
        {
            "domains": ["*.github.com", "github.com", "git-scm.com"],
            "allowed_actions": ["read", "click"]
        }
    ]
    mgr = SecurityManager(admin_only=False, whitelist_rules=rules)
    # 测试列表中不同域名
    ok1, _ = mgr.check_permission("user1", "https://api.github.com/repos", "read")
    self.assertTrue(ok1)
    ok2, _ = mgr.check_permission("user1", "https://github.com/SmileYik", "click")
    self.assertTrue(ok2)
    ok3, _ = mgr.check_permission("user1", "https://git-scm.com/docs", "read")
    self.assertTrue(ok3)
    # 拒绝未在列表的域名与未授权动作
    ok4, _ = mgr.check_permission("user1", "https://gitlab.com", "read")
    self.assertFalse(ok4)
    ok5, _ = mgr.check_permission("user1", "https://github.com", "download")
    self.assertFalse(ok5)

def test_whitelist_rules_backward_compatibility_single_domain(self):
    rules = [{"domain": "example.com", "allowed_actions": ["read"]}]
    mgr = SecurityManager(admin_only=False, whitelist_rules=rules)
    ok, _ = mgr.check_permission("user1", "https://example.com", "read")
    self.assertTrue(ok)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/Scripts/python.exe -m unittest tests/test_security_manager.py`
Expected: FAIL（因为当前代码仅提取 `rule.get("domain", "")`）

- [ ] **Step 3: 更新 `core/security_manager.py` 匹配逻辑**

在 `core/security_manager.py` 中实现统一的 `_is_rule_match(self, host: str, rule: dict) -> bool`：
```python
def _is_rule_match(self, host: str, rule: dict) -> bool:
    domains = rule.get("domains")
    if domains is None:
        dom = rule.get("domain")
        domains = [dom] if dom else []
    elif isinstance(domains, str):
        domains = [domains]
    return any(self._is_domain_match(host, str(d)) for d in domains if str(d).strip())
```
在 `is_url_allowed_navigation` 与 `check_permission` 中用 `_is_rule_match` 代替原本单独检查 `rule.get("domain")`。

- [ ] **Step 4: 更新 `_conf_schema.json` 中的字段定义**

在 `_conf_schema.json` 中将 `whitelist_rules.templates.rule.items.domain` 升级为 `domains`：
```json
"domains": {
  "type": "list",
  "description": "目标域名/通配符列表",
  "hint": "输入域名或通配符（如 *.github.com、github.com），本规则内的所有操作权限均应用于该域名集合",
  "default": []
}
```
并将 `display_item` 调整为 `domains`。

- [ ] **Step 5: 验证测试通过**

Run: `.venv/Scripts/python.exe -m unittest tests/test_security_manager.py tests/test_conf_schema.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add _conf_schema.json core/security_manager.py tests/test_security_manager.py
git commit -m "feat: support multiple domain patterns per whitelist rule with backward compatibility"
```

---

### Task 4: 配置项扩展：提炼模式、密码脱敏开关与分页字符预算

**Files:**
- Modify: `_conf_schema.json:7-130`
- Modify: `main.py:100-140`
- Test: `tests/test_conf_schema.py`

**Interfaces:**
- Consumes: 用户配置的 `mask_password_inputs`, `content_extraction_mode`, `page_chunk_char_limit`
- Produces: `main.py` 提取配置并挂载至 `self.content_extraction_mode`, `self.mask_password_inputs`, `self.page_chunk_char_limit`。

- [ ] **Step 1: 编写配置解析的失败测试**

在 `tests/test_conf_schema.py` 中增加对新配置项的断言：
```python
def test_new_extraction_and_security_config_schema(self):
    with open("_conf_schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    self.assertIn("mask_password_inputs", schema["security"]["items"])
    self.assertIn("content_extraction_mode", schema["runtime"]["items"])
    self.assertIn("page_chunk_char_limit", schema["runtime"]["items"])
    self.assertEqual(schema["runtime"]["items"]["page_chunk_char_limit"]["default"], 2000)
    self.assertTrue(schema["security"]["items"]["mask_password_inputs"]["default"])
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/Scripts/python.exe -m unittest tests/test_conf_schema.py`
Expected: FAIL（未找到新配置项）

- [ ] **Step 3: 更新 `_conf_schema.json`**

在 `security.items` 下追加 `mask_password_inputs`；在 `runtime.items` 下追加 `content_extraction_mode` 与 `page_chunk_char_limit`。

- [ ] **Step 4: 在 `main.py` 中解析配置并赋默认值**

在 `main.py` 的 `__init__` 中读取：
```python
security_cfg = config.get("security", {})
runtime_cfg = config.get("runtime", {})
self.mask_password_inputs = bool(security_cfg.get("mask_password_inputs", True))
self.content_extraction_mode = str(runtime_cfg.get("content_extraction_mode", "inline_markdown")).strip().lower()
self.page_chunk_char_limit = int(runtime_cfg.get("page_chunk_char_limit", 2000))
```

- [ ] **Step 5: 验证测试通过**

Run: `.venv/Scripts/python.exe -m unittest tests/test_conf_schema.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add _conf_schema.json main.py tests/test_conf_schema.py
git commit -m "feat: add config options for extraction mode, password masking, and page chunk budget"
```

---

### Task 5: 策略模式基类与 `InlineMarkdownReader` 实现

**Files:**
- Create: `core/readers/__init__.py`
- Create: `core/readers/base.py`
- Create: `core/readers/markdown_reader.py`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: Playwright `page.evaluate(script)`, `chunk_char_limit: int`, `mask_passwords: bool`
- Produces: `InlineMarkdownReader(BasePageReader)`：单遍阅读序遍历 DOM，将标题、段落、图片、控件内联为 Markdown，按语义块边界分页。

- [ ] **Step 1: 编写 `InlineMarkdownReader` 的失败测试**

创建 `tests/test_readers.py`：
```python
import unittest
from core.readers.markdown_reader import InlineMarkdownReader

class TestInlineMarkdownReader(unittest.IsolatedAsyncioTestCase):
    def test_semantic_block_chunking_preserves_elements(self):
        reader = InlineMarkdownReader(chunk_char_limit=150, mask_passwords=True)
        blocks = [
            "# 标题一",
            "这是第一节详细介绍段落，长度适中。",
            "## 标题二\n- [Ref: 1] [按钮: 点击下载]\n- 状态说明: 推荐选项",
            "## 标题三\n- [Ref: 2] [链接: 历史版本目录]"
        ]
        chunks = reader._chunk_blocks(blocks, "https://example.com", "测试网页")
        self.assertGreaterEqual(len(chunks), 2)
        # 验证每个切片内 ref 完整，且切片首尾包含分页提示
        self.assertIn("[Ref: 1]", "".join(chunks))
        self.assertIn("[分页:", chunks[0])

    def test_password_masking_switch(self):
        reader_masked = InlineMarkdownReader(mask_passwords=True)
        html_script = reader_masked.get_js_extractor_script()
        self.assertIn("******", html_script)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/Scripts/python.exe -m unittest tests/test_readers.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.readers'`

- [ ] **Step 3: 实现 `core/readers/base.py`**

定义 `PageSnapshot` dataclass 与 `BasePageReader` 抽象基类，规范 `extract_snapshot`、`format_chunk`、`search`、`get_tool_metadata`。

- [ ] **Step 4: 实现 `core/readers/markdown_reader.py`**

1. 编写内联提炼 JS 脚本：
   - 顺序提取 DOM；
   - 提取 `<img>` 标签生成 `![alt](src)`；
   - 提取控件时就地分配全局自增 `ref`，注入 `data-astr-ref="{ref}"`，并生成 `[Ref: X] [按钮: 文本]` 或 `[Ref: X] [链接: 文本]`；
   - 针对 `input[type="password"]`，当 `self.mask_passwords=True` 时固定输出 `value="******"`；
2. 实现 `_chunk_blocks`：累加 Block 字符，不越过 `self.chunk_char_limit` 并在语义块边界切分，追加上下文定位与翻页提示。
3. 实现 `format_chunk` 与 `search` 方法。

- [ ] **Step 5: 验证测试通过**

Run: `.venv/Scripts/python.exe -m unittest tests/test_readers.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/readers/ tests/test_readers.py
git commit -m "feat: implement BasePageReader and InlineMarkdownReader with block pagination"
```

---

### Task 6: `AriaSnapshotReader` 实现（客户端 DOM 语义映射与祖先回填）

**Files:**
- Create: `core/readers/aria_reader.py`
- Modify: `core/readers/__init__.py`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: Playwright `page.evaluate(script)`, `chunk_char_limit: int`, `mask_passwords: bool`
- Produces: `AriaSnapshotReader(BasePageReader)`：输出符合 ARIA Snapshot 规范的 YAML 缩进层级树，分配并注入 `data-astr-ref`，按区域切分并回填祖先树桩。

- [ ] **Step 1: 编写 `AriaSnapshotReader` 的失败测试**

在 `tests/test_readers.py` 中增加用例：
```python
from core.readers.aria_reader import AriaSnapshotReader

class TestAriaSnapshotReader(unittest.IsolatedAsyncioTestCase):
    def test_aria_reader_tool_metadata(self):
        reader = AriaSnapshotReader(chunk_char_limit=1500)
        meta = reader.get_tool_metadata()
        self.assertIn("ARIA", meta["description"])
        self.assertIn("page", meta["parameters"]["properties"])

    def test_aria_chunking_with_ancestor_breadcrumbs(self):
        reader = AriaSnapshotReader(chunk_char_limit=200)
        tree_text = (
            "- main:\n"
            "  - region \"客户端\":\n"
            "    - button \"下载\" [ref=1]\n"
            "  - region \"服务端\":\n"
            "    - button \"下载\" [ref=2]\n"
        )
        chunks = reader._chunk_aria_tree(tree_text, "https://example.com", "测试网页")
        self.assertGreaterEqual(len(chunks), 1)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/Scripts/python.exe -m unittest tests/test_readers.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.readers.aria_reader'`

- [ ] **Step 3: 实现 `core/readers/aria_reader.py`**

1. 编写客户端 DOM ARIA 映射 JS 脚本：
   - 递归计算元素的 computed role、accessible name、level 等属性；
   - 过滤不可见节点；
   - 遍历到可交互角色（button, link, textbox, combobox, checkbox 等）时在真实 DOM 上打上 `node.setAttribute('data-astr-ref', ref.toString())` 并生成 `[ref=X]`；
   - 密码框依据 `mask_passwords` 处理脱敏；
   - 格式化为标准缩进的 YAML 树。
2. 实现 `_chunk_aria_tree`：
   - 按顶层 `region` / `section` 优先拆分；
   - 若超出 `chunk_char_limit`，在子树边界切断并在下页首部回填祖先路径缩进树桩；
   - 结尾附加翻页与交互指令提示。

- [ ] **Step 4: 验证测试通过**

Run: `.venv/Scripts/python.exe -m unittest tests/test_readers.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/readers/aria_reader.py core/readers/__init__.py tests/test_readers.py
git commit -m "feat: implement AriaSnapshotReader with client-side ARIA tree and breadcrumb pagination"
```

---

### Task 7: 解耦 `pw_page`、实现专属 `pw_read` 工具与上下文快照脏标记管理

**Files:**
- Modify: `tools/schemas.py:1-80`
- Modify: `core/context_manager.py:20-60`
- Modify: `tools/handlers/page_handler.py:1-200`
- Modify: `tools/handlers/interact_handler.py:40-120`
- Modify: `tools/tools.py:140-240`
- Modify: `main.py:120-160`
- Test: `tests/test_tools.py`
- Test: `tests/test_page_handler.py`

**Interfaces:**
- Consumes: `BasePageReader`, `PageHandler`, `ContextManager`, `ContextItem`
- Produces: `PwReadTool` 独立注册；`pw_page` 精简仅支持 open/switch_tab/dialog/close；`is_snapshot_dirty` 驱动按需刷新与稳定连续翻页。

- [ ] **Step 1: 编写 `pw_read` 独立工具与 `pw_page` 精简后的失败测试**

在 `tests/test_tools.py` 中更新断言：
```python
def test_pw_page_schema_no_read_or_search(self):
    actions = PW_PAGE_SCHEMA["properties"]["action"]["enum"]
    self.assertNotIn("read", actions)
    self.assertNotIn("search", actions)
    self.assertEqual(set(actions), {"open", "switch_tab", "dialog", "close"})

def test_pw_read_tool_registered(self):
    from tools.tools import PwReadTool
    tool = PwReadTool(page_handler=self.page_handler)
    self.assertEqual(tool.name, "pw_read")
    self.assertIn("page", tool.parameters["properties"])
```

- [ ] **Step 2: 运行测试验证失败**

Run: `.venv/Scripts/python.exe -m unittest tests/test_tools.py`
Expected: FAIL（因为当前 `PW_PAGE_SCHEMA` 中仍包含 `read`，且尚无 `PwReadTool`）

- [ ] **Step 3: 更新 `tools/schemas.py` 与 `ContextItem`**

1. 修改 `tools/schemas.py`：
   - 精简 `PW_PAGE_SCHEMA`，动作仅保留 `open`, `switch_tab`, `dialog`, `close`；
   - 增加 `PW_READ_SCHEMA`：包含 `page` (int, default 1), `keyword` (string, default ""), `refresh` (bool, default False)。
2. 修改 `core/context_manager.py` 中的 `ContextItem`：
   - 增加属性：`current_snapshot: Any = None`、`is_snapshot_dirty: bool = False`。

- [ ] **Step 4: 改造 `PageHandler` 与 `InteractHandler`**

1. 在 `PageHandler` 中：
   - 注入 `reader: BasePageReader`；
   - `open_url`：打开网页，将上下文 `is_snapshot_dirty = True`，并返回简洁成功的引导话术；
   - `switch_tab`：切换标签后重置 `current_snapshot = None, is_snapshot_dirty = True`；
   - 新增 `read_page(session_id, sender_id, page=1, keyword="", refresh=False)`：
     - 若 `current_snapshot is None` 或 `is_snapshot_dirty` 或 `refresh`：调用 `self.reader.extract_snapshot` 并缓存，置 `is_snapshot_dirty = False`；
     - 同步更新 `ctx.ref_map = current_snapshot.ref_map`；
     - 若有 `keyword` 则调用 `self.reader.search`，否则调用 `self.reader.format_chunk(current_snapshot, page)`。
2. 在 `InteractHandler` 中：
   - 在任意 `click`, `fill_form`, `select_option`, `press_key` 执行完毕后，标记 `ctx.is_snapshot_dirty = True`。

- [ ] **Step 5: 改造 `tools/tools.py` 与 `main.py`**

1. 在 `tools/tools.py` 中：
   - 精简 `PwPageTool`：动作路由仅保留 open, switch_tab, dialog, close；
   - 新建 `PwReadTool`：绑定 `PW_READ_SCHEMA`，调用 `page_handler.read_page`，其 description 动态读取自 `page_handler.reader.get_tool_metadata()["description"]`。
2. 在 `main.py` 中：
   - 实例化对应的 Reader（基于 `self.content_extraction_mode`）；
   - 创建 `self.pw_read_tool = PwReadTool(page_handler=self.page_handler)`；
   - 在 `add_llm_tools` 中注册 `pw_page`, `pw_read`, `pw_interact`, `pw_media` 四个独立工具。

- [ ] **Step 6: 验证测试通过**

Run: `.venv/Scripts/python.exe -m unittest tests/test_tools.py tests/test_page_handler.py tests/test_interact_handler.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tools/schemas.py core/context_manager.py tools/handlers/ tools/tools.py main.py tests/
git commit -m "feat: decouple pw_page and implement independent pw_read tool with snapshot caching"
```

---

### Task 8: 全量测试集回归、前端产物构建与综合验证

**Files:**
- Modify: `tests/test_plugin_main.py`
- Modify: `views/browser/**` (前端编译输出产物)
- Test: 全量单元测试集

**Interfaces:**
- Consumes: 全量前后端改动
- Produces: 100% 自动测试回归通过；`views/browser/` 最新构建产物同步。

- [ ] **Step 1: 运行全量 Python 单元测试集**

Run: `.venv/Scripts/python.exe -m unittest discover tests`
Expected: 所有用例全部通过（130+ tests OK）。

- [ ] **Step 2: 构建前端静态产物并验证**

Run: `cd web-src; npm run build; cd ..` (必要时 BypassSandbox: true)
Expected: Vite 编译成功，更新 `views/browser/index.html` 及 assets 静态文件，无 TypeScript 类型错误。

- [ ] **Step 3: 检查 Git 状态与清洁度**

Run: `git status -s`
Expected: 仅包含本任务构建与测试修改，无多余未跟踪文件。

- [ ] **Step 4: Commit**

```bash
git add views/browser/ tests/
git commit -m "chore: build frontend assets and verify complete test suite passes"
```
