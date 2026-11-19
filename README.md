# PlaywrightTool (astrbot_plugin_playwright_tools)

基于 Playwright (首选 Camoufox 驱动) 的 AstrBot 浏览器自动化插件。
为大模型提供低 Token 消耗、高精准度的元素编号（Ref ID）交互与长页面分页阅读能力，具备完善的多租户隐私隔离、白名单防护与 SQLite 行为审计。

---

## 特性亮点

- **三大聚合复合工具**：收敛为 `pw_page`、`pw_interact`、`pw_media`，采用 `FunctionTool` 类型化注册与统一前缀 `pw_`。
- **元素编号（Ref ID）与快速搜索**：精简 DOM 并为可操作元素赋予自增编号（如 `[1] <button>`），提供长页面分页与关键词快速检索。
- **全面键鼠交互**：全面支持点击、输入、下拉选择、鼠标悬停、焦点管理（focus/blur）、元素拖拽、键盘按键及滚动。
- **双重截图熔断机制**：支持视口截图与全页长截图；长截图具备最大像素高度限制（超限截断）与超时回退（超时降级为视口截图）。
- **全局超时保护**：所有单工具执行均受超时保护，超时强制中断并返回。
- **提示词动态注入**：支持在请求大模型前动态追加自定义系统提示词。
- **多租户隐私隔离**：
  - **个人模式**：上下文相互隔离，支持通过指令邀请好友协作与手动关闭释放。
  - **会话模式**：同一会话共享浏览器实例。
  - **空闲超时与指令释放**：超时自动销毁 Context，释放内存资源。
- **细粒度安全白名单**：支持域名通配符（如 `*.github.com`）与行为权限绑定（`read`, `click`, `fill`, `scroll`, `screenshot`, `download`）；拦截未授权的顶层跳转、弹窗与 iframe 导航。
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

所有工具均通过 AstrBot `context.add_llm_tools` 类型化注册，统一命名为 `pw_*`：

- **`pw_page`**：页面导航与快照（打开、读取、关键词搜索、标签页切换、弹窗响应、关闭）。
- **`pw_interact`**：元素与按键交互（点击、输入、下拉框选择、悬停、聚焦、失焦、拖拽、键盘按键、滚动）。
- **`pw_media`**：媒体交互（当前视口截图、全页面长截图、触发文件下载）。

详细文档请参见 [docs/README.md](docs/README.md) 与 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 依赖与安装

运行环境需 Python 3.10+，并建议安装 Camoufox：

```bash
pip install "camoufox[geoip]"
```
