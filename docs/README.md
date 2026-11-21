# AstrBot Playwright 工具插件使用文档

基于 Playwright / Camoufox 的网页自动化插件，为大模型提供低 Token 消耗、高精准度的 DOM 交互与安全受控的浏览环境。

---

## 核心特性

- **三大聚合工具**：由原原子工具收敛为 `pw_page`、`pw_interact`、`pw_media`，采用 `FunctionTool` 类型化注册与统一前缀 `pw_`。
- **DOM 编号与快速检索**：自动为交互元素赋予自增 Ref ID（如 `[1] <button>`）；提供页面关键字快速搜索与自动分页截断。
- **完善的键鼠交互**：全面支持点击、输入、下拉选择、鼠标悬停、焦点管理（focus/blur）、元素拖拽、键盘按键及滚动。
- **双重截图熔断机制**：支持视口截图与全页长截图；长截图具备最大像素高度限制（超限截断）与超时回退（超时降级为视口截图）。
- **全局超时保护**：所有单工具执行均受超时保护，超时强制中断并返回友好提示。
- **提示词动态注入**：支持在请求大模型前动态追加自定义系统提示词。
- **安全白名单与行为审计**：支持域名通配符（如 `*.github.com`）与动作权限粒度校验；SQLite 全量记录调用起止、参数与结果。
- **多租户隐私隔离**：支持个人模式（隔离独立）与会话模式（共享共用），支持用户间授权协作与空闲资源自动回收。

---

## 用户指令

| 指令 | 说明 |
|---|---|
| `/browser invite <UID/@用户>` | 邀请目标用户协作当前属于自己的浏览器 |
| `/browser use <UID/@用户>` | 切换当前会话绑定的操作目标浏览器 |
| `/browser close` | 手动关闭并释放自己开启的浏览器上下文 |
| `/browser status` | 查看当前浏览器活跃上下文、网页及标签页状态 |

---

## 大模型工具规范 (LLM Tools)

所有工具均通过 AstrBot `context.add_llm_tools` 类型化注册，统一命名为 `pw_*`：

### 1. `pw_page` (页面控制与视图)
管理页面的打开、快照读取、关键字检索、标签页切换、弹窗响应及释放。

- **参数**：
  - `action` (string, 必填): `open` / `read` / `search` / `switch_tab` / `dialog` / `close`
  - `url` (string, 可选): 网页地址 (action=`open` 时必填)
  - `page` (integer, 可选): 分页页码，从 1 开始 (action=`read` 时可选，默认 1)
  - `keyword` (string, 可选): 页面检索关键词 (action=`search` 时必填)
  - `tab_index` (integer, 可选): 标签页序号 (action=`switch_tab` 时必填)
  - `dialog_action` (string, 可选): 弹窗响应策略 `'accept'` / `'dismiss'` (action=`dialog` 时可选)
  - `prompt_text` (string, 可选): 弹窗输入文本 (action=`dialog` 且为 prompt 时可选)

### 2. `pw_interact` (DOM 元素与键鼠交互)
针对页面元素执行点击、填充、下拉选择、悬停、聚焦/失焦、拖拽、按键与滚动。

- **参数**：
  - `action` (string, 必填): `click` / `fill` / `select` / `hover` / `focus` / `blur` / `drag` / `press_key` / `scroll`
  - `ref` (integer, 可选): 目标元素 Ref ID 编号
  - `text` (string, 可选): 输入文本 (action=`fill` 时必填)
  - `value` (string, 可选): 下拉选择值 (action=`select` 时必填)
  - `target_ref` (integer, 可选): 拖拽目标元素 Ref ID (action=`drag` 时必填)
  - `key` (string, 可选): 键盘按键名称如 `'Enter'`, `'Tab'` (action=`press_key` 时必填)
  - `direction` (string, 可选): 滚动方向 `'down'` / `'up'` (action=`scroll` 时可选，默认 `'down'`)
  - `amount` (integer, 可选): 滚动像素数 (action=`scroll` 时可选，默认 500)

### 3. `pw_media` (媒体交付与下载)
执行当前视口截图、全页面长截图或触发文件下载。

- **参数**：
  - `action` (string, 必填): `screenshot_viewport` / `screenshot_full` / `download`
  - `target` (string, 可选): 交付目标 `'chat'` (发送至聊天) 或 `'ai'` (base64 供视觉大模型分析，默认 `'chat'`)
  - `ref` (integer, 可选): 下载链接/按钮的 Ref ID 编号 (action=`download` 时必填)

