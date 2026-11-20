# 变更日志 (CHANGELOG)

本项目遵循语义化版本规范。

---

## [v2.1.1] - 2026-11-20

### 修复与重构 (Bug Fixes & Refactoring)
- **修复工具协程调用异常**：修复 `tools/tools.py` 中 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 的 `call()` 方法误用异步生成器（`yield`）导致 AstrBot `FuncToolWrapper.call()` 执行抛出 `TypeError: object async_generator can't be used in 'await' expression` 的问题，全面恢复为标准协程（`return`）。截图直发聊天场景改为异步调用 `event.send` 推送图片，同时返回说明文本给大模型。
- **Web API 独立模块化重构**：根据单一职责原则，将原写在 `main.py` 中的审计相关 Web API 路由与业务逻辑（`api_audit_logs`、`api_audit_stats`、`api_audit_export`、`api_audit_clear`）彻底剥离至新建的独立模块 `api/audit_api.py`，`main.py` 仅负责实例化与路由委托挂载。
- **前端 Bridge 响应自适应与构建刷新**：修复 `web-src/src/App.tsx` 在接收 AstrBot Bridge 解包数据时因硬编码检查 `res.code === 0` 导致一直报错“拉取日志失败”的问题，全面自适应 Bridge 解包后的对象结构与标准包裹结构，并重新执行构建将更新后的静态资源同步更新至 `views/audit/`。

---

## [v2.1.0] - 2026-11-20

### 新增与增强 (Features & Enhancements)
- **可视化审计视图 (Visual Audit View)**：在 `metadata.yaml` 声明独立插件页面（`target: plugin_page`），源码采用 Yarn + Vite + React 18 + TS 组织于 `web-src/` 并编译至 `views/audit/`。
- **Material Design 3 大圆角交互设计**：自研轻量级 MD3 组件，采用 16~24px 大圆角与表面色彩体系，自适应 AstrBot 宿主深浅色主题。
- **长文本两行截断预览与右侧抽屉检视**：列表卡片以代码块展示入参单行摘要与输出前 2 行文本，点击任意卡片从右侧平滑滑出大圆角抽屉（Side Drawer Inspector），支持格式化 JSON 树展示、完整结果换行检视与一键快捷复制。
- **审计数据增强与全链路透传**：工具调用链路中纯内存被动探测群聊名称与发送者昵称（私聊标记为 `私聊: {sender_name}`），全链路透传写入 SQLite 审计表。
- **运维与统计管理 Web API**：通过 `context.register_web_api` 注册多维条件检索（`/audit/logs`）、实时指标统计（`/audit/stats`）、全量/筛选日志导出（`/audit/export`，支持 JSON 与 RFC 4180 CSV）及带二次确认的安全清空（`/audit/clear`）。

---

## [v2.0.1] - 2026-11-19

### 优化与重构 (Refactoring)
- **工具方法字典映射分发**：彻底移除 `tools/tools.py` 中三大工具 `call()` 内的 `if-elif-else` 长分支，重构为通过 `self._actions` 字典映射到私有动作方法。
- **统一异步生成器产出**：所有复合工具的 `call()` 统一设计为异步生成器（`yield` 产出结果）。
- **截图消息直发防覆盖**：`pw_media` 截图发送给聊天用户时，改用 `yield event.image_result(path)` 直接交付且立即退出，不再返回额外文本，防止后续消息在聊天界面覆盖图片。

---

## [v2.0.0] - 2026-11-19

### 新增与重构 (Features & Enhancements)
- **类型化大工具聚合**：由分散的原子工具收敛为三大面向对象复合工具（`pw_page`、`pw_interact`、`pw_media`），继承 AstrBot `FunctionTool` 规范并通过 `context.add_llm_tools` 统一以 `pw_` 前缀注册。
- **高级交互操作补齐**：补齐鼠标悬停（`hover`）、元素聚焦（`focus`）、元素失焦（`blur`）、元素拖拽（`drag`）及键盘按键（`press_key`）支持。
- **双重截图熔断机制**：提供视口截图（`screenshot_viewport`）与全页面长截图（`screenshot_full`）；长截图支持配置最大高度限制（默认 8000px，超限截断）与超时熔断（默认 15s，超时自动降级为视口截图）。
- **单工具执行全局超时保护**：每个工具调用封装 `asyncio.wait_for` 超时拦截（默认 30s），超时立即强制中断并返回友好反馈。
- **系统提示词动态注入**：增加 WebUI 配置项 `system_prompt_injection`，通过 `@filter.on_llm_request()` 钩子在大模型请求前动态注入（留空则不注入）。
- **页面内容关键字检索**：新增 `search_page` 动作与 `PageExtractor.search_snapshot` 算法，支持快速搜索包含目标词的文本块及邻近 Ref ID。
- **多租户隔离与权限审计**：
  - 支持个人隔离模式与会话共享模式，提供 `/browser invite/use/close/status` 管理指令。
  - 支持域名通配符与动作级白名单管控。
  - SQLite 记录全生命周期审计日志并支持周期性自动清理。
