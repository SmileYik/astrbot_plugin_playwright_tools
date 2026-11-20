---
name: playwright-tool
description: 网页浏览与自动化操作工具指南，指导 AI 如何通过 pw_page、pw_interact 和 pw_media 安全高效地浏览网页、阅读排版正文、检索信息、处理遮挡与执行交互。
---

# 网页浏览与交互指南 (Playwright Tools)

通过三大工具（`pw_page`、`pw_interact`、`pw_media`）实现完整的网页浏览、检索与交互。

---

## 1. 核心工具与职责

| 工具名称 | 核心职责 |
|---|---|
| `pw_page` | 打开网址、阅读正文/控件快照（支持按 target 独立分页阅读）、关键字检索、切换标签页、预设弹窗与关闭浏览器。 |
| `pw_interact` | 对快照中带有 Ref ID（形如 `[1]`, `[2]`）的元素执行点击、输入、下拉选择、鼠标悬停、焦点管理、拖拽、键盘按键或滚动。 |
| `pw_media` | 获取当前网页视口截图、全页面长截图或点击指定 Ref ID 触发文件下载。 |

---

## 2. 标准操作流程

### 步骤一：打开页面
调用 `pw_page(action='open', url='https://example.com')` 打开网页。
返回内容包含页面标题与第一页全局概览视图，末尾附带下一步操作指引。

### 步骤二：结构化正文阅读与控件分离（Target 模式）
为了避免文章正文与交互元素相互干扰，`pw_page(action='read')` 提供了独立的查看目标：
- **阅读文章正文**：`pw_page(action='read', target='text', page=1)`
  返回按 Markdown 排版（标题、段落、列表、表格）的纯净正文，排除杂乱控件干扰。若篇幅较长，按提示传入 `page=2` 查看后续章节。
- **获取操作元素**：`pw_page(action='read', target='elements', page=1)`
  返回当前页面的可操作元素列表及其专属 **Ref ID**（如 `[1] [按钮] 登录`、`[2] [输入框] 用户名`），元素多行文本内部已平整归一化。
- **全局对照**（默认）：`pw_page(action='read', target='all', page=1)`
  同时呈现正文前段与可操作控件。

### 步骤三：定位与交互
根据快照返回的 Ref ID 执行精准操作：
- **点击**：`pw_interact(action='click', ref=1)`
- **输入**：`pw_interact(action='fill', ref=2, text='my_username')`
- **选择下拉**：`pw_interact(action='select', ref=3, value='option_val')`
- **悬停**：`pw_interact(action='hover', ref=4)` 触发下拉菜单或提示
- **聚焦 / 失焦**：`pw_interact(action='focus', ref=2)` 或 `pw_interact(action='blur', ref=2)`
- **拖拽**：`pw_interact(action='drag', ref=5, target_ref=6)` 将元素 5 拖动到元素 6
- **键盘按键**：`pw_interact(action='press_key', key='Enter')`
- **滚动页面**：`pw_interact(action='scroll', direction='down', amount=500)`

### 步骤四：信息检索
- **定向检索**：`pw_page(action='search', keyword='关键字', target='all'|'text'|'elements')`
  直接返回包含关键词的正文段落或匹配的控件 Ref ID，大幅节省翻页 Token。

### 步骤五：视觉展示与下载
- **截图展示**：
  - 聊天直发：`pw_media(action='screenshot_viewport', target='chat')`（当前视口）或 `pw_media(action='screenshot_full', target='chat')`（整页长图）。
  - 视觉分析：若需自身分析图像内容，设置 `target='ai'`。
- **下载文件**：找到下载链接 Ref ID，调用 `pw_media(action='download', ref=7)`。

### 步骤六：完成与释放
任务结束或用户要求关闭时，调用 `pw_page(action='close')` 释放资源。

---

## 3. 常见情况与处理策略

1. **坚持使用 Ref ID**：所有元素交互必须使用快照中给出的 Ref ID，不要臆造选择器。
2. **页面弹窗遮挡拦截**：若操作返回“页面弹层遮挡拦截”提示，通常是因为网站弹出了 Cookie 同意、公告或登录模态框。处理方法：
   - 查阅元素列表寻找关闭/确认按钮（如 `×`、`关闭`、`确定`），并调用 `pw_interact(action='click', ref=...)` 先行关闭。
   - 或若是原生浏览器 Alert/Confirm 对话框，调用 `pw_page(action='dialog', dialog_action='accept'|'dismiss')` 预设处理。
3. **页面跳转后需重新读取**：点击跳转或刷新后，原有 Ref ID 失效，应调用 `pw_page(action='read')` 获取新快照。
4. **关注推荐操作指引**：每次操作工具的返回末尾均附有 `[推荐操作: ...]`，可依据提示决定下一步动作。
