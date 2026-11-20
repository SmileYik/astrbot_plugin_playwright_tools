# 工具异步执行修复、Web API 独立模块化与可视化日志拉取修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复大模型调用 Playwright 工具时的 `async_generator` 异常，将 Web API 从 `main.py` 剥离至独立模块 `api/audit_api.py`，并修复 Web 端日志数据解包与重新编译前端。

**Architecture:** 
1. 将 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 的 `call()` 方法恢复为标准异步函数并返回字符串结果；
2. 新建 `api/audit_api.py` 承载 Web API 路由和请求响应逻辑，在 `main.py` 中仅做注册与代理；
3. 在 `web-src/src/App.tsx` 中兼容 AstrBot Bridge 自动解包后的数据格式，并重新打包输出至 `views/audit/`。

**Tech Stack:** Python 3.12+, TypeScript, React, Vite, AstrBot Star/FunctionTool SDK.

**Spec:** [docs/superpowers/specs/2026-11-20-tool-fix-and-web-api-refactor-design.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-20-tool-fix-and-web-api-refactor-design.md)

## Global Constraints

- 不改变审计日志数据表结构（SQLite 保持不变）。
- `main.py` 中严禁保留 Web API 逻辑实现与相关的网络库直接导入。
- 前端 `web-src` 修改后必须执行编译并将结果同步到 `views/audit/`。
- 遵循 [AGENT.md](../../../AGENT.md) 文档规范与命名规则，并更新 `CHANGELOG.md`。

## Review Focus

1. `PwPageTool.call`、`PwInteractTool.call` 和 `PwMediaTool.call` 必须是普通协程函数，不能包含任何 `yield`，调用必须返回字符串。
2. `PwMediaTool.call` 在截图且 `target="chat"` 时，推送图片消息不能抛出未捕获异常，且依然必须向 LLM 返回结果字符串。
3. `AuditApiHandler` 在非 AstrBot 环境或独立测试环境下必须有 `json_response`、`error_response`、`request` 降级容错。
4. `web-src/src/App.tsx` 必须同时支持 Bridge 解包对象格式（包含 `items`/`total`）与标准包裹格式（包含 `code: 0, data: ...`）。
5. `main.py` 保持向后兼容：保留对 `api_audit_*` 的属性委托，避免任何外部模块或用例发生属性缺失。

---

### Task 1: 修复工具类的协程执行机制 (`tools/tools.py`)

**Files:**
- Modify: `tools/tools.py:208-221, 343-359, 416-439`
- Modify: `tests/test_tools_v2.py:70-130`

**Interfaces:**
- Consumes: `_extract_event_and_metadata(context)`, `_execute_with_timeout(coro, timeout)`
- Produces: `async def call(self, context: AstrAgentContext, **kwargs) -> str`

- [ ] **Step 1: 在 `tests/test_tools_v2.py` 中修改并编写针对普通异步协程的测试用例**

```python
# 将测试从 run_gen(generator) 调整为 asyncio 运行普通协程
def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def test_page_tool_call_is_coroutine(self):
    res = run_async(self.page_tool.call(self.mock_context_wrapper, action="unknown_action"))
    self.assertIsInstance(res, str)
    self.assertIn("未知的动作", res)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python tests/test_tools_v2.py`
预期：因当前实现为 `async_generator`，在断言 `isinstance(res, str)` 时失败或报错。

- [ ] **Step 3: 修改 `tools/tools.py` 中的 `call` 实现**

1. 将 `PwPageTool.call` 中的 `yield f"未知的动作..."` 改为 `return f"未知的动作..."`，`yield res` 改为 `return res`。
2. 将 `PwInteractTool.call` 中的 `yield f"未知的动作..."` 改为 `return f"未知的动作..."`，`yield res` 改为 `return res`。
3. 将 `PwMediaTool.call` 中的 `yield f"未知的动作..."` 改为 `return f"未知的动作..."`；对于截图推送：
   ```python
   target = str(kwargs.get("target", "chat")).lower()
   if action in ("screenshot_viewport", "screenshot_full") and target == "chat" and res.startswith("[IMAGE_PATH:"):
       img_path = res.split("\n", 1)[0].strip()[len("[IMAGE_PATH:"):].rstrip("]")
       if hasattr(event, "send") and callable(event.send):
           try:
               from astrbot.core.message.message_event_result import MessageChain
               await event.send(MessageChain().file_image(img_path))
           except Exception:
               pass
   return res
   ```

- [ ] **Step 4: 运行 `tests/test_tools_v2.py` 验证全部测试通过**

运行：`python tests/test_tools_v2.py`
预期：全部用例 PASS。

- [ ] **Step 5: 提交代码**

```bash
git add tools/tools.py tests/test_tools_v2.py
git commit -m "fix(tools): convert tool call methods from async generator to coroutine"
```

---

### Task 2: 提取 Web API 至独立模块 `api/audit_api.py` 并重构 `main.py`

**Files:**
- Create: `api/__init__.py`
- Create: `api/audit_api.py`
- Create: `tests/test_audit_api.py`
- Modify: `main.py:8-16, 120-145, 258-332`
- Modify: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: `AuditLogger` (from `core/audit_logger.py`)
- Produces: `class AuditApiHandler(audit_logger: AuditLogger)` with method `register_routes(context: Any, plugin_name: str) -> None`

- [ ] **Step 1: 编写 `tests/test_audit_api.py` 单元测试**

测试 `AuditApiHandler` 的路由注册以及 4 个接口函数（`api_audit_logs`、`api_audit_stats`、`api_audit_export`、`api_audit_clear`）的调用与参数解析。

