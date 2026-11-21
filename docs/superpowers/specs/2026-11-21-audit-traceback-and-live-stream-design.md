# 设计文档：审计异常堆栈追溯、生命周期元信息增强与前端实时流式自动更新

**创建日期**：2026-11-21  
**状态**：待用户审批 (Pending Approval)  

---

## 1. 目标与背景 (Intent & Why)

在当前 AstrBot Playwright 工具插件使用中，存在两个阻碍调试的严重问题及一个迫切的前端交互增强需求：
1. **Markdown 内联模式崩溃**：`pw_read` 在提炼网页正文时抛出 `Page.evaluate: unterminated regular expression literal` 语法异常，导致页面阅读功能彻底失效。
2. **审计日志缺少异常堆栈**：当工具执行出错时，系统仅记录了 `str(e)` 浅层单行概况，开发者与审计员在 Web UI 中无法定位报错的文件、代码行数与调用链路。
3. **会话生命周期标识不完整**：在“会话生命周期管理”页面中，仅展示了单一 ID 或单一名称，缺少会话名称+会话 ID、发送者/操作者名称+发送者/操作者 ID 的完整组合展示。
4. **缺少实时流式自动更新**：在工具审计和生命周期管理两个视图中，用户必须手动点击“刷新状态”按钮才能获取最新记录，缺乏“自动更新”与实时流式呈现能力。

---

## 2. 目标与非目标 (Goals & Non-Goals)

### 目标 (Goals)
1. **彻底修复 JS 提取脚本语法**：确保 `InlineMarkdownReader` 生成的 JS 脚本转义合法，杜绝正则字面量换行报错。
2. **全量异常堆栈入库与展示 (方案 2.A)**：所有 Handler 在捕获异常时将完整的 `traceback.format_exc()` 写入 `error_message`。前端抽屉将首行作为概况，下方新增独立高亮代码块“异常堆栈详情 (Stack Trace)”及一键复制。
3. **生命周期元信息穿透与双重标识**：
   - 上下文管理器与生命周期审计表新增并持久化 `operator_name` 与 `owner_name`。
   - 前端表格与活跃卡片同时展示**会话名称 + 会话 ID** 与 **操作者/发送者名称 + 操作者/发送者 ID**。
4. **平滑流式“自动更新” (方案 3.A)**：
   - 提供通用 `useAutoStream` React Hook（默认 2.5 秒轮询间隔）。
   - 在“工具审计”与“会话生命周期”两个页面顶部均增加“⚡ 自动更新”开关及脉冲呼吸指示灯（🟢 实时同步中 / ⏸️ 已暂停）。
   - 交互遵循**方案 A（友好不打扰）**：若在第 1 页且未展开抽屉，新记录平滑推入顶部；若在第 2 页及之后或打开了详情抽屉，保持视图不跳动，仅更新统计指标并提示。

### 非目标 (Non-Goals)
- 不引入外部 WebSocket 服务或打破 AstrBot Bridge 通道；全部通信严格遵守 AstrBot Web API 鉴权。
- 不修改原有的工具调用安全白名单策略与权限鉴权逻辑。

---

## 3. 技术约束 (Constraints)
- **AstrBot Iframe Bridge 通道约束**：前端运行于 AstrBot Dashboard 的 iframe 内，所有数据请求必须经由 `AstrBotPluginViewBridge`（`apiGet` / `apiPost`），无法直接发起外层 WebSocket 或原生 EventSource 请求（后者会因缺少 Bearer Token 遭遇 401 拦截）。
- **兼容性约束**：SQLite 数据库变更必须使用 `ALTER TABLE ... ADD COLUMN` 并捕获 `OperationalError`，保证向后无损兼容已有的生产环境数据库。

---

## 4. 架构设计与实现方案 (Detailed Design)

### 4.1 模块 1：JS 正则表达式转义修复
- **文件**：`core/readers/markdown_reader.py`
- **修改点**：
  第 132 行将 `return node.nodeValue.replace(/[\r\n\t]+/g, ' ');` 替换为：
  ```javascript
  return node.nodeValue.replace(/[\\r\\n\\t]+/g, ' ');
  ```
  在 Python f-string 模板中，双反斜杠 `[\\r\\n\\t]` 格式化后为 `[\r\n\t]`，浏览器执行时即为合法的字符组转义，不会在 JS 解释器中被解析为物理换行符。

---

### 4.2 模块 2：全量异常堆栈（Traceback）持久化与抽屉展示

#### 1. 后端 Handler 异常捕获标准化
- **文件**：`tools/handlers/page_handler.py`, `tools/handlers/interact_handler.py`, `tools/handlers/media_handler.py`, `tools/tools.py`
- **逻辑**：
  当发生未捕获异常时，构造包含类型、概况与完整堆栈的字符串：
  ```python
  tb_full = traceback.format_exc()
  full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_full}" if tb_full else str(e)
  await self.audit_logger.log_action(
      ...,
      is_error=True,
      error_message=full_error,
      ...
  )
  ```
  在 `tools/tools.py` 的 `_execute_with_timeout` 出现未预期异常或超时时，同样补记审计日志。

