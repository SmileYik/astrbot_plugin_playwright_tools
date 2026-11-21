# 审计异常堆栈追溯、生命周期元信息增强与前端实时流式自动更新实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Markdown 阅读器 JS 正则转义语法错误，实现工具审计完整异常堆栈入库与前端高亮展示，补全生命周期“会话名称+ID”与“人员名称+ID”元信息，并在前端实现不打扰的实时流式“自动更新”。

**Architecture:** 
1. 修复 `InlineMarkdownReader` 生成脚本时对 `[\\r\\n\\t]` 的双重转义，防止 Python 模板将正则字符组替换为物理换行符。
2. 在各 Handler 捕获未处理异常时将包含 `traceback.format_exc()` 的完整异常文本写入 `error_message`；前端抽屉分离首行概况与完整堆栈面板。
3. 扩展 `context_lifecycle_logs` 数据表字段与 `ContextManager` 事件链路，贯通持久化 `operator_name` 与 `owner_name`，在生命周期视图中同时展示会话名+ID、人员名+ID。
4. 封装 `useAutoStream` React Hook，结合 AstrBot Bridge 轮询机制在首屏无打扰平滑插入新记录，并在翻页或打开抽屉时仅更新统计指标。

**Tech Stack:** Python 3.12, Playwright, SQLite3, React 18, TypeScript, Vite, CSS Modules.

**Spec:** [docs/superpowers/specs/2026-11-21-audit-traceback-and-live-stream-design.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-21-audit-traceback-and-live-stream-design.md)

## Global Constraints

- **Bridge 鉴权约束**：前端运行于 iframe 内，所有网络请求必须经由 `AstrBotPluginViewBridge`（`apiGet` / `apiPost`），禁止依赖直连原生 WebSocket 或 EventSource。
- **数据库无损升级**：SQLite 表结构升级必须通过 `ALTER TABLE ... ADD COLUMN` 配合 `OperationalError` 容错，绝不破坏既有数据。
- **非侵入式刷新**：自动更新开启时，若用户位于第 2 页及之后或打开了详情侧边栏，严禁强制跳回第 1 页或强刷重置滚动条。

## Review Focus

1. `InlineMarkdownReader.get_js_extractor_script()` 生成的代码中不能包含未经转义的物理回车或换行符。
2. 工具抛出深层调用异常时，`audit_logger` 记录的 `error_message` 包含完整的 Traceback 信息（包含文件名与行号）。
3. 前端侧边栏在遇到多行 `error_message` 时，黄色警告横幅仅展示第一行概况，堆栈区呈现完整可滚动的 Traceback，并提供复制按钮。
4. 生命周期历史事件表格中，会话展示为 `会话名称 (会话 ID)`，操作人展示为 `操作人名称 (操作人 ID)`，当名称为空时回退为纯 ID。
5. 当用户在第一页开启“自动更新”且无抽屉打开时，新数据平滑流入；打开抽屉后轮询不再打断抽屉视图。

---

### Task 1: 修复 Markdown 阅读器 JS 正则转义语法错误

**Files:**
- Modify: `core/readers/markdown_reader.py:132`
- Test: `tests/test_readers.py`

**Interfaces:**
- Consumes: `InlineMarkdownReader.get_js_extractor_script() -> str`
- Produces: 语法合法的 JavaScript 提取脚本，不包含未转义正则字面量换行。

- [ ] **Step 1: 编写针对 JS 提取脚本正则合法性与换行符检查的测试用例**

在 `tests/test_readers.py` 中添加 `test_inline_markdown_reader_script_syntax_and_escapes`:
```python
    def test_inline_markdown_reader_script_syntax_and_escapes(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script()
        # 验证 script 中不存在包含物理 CR/LF/TAB 的 replace(/[\r\n\t]+/g, ' ')
        self.assertNotIn("replace(/[\r", script)
        self.assertNotIn("replace(/[\n", script)
        self.assertIn(r"replace(/[\r\n\t]+/g, ' ')", script)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m unittest tests.test_readers.TestPageReaders.test_inline_markdown_reader_script_syntax_and_escapes -v`  
Expected: FAIL (`AssertionError: 'replace(/[\\r' unexpectedly in script`)

- [ ] **Step 3: 修复 `core/readers/markdown_reader.py` 中的转义字符**

在 `core/readers/markdown_reader.py` 第 132 行，将：
`return node.nodeValue.replace(/[\r\n\t]+/g, ' ');`
替换为：
`return node.nodeValue.replace(/[\\r\\n\\t]+/g, ' ');`

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m unittest tests.test_readers -v`  
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add core/readers/markdown_reader.py tests/test_readers.py
git commit -m "fix(readers): escape regex line breaks in InlineMarkdownReader js script"
```

