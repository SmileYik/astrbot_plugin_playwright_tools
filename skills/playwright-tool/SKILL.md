---
name: playwright-tool
description: 指导 AI 使用 pw_page、pw_read、pw_interact 与 pw_media 工具进行网页浏览、正文阅读、信息检索、元素交互与媒体操作。
---

# 网页浏览与交互指南 (Playwright Tools)

通过四大独立工具（`pw_page`、`pw_read`、`pw_interact`、`pw_media`）实现完整的网页浏览、检索与交互。

---

## 1. 核心工具职责

| 工具名称 | 核心职责 | 典型调用场景 |
|---|---|---|
| `pw_page` | 页面生命周期与窗口控制 | 打开网址、切换标签页、处理原生弹窗、关闭浏览器上下文 |
| `pw_read` | 结构化正文阅读与快照提取 | 提取正文内容、按页顺读、关键词检索、查询指定元素详情与 URL |
| `pw_interact` | 元素交互与键鼠操作 | 点击、输入、选择下拉、悬停、焦点切换、拖拽、键盘按键、页面滚动 |
| `pw_media` | 截图与文件下载 | 获取当前视口截图、整页长截图、触发文件下载 |

---

## 2. 标准操作流程

### 步骤一：打开页面 (`pw_page`)
- 打开网址：`pw_page(action='open', url='https://example.com')`
- 打开成功后返回页面标题与状态。该操作不直接返回正文内容，需执行步骤二获取页面快照。

### 步骤二：阅读页面内容与提取元素 (`pw_read`)
调用 `pw_read` 获取结构化正文与带编号（Ref ID）的可交互元素。

1. **按页顺读**：`pw_read(page=1)`
   - **排版格式**：正文以 Markdown 呈现，交互元素嵌入正文中，采用原生引用风格编号（相邻交互控件以空格分隔）：
     - 超链接：`[链接文本][Ref]`（如 `[新手指南][@r12]`）
     - 按钮与交互控件：`[控件类型: 文本][Ref]`（如 `[按钮: 搜索][@r15]`、`[输入框 (text): 请输入账号][@r16]`）
     - 图片：`![图片描述][Ref]`
   - **长表格阅读**：若表格跨页截断，后续分页顶部会自动保留原表头行与分隔线，以保持列上下文。
   - **翻页机制**：单次返回一个分页。若末尾提示存在剩余页数，可传入 `pw_read(page=2)` 顺次阅读。
2. **关键词检索**：`pw_read(keyword='搜索词')`
   - 当页面篇幅较长且目标明确时，直接定位包含关键词的正文段落与临近控件 Ref，无需逐页翻阅。
3. **查询元素详情与真实 URL**：`pw_read(ref='@r12')`
   - 快照正文中默认剥离长 URL。如需获取特定超链接的跳转地址、图片下载地址（src）或控件完整属性，传入对应 Ref 字符串进行定向查询。
4. **强制刷新**：`pw_read(refresh=True)`
   - 当完成交互操作（如点击提交、加载更多）或等待异步数据加载后，强制重新提取页面最新快照。

> **Ref ID 说明**：所有 Ref 均为由阅读器分配的字符串标识符（Markdown 模式为 `@r` 前缀如 `'@r1'`、`'@r12'`，ARIA 模式为 `'e1'`）。后续工具交互传参时必须传入完整字符串（如 `'@r12'`）以精确匹配。

### 步骤三：元素定位与交互 (`pw_interact`)
依据快照中获取到的 Ref 编号执行键鼠交互：
- **点击**：`pw_interact(action='click', ref='@r15')`
- **输入文本**：`pw_interact(action='fill', ref='@r16', text='目标内容')`
- **选择下拉选项**：`pw_interact(action='select', ref='@r18', value='option_value')`
- **鼠标悬停**：`pw_interact(action='hover', ref='@r20')`（触发悬浮菜单或浮层）
- **聚焦 / 失焦**：`pw_interact(action='focus', ref='@r16')` / `pw_interact(action='blur', ref='@r16')`
- **拖拽**：`pw_interact(action='drag', ref='@r21', target_ref='@r22')`
- **按键**：`pw_interact(action='press_key', key='Enter')`（常用键如 `'Enter'`, `'Tab'`, `'Escape'`）
- **滚动页面**：`pw_interact(action='scroll', direction='down', amount=500)`（`direction` 可选 `'down'` 或 `'up'`）

### 步骤四：多媒体与文件获取 (`pw_media`)
- **生成截图**：
  - 发送至当前聊天：`pw_media(action='screenshot_viewport', target='chat')`（当前视口）或 `pw_media(action='screenshot_full', target='chat')`（整页长图）
  - 自身多模态理解：设置 `target='ai'`，以 base64 图像供模型分析
- **文件下载**：定位到下载链接或按钮的 Ref 编号后，调用 `pw_media(action='download', ref='@r25')`

### 步骤五：多标签页、弹窗与资源释放 (`pw_page`)
- **切换标签页**：当点击链接导致外部新窗口打开时，调用 `pw_page(action='switch_tab', tab_index=2)`
- **响应弹窗**：页面触发原生 JavaScript Alert/Confirm 时，调用 `pw_page(action='dialog', dialog_action='accept'|'dismiss')` 预设处理
- **关闭浏览器**：任务全部完成或用户明确要求结束时，调用 `pw_page(action='close')` 释放资源

---

## 3. 常见场景处理策略

1. **坚持使用快照给出的 Ref 编号**：禁止自行猜测选择器或 XPath，所有交互均基于快照返回的有效字符串 Ref。
2. **页面弹层遮挡**：若操作提示目标元素被遮挡，通常是页面弹出了 Cookie 协议、登录窗口或通知浮层：
   - 查阅当前快照寻找关闭按钮（如 `[按钮: 关闭][Ref]`、`[按钮: 同意][Ref]`），调用 `pw_interact(action='click', ref='...')` 先行关闭；
   - 若是原生浏览器弹窗，调用 `pw_page(action='dialog', dialog_action='accept')`。
3. **页面跳转与状态变化**：点击链接或提交表单后，原有 Ref 失效，必须重新调用 `pw_read(page=1)` 获取最新快照再继续后续操作。
4. **参考返回建议**：工具执行后末尾附带的 `[推荐操作: ...]` 提供了针对当前执行结果的上下文建议，可作为下一步行动的依据。