- [ ] **Step 2: 运行测试确认其因模块未创建而失败**

运行：`python tests/test_audit_api.py`
预期：FAIL with `ModuleNotFoundError: No module named 'api'`。

- [ ] **Step 3: 创建 `api/__init__.py` 与 `api/audit_api.py`**

实现 `AuditApiHandler` 类：
1. 包含 `json_response`、`error_response`、`request` 的安全导入与降级回退函数。
2. 实现 `register_routes(context, plugin_name)`，注册：
   - `/{plugin_name}/audit/logs` -> `GET`
   - `/{plugin_name}/audit/stats` -> `GET`
   - `/{plugin_name}/audit/export` -> `GET`
   - `/{plugin_name}/audit/clear` -> `POST`
3. 实现 `api_audit_logs`、`api_audit_stats`、`api_audit_export`、`api_audit_clear` 业务逻辑。

- [ ] **Step 4: 重构 `main.py` 移除 API 逻辑**

1. 导入 `from .api.audit_api import AuditApiHandler`。
2. 在 `PlaywrightToolPlugin.__init__` 中实例化：
   ```python
   self.audit_api = AuditApiHandler(self.audit_logger)
   self.audit_api.register_routes(self.context, PLUGIN_NAME)
   ```
3. 暴露属性别名以保证兼容性：
   ```python
   self.api_audit_logs = self.audit_api.api_audit_logs
   self.api_audit_stats = self.audit_api.api_audit_stats
   self.api_audit_export = self.audit_api.api_audit_export
   self.api_audit_clear = self.audit_api.api_audit_clear
   ```
4. 彻底删除 `main.py` 中的 `api_audit_*` 原始方法定义与 `astrbot.api.web` 导入。

- [ ] **Step 5: 运行 `test_audit_api.py` 与 `test_plugin_main.py` 验证通过**

运行：
`python tests/test_audit_api.py`
`python tests/test_plugin_main.py`
预期：全部 PASS。

- [ ] **Step 6: 提交代码**

```bash
git add api/__init__.py api/audit_api.py main.py tests/test_audit_api.py tests/test_plugin_main.py
git commit -m "refactor(api): extract web api routes into separate api.audit_api module"
```

---

### Task 3: 修复前端日志拉取与响应解析，重新编译构建 Web

**Files:**
- Modify: `web-src/src/App.tsx:115-136, 166-187, 197-226, 229-255`
- Output: `views/audit/index.html`, `views/audit/assets/*`

**Interfaces:**
- Consumes: `window.AstrBotPluginView.apiGet` / `apiPost`
- Produces: 成功解析并渲染日志列表、统计卡片、导出与清空。

- [ ] **Step 1: 修改 `web-src/src/App.tsx` 中的响应适配逻辑**

1. `fetchLogs`：
   ```typescript
   const res = await bridge.apiGet<any>("audit/logs", { ... });
   const data = (res && Array.isArray(res.items)) ? res : (res?.data ?? res);
   if (data && Array.isArray(data.items)) {
     setLogs(data.items);
     setTotal(data.total || 0);
   } else {
     showBanner(res?.message || "拉取日志失败", "error");
   }
   ```
2. `fetchStats`：
   ```typescript
   const res = await bridge.apiGet<any>("audit/stats");
   const data = (res && typeof res.total === "number") ? res : (res?.data ?? res);
   if (data && typeof data.total === "number") {
     setStats(data);
   }
   ```
3. `handleExport`：
   ```typescript
   const res = await bridge.apiGet<any>("audit/export", { ... });
   const content = typeof res === "string" ? res : (res?.data ?? res);
   if (content && typeof content === "string") {
     // 生成 Blob 下载
     ...
   }
   ```
4. `handleClear`：
   ```typescript
   const res = await bridge.apiPost<any>("audit/clear", { confirm: true });
   const cleared = typeof res?.cleared === "number" ? res.cleared : res?.data?.cleared;
   if (cleared !== undefined || res?.code === 0) {
     showBanner(`已清空 ${cleared ?? 0} 条历史审计记录`, "info");
     ...
   }
   ```

- [ ] **Step 2: 在 `web-src` 下执行编译打包**

运行：`cd web-src && npm run build` (或 `pnpm build`)
预期：TypeScript 检查通过，Vite 成功生成静态文件至 `../views/audit`。

- [ ] **Step 3: 检查编译产物输出**

检查 `views/audit/index.html` 以及 `views/audit/assets/` 下的文件已更新。

- [ ] **Step 4: 提交代码**

```bash
git add web-src/src/App.tsx views/audit/
git commit -m "fix(web): adapt bridge unwrapped responses and rebuild audit view"
```

---

### Task 4: 整体回归测试与文档同步维护

**Files:**
- Modify: `AGENT.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 运行全量单元测试**

运行测试脚本，确保 `test_tools_v2.py`、`test_audit_api.py`、`test_plugin_main.py` 等关键测试全部通过。

- [ ] **Step 2: 更新 `AGENT.md` 与 `CHANGELOG.md`**

1. 在 [AGENT.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/AGENT.md) 的“项目目录构”中增加 `- api: 网页 Web API 路由与业务代码`。
2. 在 [CHANGELOG.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/CHANGELOG.md) 中添加本次变更记录（工具协程修复、Web API 独立模块化、前端解包修复）。

- [ ] **Step 3: 提交文档**

```bash
git add AGENT.md CHANGELOG.md
git commit -m "docs: update directory structure and changelog"
```