---

### Task 2: 全量异常堆栈持久化与 Handlers / 工具异常捕获补全

**Files:**
- Modify:
  - `tools/handlers/page_handler.py:115-125, 174-184`
  - `tools/handlers/interact_handler.py:114-124, 165-175, 220-230, 262-272, 303-313, 344-354, 392-402, 435-445, 480-490`
  - `tools/handlers/media_handler.py:197-207, 282-292, 367-377`
  - `tools/tools.py:130-138`
- Test: `tests/test_audit_logger.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: Python 内置 `traceback.format_exc()`, `AuditLogger.log_action(...)`
- Produces: 包含完整堆栈跟踪的 `error_message` 存储于 `tool_audit_logs` 表。

- [ ] **Step 1: 在 `tests/test_audit_logger.py` 中编写验证保存和查询多行堆栈追踪的测试**

```python
    def test_audit_records_and_searches_full_stack_trace(self):
        dummy_traceback = (
            "ValueError: test evaluation error\n\n"
            "Traceback (most recent call last):\n"
            '  File "test_file.py", line 42, in test_fn\n'
            "    raise ValueError('test evaluation error')\n"
        )
        run_coro(self.logger.log_action(
            "s1", "c1", "u1", "read_page", "https://example.com",
            {"page": 1}, "读取页面异常: test evaluation error",
            is_permitted=True, is_error=True, error_message=dummy_traceback
        ))
        items, total = run_coro(self.logger.query_logs(keyword="test_file.py", status="error"))
        self.assertEqual(total, 1)
        self.assertIn("Traceback (most recent call last):", items[0]["error_message"])
```

- [ ] **Step 2: 运行测试验证**

Run: `python -m unittest tests.test_audit_logger.TestAuditLogger.test_audit_records_and_searches_full_stack_trace -v`  
Expected: PASS (证实 SQLite TEXT 字段可完美保存与模糊检索堆栈)

- [ ] **Step 3: 更新各 Handler 与 tools.py，捕获并保存完整堆栈**

1. 在 `tools/handlers/page_handler.py` 中：
```python
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] read_page 异常: {e}\n{tb_str}")
            err_msg = f"读取页面异常: {str(e)}"
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "read_page", current_url, {"page": page, "keyword": keyword, "refresh": refresh}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg
```
同理更新 `page_handler.py` 的 `open_url`。
2. 同步更新 `tools/handlers/interact_handler.py`（click, fill_form, select_option, hover, press_key, drag_and_drop, evaluate_js, scroll 等）与 `tools/handlers/media_handler.py` 中的各异常捕获点，保证 `error_message` 传入 `f"{type(e).__name__}: {str(e)}\n\n{tb_str}"`。

- [ ] **Step 4: 运行全部测试验证没有破坏既有测试**

Run: `python -m unittest discover tests`  
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tools/handlers/ tools/tools.py tests/test_audit_logger.py
git commit -m "feat(audit): record full traceback stack trace in audit logger error_message"
```

---

### Task 3: 生命周期元信息穿透与双重标识（名称 + ID）

**Files:**
- Modify:
  - `core/audit_logger.py:53-65, 297-334, 335-385`
  - `core/context_manager.py:25-35, 75-100, 183-255, 328-340, 420-438, 505-517`
  - `api/lifecycle_api.py:122-135`
- Test: `tests/test_audit_logger.py`, `tests/test_context_manager.py`

**Interfaces:**
- Consumes: `session_name: str`, `sender_name: str`, `owner_name: str`, `operator_name: str`
- Produces: 
  - `context_lifecycle_logs` 表包含 `operator_name` 与 `owner_name` 字段。
  - `get_active_contexts_detail` 返回包含 `session_name` 与 `owner_name`。
  - `query_lifecycle_logs` 返回记录包含 `session_name`, `session_id`, `operator_name`, `operator_id`, `owner_name`, `owner_id`。

- [ ] **Step 1: 在 `tests/test_audit_logger.py` 中编写验证生命周期记录名称与 ID 的测试**

