# AI 工具能力文档 (LLM Tools Reference)

本插件向大模型注册四大复合工具（`pw_page`、`pw_read`、`pw_interact`、`pw_media`），所有工具均通过 `_actions` 字典分发并受全局超时保护。

---

## 1. 工具体系与参数说明

### 1.1 `pw_page`（页面生命周期与标签页管理）
管理网页打开、标签页查询与切换、原生弹窗响应及浏览器上下文释放。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action` | string | 是 | `'open'`（打开网址；支持 HTML 网页、多模态图片直链、分页纯文本及二进制元信息分流）、`'switch_tab'`（切换标签页）、`'list_tabs'`（列出当前活动及所有已打开标签页）、`'dialog'`（响应弹窗）、`'close'`（关闭当前浏览器上下文） |
| `url` | string | 条件 | 目标网页 URL（`action='open'` 时必填） |
| `tab_index` | integer | 条件 | 目标标签页序号，从 1 开始（`action='switch_tab'` 时必填） |
| `dialog_action` | string | 条件 | 弹窗处理策略：`'accept'`（确认）或 `'dismiss'`（取消）（`action='dialog'` 时必填） |
| `prompt_text` | string | 否 | Prompt 弹窗输入文本（`action='dialog'` 时可选） |

### 1.2 `pw_read`（结构化正文提炼与 Ref 查询）
提取当前活动页面的结构化快照，支持分页阅读、关键词检索、强制刷新以及按 Ref 查询元素真实链接与图片地址。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page` | integer | 否 | 分页页码，从 1 开始（默认 `1`） |
| `keyword` | string | 否 | 关键词检索，返回匹配行及上下文 |
| `ref` | string | 否 | 查询指定元素 Ref 的类型、标题、完整 `href` 或 `src`（支持跨标签页自动切回） |
| `refresh` | boolean | 否 | 是否强制刷新重新提取当前页快照（默认 `false`） |

### 1.3 `pw_interact`（键鼠与表单交互）
基于快照中的 Ref ID 执行 Playwright 原生 Locator 交互。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action` | string | 是 | `'click'`、`'fill'`、`'select'`、`'hover'`、`'focus'`、`'blur'`、`'drag'`、`'press_key'`、`'scroll'` |
| `ref` | string | 条件 | 目标元素 Ref ID（`press_key` 与 `scroll` 除外） |
| `text` | string | 条件 | 输入文本内容（`action='fill'` 时必填，密码框自动脱敏） |
| `value` | string | 条件 | 下拉框选项值或标签（`action='select'` 时必填） |
| `target_ref` | string | 条件 | 拖拽放置目标元素 Ref ID（`action='drag'` 时必填，须与 `ref` 位于同一标签页） |
| `key` | string | 条件 | 按键名称，如 `'Enter'`、`'Tab'`、`'Escape'`（`action='press_key'` 时必填） |
| `direction` | string | 否 | 滚动方向：`'down'` 或 `'up'`（默认 `'down'`） |
| `amount` | integer | 否 | 滚动像素距离（默认 `500`） |

### 1.4 `pw_media`（截图与文件下载）
截取当前视口或整页长图，或点击指定 Ref 触发文件下载。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action` | string | 是 | `'screenshot_viewport'`（视口截图）、`'screenshot_full'`（整页长截图）、`'download'`（触发文件下载） |
| `target` | string | 否 | 截图交付目标：`'chat'`（发送至会话）或 `'ai'`（通过 `CallToolResult` 返回多模态 `ImageContent` 供 AI 识图，默认 `'chat'`） |
| `ref` | string | 条件 | 触发下载的链接或按钮 Ref ID（`action='download'` 时必填） |

---

## 2. 核心工作机制

### 2.1 Ref ID 生成与按页隔离 (`PageState`)
- **全局单调递增编号**：上下文维护单调递增计数器（达到 `1,000,000` 回滚为 `1`）。`InlineMarkdownReader` 生成 `@r` 前缀编号（如 `'@r1'`）；`AriaSnapshotReader` 将原生 `aria-ref` 重映射为单调递增数字编号（如 `'1'`），并在内部保留 `aria_ref` 字段用于 Locator 定位。
- **按标签页独立存储**：每个标签页通过 `PageState` 独立维护 `ref_map`、`current_snapshot` 与 `is_snapshot_dirty`。`switch_tab` 与其他标签页导航不会清除未操作标签页的 `ref_map`。
- **跨标签页自动寻址**：调用任何带 `ref` 的工具时，`BaseActionHandler` 优先检索当前活动页；若未命中则遍历同上下文其他存活标签页，命中后自动将其切换为当前活动页并执行鉴权与操作。

### 2.2 智能回复引导与状态通知
- **权限拒绝指引**：当当前页面无权执行某项操作时，鉴权失败消息会综合白名单规则与单跳授权，自动附带 `[当前页面可执行操作: pw_read()、...]` 指引；若当前页无可用操作，则提示调用 `pw_page(action='list_tabs')` 查看并切换其他标签页或打开允许的网址。
- **标签页变更通知**：当操作触发新标签页打开或活动标签页切换时，回复末尾自动附带 `[标签页通知: ...]`（含当前页序号、总数、标题与 URL）；`pw_page(action='open')` 也会明确返回当前所在标签页位置。