#### 2. 前端详情抽屉（SideDrawer）UI 改造
- **文件**：`web-src/src/components/SideDrawer.tsx`, `web-src/src/components/SideDrawer.module.css`
- **视觉结构**：
  1. **顶部告警横幅**：仅提取 `item.error_message` 的首行（如 `Page.evaluate: unterminated regular expression literal`），保持顶部简洁清爽。
  2. **专属堆栈面板**：若包含多行堆栈，在“输出结果 / 快照内容”上方新增独立区域：
     - 标题行：“🚨 异常调用堆栈 (Stack Trace)” + “📋 复制完整堆栈”按钮。
     - 代码框：深色等宽字体滚动框，完整呈现 Python Traceback，方便即时排查。

---

### 4.3 模块 3：生命周期元信息双重标识（名称 + ID）

#### 1. 数据库升级与字段传递
- **文件**：`core/audit_logger.py`
  - 在 `context_lifecycle_logs` 表中新增 `operator_name TEXT DEFAULT ''` 与 `owner_name TEXT DEFAULT ''` 列（通过 `_ensure_db` 自动平滑升级）。
  - `log_lifecycle` 方法新增形参 `operator_name: str = ""` 与 `owner_name: str = ""`，并持久化至数据表。
  - `query_lifecycle_logs` 的模糊搜索关键字扩展至 `operator_name` 与 `owner_name`。

#### 2. 上下文管理器信息贯通
- **文件**：`core/context_manager.py`
  - `BrowserSessionContext` 数据类新增 `session_name: str = ""` 与 `owner_name: str = ""` 属性。
  - `resolve_context` 与 `_create_new_context` 接收外部传入的 `session_name` 与 `sender_name`。
  - 在派发 `create`、`close`、`switch`、`join` 等事件时，将正确的会话名称与人员名称送入 `log_lifecycle`。
  - `get_active_contexts_detail` 返回的每个活跃上下文对象中补充 `session_name` 与 `owner_name`。

#### 3. 前端生命周期视图渲染强化
- **文件**：`web-src/src/views/LifecycleView.tsx`
  - **活跃上下文卡片**：
    - 会话信息：`💬 会话: {ctx.session_name || "默认会话"} ({ctx.session_id})`
    - 所有者信息：`👤 所有者: {ctx.owner_name ? `${ctx.owner_name} (${ctx.owner_id})` : ctx.owner_id}`
  - **生命周期历史日志表格**：
    - “上下文 / 会话”列：
      - 上行：上下文 Key（蓝色等宽字体）
      - 下行：`{log.session_name || "未知会话"} ({log.session_id})`
    - “所有者 / 操作人”列：
      - 上行：`所有者: {log.owner_name ? `${log.owner_name} (${log.owner_id})` : log.owner_id}`
      - 下行：`操作人: {log.operator_name ? `${log.operator_name} (${log.operator_id})` : log.operator_id}`

---

### 4.4 模块 4：前端实时流式“自动更新” (Live Stream Auto-Update)

#### 1. 通用 Hook 封装：`useAutoStream`
- **文件**：`web-src/src/hooks/useAutoStream.ts`
- **功能特性**：
  - 参数：`fetchFn`（拉取函数）、`enabled`（是否勾选自动更新）、`intervalMs`（默认 2500ms）、`canStream`（是否允许当前视图置换，如 `page === 1 && !isDrawerOpen`）。
  - 当 `enabled === true` 时启动定时轮询。
  - 若 `canStream === true`：比对数据最新 ID，若有新记录流入，触发无缝平滑置换（带有微渐入动效），同时更新最新统计。
  - 若 `canStream === false`：挂起列表重绘，仅在后台静默更新统计指标（或展示悬浮气泡“有 N 条最新记录流入，回到首页即可查看”），杜绝打乱用户当前的翻页阅读或详情查看。

#### 2. 工具审计视图集成
- **文件**：`web-src/src/views/AuditView.tsx`, `web-src/src/components/TopAppBar.tsx`
- **UI**：顶部应用栏右侧操作区新增“⚡ 自动更新”复选框与脉冲状态指示灯（🟢 实时同步中 / ⏸️ 已暂停）。

#### 3. 会话生命周期视图集成
- **文件**：`web-src/src/views/LifecycleView.tsx`
- **UI**：顶部操作栏刷新按钮旁新增“⚡ 自动更新”复选框与实时指示灯，同时自动同步活跃上下文列表与事件轨迹日志。

---

## 5. 测试与验证方案 (Verification Plan)

### 自动化单元测试
1. **测试用例 1：`test_markdown_reader.py`**
   - 验证 `InlineMarkdownReader().get_js_extractor_script()` 不包含裸 `\r\n\t` 换行符，且在模拟浏览器环境中执行不会报错。
2. **测试用例 2：`test_audit_logger.py`**
   - 验证 `log_action` 能完整持久化多行异常堆栈。
   - 验证 `log_lifecycle` 能完整存储并查询 `session_name`、`operator_name` 与 `owner_name`。
3. **测试用例 3：`test_context_manager.py`**
   - 验证 `resolve_context` 携带元信息时，生命周期事件正确记录了人员与会话的名称及 ID。
4. **前端构建验证**：
   - 在 `web-src` 下运行 `npm run build`，确保 TypeScript 类型检查 100% 通过，并成功打包编译至 `views/browser/` 目录。

---

## 6. 确认与审批

以上设计完整覆盖了 Markdown 正则报错修复、异常完整堆栈追溯、生命周期名称+ID 双重展示，以及双页面的无打扰流式自动更新。
请审阅此方案，如您认可，请回复批准（例如“同意”或“Proceed”），我将立即为您进入测试用例与代码实施阶段！