```python
    def test_log_lifecycle_with_names_and_ids(self):
        run_coro(self.logger.log_lifecycle(
            session_id="s123",
            context_key="s123:u456",
            owner_id="u456",
            event_type="create",
            operator_id="u456",
            session_name="测试群聊",
            operator_name="管理员张三",
            owner_name="管理员张三",
            details={"mode": "personal"}
        ))
        items, total = run_coro(self.logger.query_lifecycle_logs(keyword="张三"))
        self.assertEqual(total, 1)
        item = items[0]
        self.assertEqual(item["session_name"], "测试群聊")
        self.assertEqual(item["session_id"], "s123")
        self.assertEqual(item["operator_name"], "管理员张三")
        self.assertEqual(item["operator_id"], "u456")
        self.assertEqual(item["owner_name"], "管理员张三")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m unittest tests.test_audit_logger.TestAuditLogger.test_log_lifecycle_with_names_and_ids -v`  
Expected: FAIL (`TypeError: log_lifecycle() got an unexpected keyword argument 'operator_name'`)

- [ ] **Step 3: 改造 `core/audit_logger.py`**

1. 在 `_ensure_db` 中：
```python
    try:
        conn.execute("ALTER TABLE context_lifecycle_logs ADD COLUMN operator_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE context_lifecycle_logs ADD COLUMN owner_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
```
2. 升级 `log_lifecycle` 方法签名：
```python
    async def log_lifecycle(
        self,
        session_id: str,
        context_key: str,
        owner_id: str,
        event_type: str,
        operator_id: str,
        session_name: str = "",
        operator_name: str = "",
        owner_name: str = "",
        details: dict | list | str | None = None,
        custom_timestamp: str | None = None,
    ) -> None:
```
并在 `INSERT INTO context_lifecycle_logs` 中插入 `operator_name` 与 `owner_name`。
3. 升级 `query_lifecycle_logs` 的模糊搜索：匹配 `owner_name` 与 `operator_name`。

- [ ] **Step 4: 改造 `core/context_manager.py`**

1. `BrowserSessionContext` 增加 `session_name: str = ""` 与 `owner_name: str = ""`。
2. `resolve_context` 增加可选参数 `session_name: str = "", sender_name: str = ""`。
3. `_create_new_context` 将 `session_name` 与 `owner_name` 存入上下文实例，并在派发 `create` 生命周期记录时传入 `session_name`、`owner_name`、`operator_name`。
4. `get_active_contexts_detail` 返回的字典中增加 `session_name` 与 `owner_name` 键。

- [ ] **Step 5: 运行相关单元测试验证通过**

Run: `python -m unittest tests.test_audit_logger tests.test_context_manager -v`  
Expected: PASS

- [ ] **Step 6: 提交更改**

```bash
git add core/audit_logger.py core/context_manager.py tests/test_audit_logger.py
git commit -m "feat(lifecycle): enrich lifecycle logs and active contexts with session and user names"
```

---

### Task 4: 前端实时流式 Hook、堆栈展示与双重标识 UI 改造

**Files:**
- Create: `web-src/src/hooks/useAutoStream.ts`
- Modify:
  - `web-src/src/types.ts`
  - `web-src/src/components/SideDrawer.tsx`
  - `web-src/src/components/SideDrawer.module.css`
  - `web-src/src/components/TopAppBar.tsx`
  - `web-src/src/components/TopAppBar.module.css`
  - `web-src/src/views/AuditView.tsx`
  - `web-src/src/views/LifecycleView.tsx`
  - `web-src/src/views/LifecycleView.module.css`

**Interfaces:**
- Consumes: `useAutoStream(fetchFn, { enabled, intervalMs, canStream })`
- Produces: 
  - 侧抽屉展示多行异常堆栈与一键复制。
  - 工具审计与生命周期视图提供“⚡ 自动更新”开关及状态指示灯。
  - 生命周期视图全面呈现“会话名称+ID”与“人员名称+ID”。

- [ ] **Step 1: 更新 `web-src/src/types.ts`**

在 `LifecycleLogItem` 与 `ActiveContextItem` 中补齐 `operator_name?: string; owner_name?: string;`。

- [ ] **Step 2: 创建 `web-src/src/hooks/useAutoStream.ts`**

实现：
```typescript
import { useEffect, useRef, useState } from "react";

interface AutoStreamOptions {
  enabled: boolean;
  intervalMs?: number;
  canStream?: boolean; // 例如: page === 1 && !isDrawerOpen
  onStreamUpdate: () => void | Promise<void>;
  onBackgroundSync?: () => void | Promise<void>;
}

export function useAutoStream({
  enabled,
  intervalMs = 2500,
  canStream = true,
  onStreamUpdate,
  onBackgroundSync,
}: AutoStreamOptions) {
  const [isLiveActive, setIsLiveActive] = useState<boolean>(enabled);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    setIsLiveActive(enabled);
    if (!enabled) {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }

    timerRef.current = window.setInterval(async () => {
      try {
        if (canStream) {
          await onStreamUpdate();
        } else if (onBackgroundSync) {
          await onBackgroundSync();
        }
      } catch (err) {
        console.warn("[AutoStream] Poll error:", err);
      }
    }, intervalMs);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, intervalMs, canStream, onStreamUpdate, onBackgroundSync]);

  return { isLiveActive };
}
```

