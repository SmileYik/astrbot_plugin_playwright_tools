# PlaywrightTool (astrbot_plugin_playwright_tools)

基于 Playwright (首选 Camoufox 驱动) 的 AstrBot 浏览器自动化插件。
为大模型提供低 Token 消耗、高精准度的元素编号（Ref ID）交互与长页面分页阅读能力，具备完善的多租户隐私隔离、白名单防护与 SQLite 行为审计。

---

## 特性亮点

- **元素编号（Ref ID）与长页面分页**：精简 DOM 并为可操作元素赋予自增编号（如 `[1] <button>`），彻底规避大模型猜错选择器的问题；超过长度自动分页输出。
- **多租户隐私隔离**：
  - **个人模式**：上下文相互隔离，支持通过指令邀请好友协作。
  - **会话模式**：同一会话共享浏览器实例。
  - **空闲超时与指令释放**：超时自动销毁 Context，释放内存资源。
- **细粒度安全白名单**：支持域名通配符（如 `*.github.com`）与行为权限绑定（`read`, `click`, `fill`, `scroll`, `screenshot`, `download`）；拦截未授权的顶层跳转、弹窗与 iframe 导航。
- **Cookie 安全隔离**：支持注入标准 `storage_state.json`，且仅限定在管理员创建的上下文中生效，保护特权凭据。
- **行为审计**：SQLite 全要素记录工具调用的起止时间、会话、上下文、目标域名、入参与结果，支持过期自动清理。

---

## 插件指令

| 指令 | 说明 |
|---|---|
| `/browser invite <UID/@用户>` | 邀请目标用户加入当前个人浏览器协作 |
| `/browser use <UID/@用户>` | 显式切换当前会话绑定的操作目标浏览器 |
| `/browser close` | 关闭并释放属于自己的浏览器上下文 |
| `/browser status` | 查看当前绑定的浏览器状态与标签页信息 |

---

## 大模型工具列表 (LLM Tools)

- `open_url(url)`: 打开网页并输出首屏元素快照
- `read_page(page)`: 读取当前页面指定分页内容
- `click(ref)`: 点击指定 Ref ID 的元素
- `fill_form(ref, text)`: 在指定 Ref ID 的输入框填入文本
- `select_option(ref, value)`: 选取下拉框选项
- `scroll(direction, amount)`: 垂直滚动页面
- `switch_tab(tab_index)`: 切换浏览器标签页
- `take_screenshot(target)`: 网页截图 (`chat` 发送聊天，`ai` 返回 base64)
- `download_file(ref)`: 触发下载并将文件发送至会话
- `handle_dialog(action, prompt_text)`: 预设弹窗处理策略

---

## 依赖与安装

运行环境需 Python 3.10+，并建议安装 Camoufox：

```bash
pip install "camoufox[geoip]"
```
