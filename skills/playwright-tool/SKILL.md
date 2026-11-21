---
name: playwright-tool
description: 网页浏览与自动化操作工具指南，指导 AI 如何通过 pw_page、pw_read、pw_interact 和 pw_media 安全高效地浏览网页、阅读结构化排版正文、定位检索信息、处理遮挡与执行交互。
---

# 网页浏览与交互指南 (Playwright Tools)

通过四大独立复合工具（`pw_page`、`pw_read`、`pw_interact`、`pw_media`）实现完整的网页浏览、检索与交互。

---

## 1. 核心工具与职责

| 工具名称 | 核心职责 |
|---|---|
| `pw_page` | 打开网址、切换标签页、预设响应浏览器弹窗与关闭浏览器上下文。 |
| `pw_read` | 读取当前页面结构化排版正文与带 Ref ID 的可交互元素快照，支持按页翻阅与关键词检索。 |
| `pw_interact` | 对快照中带有 Ref ID（形如 `'1'`, `'e1'` 等字符串标识）的元素执行点击、输入、下拉选择、鼠标悬停、焦点管理、拖拽、键盘按键或滚动。 |
| `pw_media` | 获取当前网页视口截图、全页面长截图或点击指定 Ref ID 触发文件下载。 |

---

## 2. 标准操作流程

### 步骤一：打开页面
调用 `pw_page(action='open', url='https://example.com')` 打开目标网址。
返回内容包含页面标题与第一页概览视图，末尾附带下一步操作建议。

### 步骤二：结构化正文阅读与快照提取 (`pw_read`)
调用 `pw_read` 获取页面内容与交互元素编号：
- **按页顺读**：`pw_read(page=1)`
  默认呈现内联交互 Markdown，正文排版（标题、段落、列表、表格）与带 Ref ID 的交互控件融为一体。若提示篇幅较长，按指引传入 `pw_read(page=2)` 继续阅读后续内容。
- **关键词检索**：`pw_read(keyword='关键词')`
  直接返回包含关键词的正文段落与临近控件 Ref ID，节省翻页 Token 消耗。
- **强制刷新快照**：`pw_read(refresh=True)`
  当页面经过点击或等待异步数据渲染完成后，强制重新提取最新快照。
- **Ref ID 格式说明**：
  Ref ID 是由阅读器生成的字符串标识符，支持纯数字编号（如 Markdown 模式下的 `'1'`, `'2'`）与语义标识（如 ARIA 模式下的 `'e1'`, `'e2'`）。所有交互参数均使用字符串格式传入。

### 步骤三：定位与交互 (`pw_interact`)
依据快照返回的专属字符串 Ref ID 执行键鼠操作：
- **点击**：`pw_interact(action='click', ref='1')`
- **输入文本**：`pw_interact(action='fill', ref='2', text='my_username')`
- **选择下拉**：`pw_interact(action='select', ref='3', value='option_val')`
- **悬停**：`pw_interact(action='hover', ref='4')` 触发下拉浮层或提示信息
- **聚焦 / 失焦**：`pw_interact(action='focus', ref='2')` 或 `pw_interact(action='blur', ref='2')`
- **拖拽**：`pw_interact(action='drag', ref='5', target_ref='6')` 将元素 `'5'` 拖动到元素 `'6'`
- **键盘按键**：`pw_interact(action='press_key', key='Enter')`
- **滚动页面**：`pw_interact(action='scroll', direction='down', amount=500)`

### 步骤四：视觉展示与下载 (`pw_media`)
- **截图展示**：
  - 聊天直发：`pw_media(action='screenshot_viewport', target='chat')`（当前视口）或 `pw_media(action='screenshot_full', target='chat')`（整页长图）。
  - 视觉分析：若需自身通过多模态分析图像细节，设置 `target='ai'`。
- **下载文件**：找到下载链接或按钮的 Ref ID，调用 `pw_media(action='download', ref='7')`。

### 步骤五：多标签页与弹窗控制 (`pw_page`)
- **切换标签页**：当点击链接在外部新窗口打开时，调用 `pw_page(action='switch_tab', tab_index=2)` 控制新标签。
- **响应弹窗**：遇到原生 Alert/Confirm 对话框时，调用 `pw_page(action='dialog', dialog_action='accept'|'dismiss')` 预设处理。
- **释放资源**：任务结束或用户要求关闭时，调用 `pw_page(action='close')` 销毁上下文。

---

## 3. 常见情况与处理策略

1. **坚持使用字符串 Ref ID**：所有元素交互必须使用快照中提取给出的字符串 Ref ID（如 `'1'`, `'e1'`），不要臆造 CSS 选择器或 XPath。
2. **页面弹窗遮挡拦截**：若操作返回“页面弹层遮挡拦截”提示，通常是因为网站弹出了 Cookie 同意、活动公告或登录模态框：
   - 查阅元素列表寻找关闭/确认按钮（如 `×`、`关闭`、`确定`、`Agree`），并调用 `pw_interact(action='click', ref='...')` 先行关闭。
   - 若是原生浏览器 Alert 对话框，调用 `pw_page(action='dialog', dialog_action='accept')`。
3. **页面跳转后需重新读取**：点击跳转或表单提交后，原有 Ref ID 失效，应调用 `pw_read(page=1)` 获取新快照。
4. **关注推荐操作指引**：每次操作工具的返回末尾均附有 `[推荐操作: ...]`，可依据提示决定下一步动作。