- [ ] **Step 3: 改造 `web-src/src/components/SideDrawer.tsx`**

1. 将 `item.error_message` 解析为首行概况 `errorSummary = (item.error_message || '').split('\n')[0]`，顶部黄色横幅仅显示 `errorSummary`。
2. 若 `item.error_message` 包含多行（或包含 `Traceback`），在入参框下方渲染专有堆栈区域：
```tsx
{item.is_error && item.error_message && item.error_message.includes("\n") && (
  <div>
    <div className={styles.sectionHeaderRow}>
      <span className={styles.sectionHeaderTitle} style={{ color: "var(--color-error)" }}>
        🚨 异常调用堆栈 (Stack Trace)
      </span>
      <button onClick={() => handleCopy(item.error_message, "traceback")} className={styles.copyBtn}>
        {copiedType === "traceback" ? "✓ 已复制堆栈" : "📋 复制完整堆栈"}
      </button>
    </div>
    <pre className={`${styles.codeBox} ${styles.stackTraceBox}`}>
      {item.error_message}
    </pre>
  </div>
)}
```
并在 `SideDrawer.module.css` 中增加 `stackTraceBox` 样式（红色边框微光，深色等宽字体）。

- [ ] **Step 4: 改造 `web-src/src/components/TopAppBar.tsx` 与 `AuditView.tsx`**

1. 在 `TopAppBar` 增加 `autoRefresh: boolean; onAutoRefreshChange: (val: boolean) => void;` 属性。
2. 在工具栏右侧增加带呼吸指示灯的勾选框：
```tsx
<label className={styles.autoRefreshLabel}>
  <input
    type="checkbox"
    checked={autoRefresh}
    onChange={(e) => onAutoRefreshChange(e.target.checked)}
  />
  <span className={`${styles.statusDot} ${autoRefresh ? styles.statusDotActive : ""}`} />
  自动更新
</label>
```
3. 在 `AuditView.tsx` 中使用 `useAutoStream`，当 `page === 1 && !selectedItem` 时执行 `loadLogs()`，否则仅静默执行 `loadStats()`。

- [ ] **Step 5: 改造 `web-src/src/views/LifecycleView.tsx`**

1. 顶部操作栏增加“⚡ 自动更新”勾选框与呼吸灯，通过 `useAutoStream` 驱动。
2. 表格中：
   - 上下文/会话列显示：`{log.context_key}`，下行显示 `💬 {log.session_name || "默认会话"} ({log.session_id})`。
   - 所有者/操作人列显示：
     `所有者: {log.owner_name ? `${log.owner_name} (${log.owner_id})` : log.owner_id}`
     `操作人: {log.operator_name ? `${log.operator_name} (${log.operator_id})` : log.operator_id}`。
   - 活跃上下文卡片同样展示双重标识。

- [ ] **Step 6: 构建前端静态资源并验证输出**

Run: `cd web-src && npm run build`  
Expected: 打包成功，更新生成 `views/browser/` 目录下相关 JS/CSS 资源。

- [ ] **Step 7: 提交前端更改**

```bash
git add web-src/ views/browser/
git commit -m "feat(ui): add auto-stream hook, stack trace drawer view and lifecycle dual identifiers"
```

---

### Task 5: 综合端到端与回归测试验证

**Files:**
- Modify: `tests/test_plugin_main.py`
- Run: `python -m unittest discover tests`

- [ ] **Step 1: 编写全链路模拟测试**

在 `tests/test_plugin_main.py` 中验证：
1. 异常触发时保存的完整堆栈能被 Web API 准确拉取。
2. 会话生命周期 Web API 能准确输出 `session_name`, `session_id`, `operator_name`, `operator_id`。

- [ ] **Step 2: 运行全量 Python 单元测试**

Run: `python -m unittest discover tests -v`  
Expected: 163+ 测试全部 PASS。

- [ ] **Step 3: 最终提交与版本收尾**

```bash
git add tests/
git commit -m "test: add integration test cases for audit stack trace and lifecycle metadata"
```
