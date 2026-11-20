# 设计文档：工具异步执行修复、Web API 独立模块化与可视化日志拉取修复

## 1. 背景与意图 (Intent & Why)

在运行插件过程中出现了两项直接阻断用户体验的问题：
1. **大模型调用工具报错**：执行 `pw_page`、`pw_interact` 或 `pw_media` 工具时触发 `TypeError: object async_generator can't be used in 'await' expression`，导致智能体无法使用浏览器工具。
2. **可视化审计界面报错**：打开网页时一直提示“拉取日志失败”，虽然后端接口返回 200 OK，但前端未能正常渲染审计日志。
3. **架构优化诉求**：用户明确提出禁止将网页 Web API 代码混合在 `main.py` 中，要求新建独立模块承载。

本次改造旨在修复工具调用的协程机制、修复前端数据解包逻辑，并将 Web API 彻底剥离至独立模块 `api/audit_api.py`，保持架构清晰、职责单一。

---

## 2. 目标、非目标与反目标 (Goals, Non-goals & Anti-goals)

### 目标 (Goals)
1. **工具异步机制修复**：
   - 将 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 的 `call()` 方法恢复为普通异步协程（使用 `return res` 代替 `yield res`），确保兼容 AstrBot `FuncToolWrapper.call()` 的 `await` 调用。
   - 保留截图时若 `target == "chat"` 能够向用户会话推送图片消息的能力。
2. **Web API 模块化重构**：
   - 新建 `api/` 目录与 `api/audit_api.py` 模块，将所有与审计相关的 Web API（`api_audit_logs`、`api_audit_stats`、`api_audit_export`、`api_audit_clear`）移至该模块。
   - `main.py` 移除所有 Web API 实现代码及 `request`/`json_response` 等导入，改为实例化并调用新模块完成注册。
3. **前端日志拉取与操作修复**：
   - 修改 `web-src/src/App.tsx` 中的 API 响应解析逻辑，自适应 AstrBot Bridge 自动解包后的数据格式，同时向下兼容封装格式。
   - 保证日志列表加载、统计卡片显示、日志导出及清空功能全部恢复正常。
   - 执行前端构建并将更新后的产物写入 `views/audit/`。
4. **测试与规范更新**：
   - 修复或重构单元测试，确保 `tools` 和 `main` 的用例全部通过。
   - 依据 AGENT.md 规范更新目录说明及 CHANGELOG.md。

### 非目标 (Non-goals)
- 不改变审计日志数据表结构（SQLite 表结构保持不变）。
- 不改变前端 UI 界面视觉风格或新增除修复之外的功能特性。
- 不修改底层 Playwright/Camoufox 适配器与页面抽取核心算法。

### 反目标 (Anti-goals)
- 严禁把 Web API 继续留在 `main.py` 或回退到旧单文件设计。
- 严禁通过双层包装 `json_response({"code": 0, "data": {"code": 0, ...}})` 这种 hack 手段修补问题。

---

## 3. 约束 (Constraints)
- 遵循 [AGENT.md](../../../AGENT.md) 规范：
  - 简洁凝练，不啰嗦。
  - `web-src` 修改后必须重新构建并同步维护至 `views/audit`。
  - 项目目录结构需更新 `api/`。
  - 更新 CHANGELOG.md。
- 遵循 AstrBot Web API 与 Bridge 规范（支持 `context.register_web_api` 与 `AstrBotPluginView`）。

---

## 4. 方案选型与权衡 (Approaches)

### 方案 1：双向解耦与适配 + 新建 `api/audit_api.py` 模块（已选定，选项 A）
- **实现方式**：
  1. 新建 `api/audit_api.py`，定义 `AuditApiHandler` 统一封装审计路由逻辑。
  2. `main.py` 仅负责组装与调用 `AuditApiHandler.register_routes()`。
  3. 工具 `call()` 方法全部返回 `str`。
  4. `web-src/src/App.tsx` 做数据自适应读取。
- **优点**：
  - 职责界限分明，`main.py` 结构清爽。
  - 彻底解决 `async_generator` 无法被 await 的问题。
  - 前端稳健兼容 Bridge 解包与直接 HTTP 调用。
- **缺点**：需要新增目录与重新构建前端。

### 方案 2：仅局部修改（在 `main.py` 保留 API 并 hack 数据外层结构）
- **实现方式**：保持 `main.py` 不变，仅在 `main.py` 中把返回值套多一层，工具中只改 `return`。
- **缺点**：用户明确拒绝“把网页 API 放在 `main.py`”，且违反优雅设计原则。

---

## 5. 详细设计 (Detailed Design)

### 5.1 后端 Web API 模块 (`api/audit_api.py`)
- 定义 `AuditApiHandler` 类：
  ```python
  class AuditApiHandler:
      def __init__(self, audit_logger: AuditLogger):
          self.audit_logger = audit_logger

      def register_routes(self, context: Any, plugin_name: str) -> None:
          # 注册 4 个路由
          ...

      async def api_audit_logs(self): ...
      async def api_audit_stats(self): ...
      async def api_audit_export(self): ...
      async def api_audit_clear(self): ...
  ```
- 异常与回退处理：内置 `json_response`、`error_response`、`request` 降级支持，防止在独立测试环境下导包报错。

### 5.2 `main.py` 精简
- 导入 `from .api.audit_api import AuditApiHandler`。
- 移除 70+ 行 Web API 逻辑与相关的请求工具导入。
- 在 `PlaywrightToolPlugin.__init__` 中实例化并注册。

### 5.3 工具类修复 (`tools/tools.py`)
- `PwPageTool.call`：
  - 执行 `handler`，获取 `res`，`return res`。
- `PwInteractTool.call`：
  - 执行 `handler`，获取 `res`，`return res`。
- `PwMediaTool.call`：
  - 执行 `handler`，获取 `res`。
  - 若 `target == "chat"` 且包含图片路径，通过 `event.send(...)` 发送图片。
  - 最后 `return res`。

### 5.4 前端数据适配 (`web-src/src/App.tsx`)
- `fetchLogs`：
  ```typescript
  const data = (res && Array.isArray((res as any).items)) ? res : (res?.data ?? res);
  if (data && Array.isArray(data.items)) {
    setLogs(data.items || []);
    setTotal(data.total || 0);
  } else {
    showBanner(res?.message || "拉取日志失败", "error");
  }
  ```
- `fetchStats`：自适应读取 `res.total !== undefined ? res : res.data`。
- `handleExport`：自适应解析字符串内容 `typeof res === "string" ? res : res?.data`。
- `handleClear`：自适应判断 `res?.cleared !== undefined || res?.code === 0`。
- 执行 `npm run build`，编译生成产物至 `views/audit/`。

---

## 6. 构建与验证计划 (Verification Plan)
1. **单元测试验证**：
   - 运行针对 `api/audit_api.py` 和 `main.py` 的测试。
   - 运行针对 `tools/tools.py` 协程调用的测试。
2. **前端编译验证**：
   - 验证 `web-src` 构建无 TS 报错，`views/audit` 正确刷新静态资源。
3. **文档同步验证**：
   - 检查 `AGENT.md`、`CHANGELOG.md` 更新。