---

## WebUI 配置说明 (`_conf_schema.json`)

配置已划分为 5 大业务分组，支持在 AstrBot WebUI 中折叠与展开：

### 1. 安全与权限 (`security`)
| 配置项 | 类型 | 默认值 | 作用描述 |
|---|---|---|---|
| `admin_only` | bool | `false` | 仅管理员可用 |
| `extra_admin_uids` | list (`sender_id`) | `[]` | 额外管理员 UID 列表（支持平台用户选择器） |
| `storage_state_path` | string | `""` | 管理员 Cookie/StorageState 凭据文件路径 |
| `whitelist_rules` | template_list | `[]` | 网站白名单与权限集合（可视化添加，支持通配域名与权限多选） |

### 2. 会话与运行时 (`runtime`)
| 配置项 | 类型 | 默认值 | 作用描述 |
|---|---|---|---|
| `context_mode` | string (select) | `"personal"` | 隔离模式：`personal` (个人隔离) 或 `session` (会话共享) |
| `idle_timeout_minutes` | int (slider) | `10` | 空闲自动销毁分钟数 (1~120 分钟) |
| `tool_execution_timeout_seconds` | int (slider) | `30` | 单个工具执行超时时间 (5~180 秒) |
| `enable_close_tool` | bool | `true` | 是否向 AI 注册主动关闭浏览器上下文的工具 |
| `system_prompt_injection` | text | `""` | 自定义系统提示词注入，留空则不注入 |

### 3. 浏览器引擎 (`browser`)
| 配置项 | 类型 | 默认值 | 作用描述 |
|---|---|---|---|
| `browser_adapter` | string (select) | `"camoufox"` | 浏览器适配器：`camoufox` (防检测) 或 `playwright` (原生引擎) |
| `playwright_browser_type` | string (select) | `"chromium"` | Playwright 核心类型：`chromium`, `firefox`, `webkit`, `custom` (选自定义时必填路径) |
| `browser_executable_path` | string | `""` | 自定义浏览器二进制文件绝对路径 |
| `camoufox_geoip` | bool | `false` | Camoufox 适配器是否开启 GeoIP 定位防检 |
| `browser_headless` | bool | `true` | 是否以无头模式运行浏览器 |
| `browser_window_width` | int (slider) | `1280` | 浏览器初始视口宽度 (800~3840 像素) |
| `browser_window_height` | int (slider) | `720` | 浏览器初始视口高度 (600~2160 像素) |
| `browser_user_agent` | string | `""` | 自定义 User-Agent，留空使用内置默认值 |

### 4. 截图与多媒体 (`media`)
| 配置项 | 类型 | 默认值 | 作用描述 |
|---|---|---|---|
| `screenshot_format` | string (select) | `"png"` | 截图输出格式：`png` (无损高清) 或 `jpeg` (压缩优化) |
| `screenshot_quality` | int (slider) | `80` | JPEG 压缩质量 (1~100，仅当格式为 jpeg 时显示) |
| `screenshot_max_height_px` | int (slider) | `8000` | 长截图最大允许高度 (1000~30000 像素)，超出自动截断 |
| `screenshot_timeout_seconds` | int (slider) | `15` | 长截图超时时间 (5~120 秒)，超时降级为视口截图 |
| `allow_screenshot_to_ai` | bool | `false` | 是否允许将网页截图发送给大模型进行视觉分析 |
| `element_multiline_separator` | string | `" \| "` | 页面元素内部换行分隔替换符 |

### 5. 存储与审计管理 (`storage_audit`, 默认折叠)
| 配置项 | 类型 | 默认值 | 作用描述 |
|---|---|---|---|
| `download_save_path` | string | `"data/downloads"` | 浏览器下载文件保存路径 |
| `screenshot_save_path` | string | `"data/screenshots"` | 截图文件保存路径 |
| `file_retention_days` | int (slider) | `7` | 下载与截图文件保留天数 (1~90 天) |
| `audit_retention_days` | int (slider) | `30` | 审计记录保存天数 (1~365 天) |
| `audit_max_output_chars` | int | `0` | 审计单条工具输出最大字符上限 (0 表示不限长度) |
| `audit_save_screenshots` | bool | `true` | 是否在审计数据库中关联持久化截图文件 |
