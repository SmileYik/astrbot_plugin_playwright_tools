---
name: playwright-tool
description: 网页浏览与自动化操作工具指南，指导 AI 如何通过 pw_page、pw_interact 和 pw_media 安全高效地浏览网页、检索信息与执行交互。
---

# 网页浏览与交互指南 (Playwright Tools)

通过三大工具（`pw_page`、`pw_interact`、`pw_media`）实现完整的网页浏览、检索与交互。

---

## 1. 核心工具与职责

| 工具名称 | 核心职责 |
|---|---|
| `pw_page` | 打开网址、获取页面元素快照、关键字内容检索、切换标签页、预设弹窗与关闭浏览器。 |
| `pw_interact` | 对快照中带有 Ref ID（形如 `[1]`, `[2]`）的元素执行点击、输入、下拉选择、鼠标悬停、焦点管理、拖拽、键盘按键或滚动。 |
| `pw_media` | 获取当前网页视口截图、全页面长截图或点击指定 Ref ID 触发文件下载。 |

---

## 2. 标准操作流程

### 步骤一：打开页面与获取快照
调用 `pw_page(action='open', url='https://example.com')` 打开网页。
返回内容包含：
- 页面标题与当前 URL。
- 可交互元素列表及其专属 **Ref ID**（如 `[1] <button> 登录`、`[2] <input placeholder='用户名'>`）。
- 文本内容块（超出长度时提示分页）。

### 步骤二：定位与交互
根据快照返回的 Ref ID 执行精准操作：
- **点击**：`pw_interact(action='click', ref=1)`
- **输入**：`pw_interact(action='fill', ref=2, text='my_username')`
- **选择下拉**：`pw_interact(action='select', ref=3, value='option_val')`
- **悬停**：`pw_interact(action='hover', ref=4)` 触发下拉菜单或提示
- **聚焦 / 失焦**：`pw_interact(action='focus', ref=2)` 或 `pw_interact(action='blur', ref=2)`
- **拖拽**：`pw_interact(action='drag', ref=5, target_ref=6)` 将元素 5 拖动到元素 6
- **键盘按键**：`pw_interact(action='press_key', key='Enter')`
- **滚动页面**：`pw_interact(action='scroll', direction='down', amount=500)`

### 步骤三：信息获取与长页面阅读
- **快速检索**：若页面内容过长或需要查找特定词句，优先使用 `pw_page(action='search', keyword='关键字')` 直接获取匹配行与临近 Ref ID，避免逐页翻查。
- **分页读取**：如需顺序通读，使用 `pw_page(action='read', page=2)` 翻页。

### 步骤四：视觉展示与下载
- **截图展示**：
  - 聊天直发：`pw_media(action='screenshot_viewport', target='chat')`（当前视口）或 `pw_media(action='screenshot_full', target='chat')`（整页长图）。
  - 视觉分析：若需自身分析图像内容，设置 `target='ai'`。
- **下载文件**：找到下载链接 Ref ID，调用 `pw_media(action='download', ref=7)`。

### 步骤五：完成与释放
任务结束或用户要求关闭时，调用 `pw_page(action='close')` 释放资源。

---

## 3. 注意事项

1. **坚持使用 Ref ID**：所有元素交互必须使用快照中给出的 Ref ID，不要臆造选择器。
2. **页面跳转后需重新读取**：点击跳转或刷新后，原有 Ref ID 失效，应调用 `pw_page(action='read')` 获取新快照。
3. **敏感操作需谨慎**：表单提交、支付或下载操作前，先向用户核对关键信息。
