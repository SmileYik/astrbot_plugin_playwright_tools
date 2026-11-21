# 插件配置 WebUI 体验升级与分组重构设计规范

## 1. 概述与背景 (Intent & Why)

当前 `astrbot_plugin_playwright_tools` 插件的 `_conf_schema.json` 采用扁平文本与数字输入结构，在 AstrBot WebUI 呈现上存在多处体验痛点：
1. **配置项命名冗长或包含括号说明**：原 description 中直接混入了 `(多个以逗号分隔)`、`(personal: 个人模式...)` 等格式要求，界面视觉杂乱。
2. **缺乏可视化选择控件**：管理员 UID 依赖逗号分隔字符串容易输错；隔离模式、浏览器类型和截图格式均为手填文本，缺少下拉框防呆校验。
3. **缺乏滑块调节**：空闲销毁时间、工具执行超时、长截图限制等常用时长与尺寸数值无法直接拉杆拖拽。
4. **网站白名单依赖手写 JSON**：用户必须在文本框中手动填写符合 JSON 规范的数组字符串 `[{"domain": "...", "allowed_actions": [...]}]`，门槛高且极易因标点错误导致解析失败。
5. **缺少上下文联动**：例如未选中 JPEG 时依然展示压缩质量选项；非 Playwright 适配器下仍展示 Playwright 浏览器选项；选择自定义浏览器内核时缺乏必填路径约束。
6. **29 项配置平铺无层级**：所有选项挤在同一个列表，缺乏业务维度分组。

本设计旨在严格遵循 AstrBot 官方插件配置开发规范（`third-part-reference/AstrBot/docs/zh/dev/star/guides/plugin-config.md`），将表单重构为**业务分组 + 智能条件联动 + 现代化控件（用户选择器、模板列表、下拉框、滑块）**的高可用易用形态。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **规范化分组结构**：通过 AstrBot 的 `type: "object"` 将 29 项配置划分为 5 大业务逻辑组：
   - `security`（安全与权限）
   - `runtime`（会话与运行时）
   - `browser`（浏览器引擎）
   - `media`（截图与交互输出）
   - `storage_audit`（存储与审计管理）
2. **满足 9 项精准控件需求**：
   - 额外管理员 UID 使用 `_special: "sender_id"` 用户选择器。
   - 上下文隔离模式使用带 `labels` 与 `subtitles` 的单选下拉框。
   - 空闲销毁时间、工具执行超时使用 `slider`（滑块与数字输入框联动）。
   - 长截图高度限制与超时时间使用 `slider`。
   - 网站白名单采用 `template_list`，内含域名文本框与操作权限多选下拉框。
   - 浏览器适配器使用单选下拉框。
   - Playwright 原生浏览器支持 `chromium`、`firefox`、`webkit` 和 `custom`（其他），当选择 `custom` 时强制校验并填入可执行文件路径。
   - 截图格式使用下拉框，且压缩质量仅在选择 `jpeg` 时动态展现。
   - 压缩质量使用 `slider`（1~100）。
3. **文案极致清晰简明**：`description` 采用简洁直观的 2~6 字短标题，将原有长说明与用法归纳至 `hint`，下拉选项附加详细 `subtitles`。
4. **纯粹清晰的现代架构**：由于当前插件无外部存量生产用户，彻底摒弃历史遗留包袱与兼容垫片，插件配置直接按标准的分组结构原生读取，代码极其干净。

### 非目标 (Non-Goals)
- 不改变插件底层的鉴权逻辑、拦截器逻辑与浏览器驱动行为。
- 不引入外部前端库，完全利用 AstrBot WebUI 原生支持的配置规范与控件。
- 不提供旧版扁平配置向后兼容垫片与磁盘历史迁移程序。

### 反目标 (Anti-Goals)
- 严禁在白名单或权限配置中硬编码限制未来可能扩充的操作动作。
- 严禁残留冗余无用的历史过渡兼容代码。

---

## 3. 技术方案与技术决策 (Approaches & Trade-offs)

### 3.1 方案选型
鉴于当前无生产存量用户负担，直接采用**现代标准业务分组 + 智能条件联动 (Grouped Schema with Smart Conditionals)**：
- 在 `_conf_schema.json` 采用 5 大业务分组（`type: "object"`），并在各分组内利用 `condition` 动态显示子选项（如 `media` 组内 `screenshot_quality` 仅在 `screenshot_format == "jpeg"` 显示；`browser` 组内 `browser_executable_path` 仅在 `playwright_browser_type == "custom"` 显示）。
- 插件后端（`main.py` 与 `adapts/factory.py`）直接原生按对应分组提取配置，不再需要复杂的跨层级兼容探测与磁盘预迁移代码。
- 自动化测试与默认测试数据全面切换至分组结构，确保工程整洁统一。

---

## 4. 详细设计与技术规格 (Detailed Design)

### 4.1 Schema 结构规划 (`_conf_schema.json`)

整个配置文件划分为 5 个顶层 `type: "object"` 分组：

```
root
├── security (安全与权限)
│   ├── admin_only [bool]
│   ├── extra_admin_uids [list, _special: "sender_id"]
│   ├── storage_state_path [string]
│   └── whitelist_rules [template_list]
├── runtime (会话与运行时)
│   ├── context_mode [string (select: personal | session)]
│   ├── idle_timeout_minutes [int (slider: 1-120)]
│   ├── tool_execution_timeout_seconds [int (slider: 5-180)]
│   ├── enable_close_tool [bool]
│   └── system_prompt_injection [text]
├── browser (浏览器引擎)
│   ├── browser_adapter [string (select: camoufox | playwright)]
│   ├── playwright_browser_type [string (select: chromium | firefox | webkit | custom), condition: browser_adapter == "playwright"]
│   ├── browser_executable_path [string, condition: playwright_browser_type == "custom"]
│   ├── camoufox_geoip [bool, condition: browser_adapter == "camoufox"]
│   ├── browser_headless [bool]
│   ├── browser_window_width [int (slider: 800-3840)]
│   ├── browser_window_height [int (slider: 600-2160)]
│   └── browser_user_agent [string]
├── media (截图与交互输出)
│   ├── screenshot_format [string (select: png | jpeg)]
│   ├── screenshot_quality [int (slider: 1-100), condition: screenshot_format == "jpeg"]
│   ├── screenshot_max_height_px [int (slider: 1000-30000)]
│   ├── screenshot_timeout_seconds [int (slider: 5-120)]
│   ├── allow_screenshot_to_ai [bool]
│   └── element_multiline_separator [string]
└── storage_audit (存储与审计管理, collapsed: true)
    ├── download_save_path [string]
    ├── screenshot_save_path [string]
    ├── file_retention_days [int (slider: 1-90)]
    ├── audit_retention_days [int (slider: 1-365)]
    ├── audit_max_output_chars [int]
    └── audit_save_screenshots [bool]
```

### 4.2 具体字段规格与选项设计

#### 分组 1：`security` (安全与权限)
1. **`admin_only`**:
   - `type`: `"bool"`
   - `description`: `"仅管理员可用"`
   - `hint`: `"开启后仅机器人管理员与额外管理员可调用浏览器工具"`
   - `default`: `false`
2. **`extra_admin_uids`**:
   - `type`: `"list"`
   - `description`: `"额外管理员"`
   - `hint`: `"选择或添加拥有管理权限的用户 ID 列表"`
   - `default`: `[]`
   - `_special`: `"sender_id"`
3. **`storage_state_path`**:
   - `type`: `"string"`
   - `description`: `"管理凭据路径"`
   - `hint`: `"管理员专用的 Cookie / StorageState JSON 文件路径（仅管理员可用）"`
   - `default`: `""`
4. **`whitelist_rules`**:
   - `type`: `"template_list"`
   - `description`: `"网站白名单"`
   - `hint`: `"添加非管理员允许访问的网站通配规则及对应权限"`
   - `default`: `[]`
   - `templates`:
     - `rule`:
       - `name`: `"白名单规则"`
       - `display_item`: `"domain"`
       - `items`:
         - `domain`: `type: "string"`, `description: "目标域名/通配符"`, `hint: "支持 example.com 或 *.github.com"`, `default: ""`
         - `allowed_actions`: `type: "list"`, `description: "允许的操作行为"`, `hint: "下拉勾选允许执行的操作"`, `default: ["read", "screenshot"]`, `options: ["read", "click", "fill", "scroll", "screenshot", "download"]`, `labels: ["读取文本 (read)", "点击交互 (click)", "输入表单 (fill)", "页面滚动 (scroll)", "页面截图 (screenshot)", "下载文件 (download)"]`

#### 分组 2：`runtime` (会话与运行时)
1. **`context_mode`**:
   - `type`: `"string"`
   - `description`: `"隔离模式"`
   - `hint`: `"选择浏览器上下文的隔离粒度"`
   - `default`: `"personal"`
   - `options`: `["personal", "session"]`
   - `labels`: `["个人隔离 (personal)", "会话共享 (session)"]`
   - `subtitles`: `["每个用户独享独立的浏览器标签与上下文", "同一群聊/私聊会话共享相同的浏览器上下文"]`
2. **`idle_timeout_minutes`**:
   - `type`: `"int"`
   - `description`: `"空闲销毁时长"`
   - `hint`: `"上下文无交互超过此时长后自动关闭以释放内存 (分钟)"`
   - `default`: `10`
   - `slider`: `{"min": 1, "max": 120, "step": 1}`
3. **`tool_execution_timeout_seconds`**:
   - `type`: `"int"`
   - `description`: `"执行超时时长"`
   - `hint`: `"单个工具执行的最长等待时间 (秒)"`
   - `default`: `30`
   - `slider`: `{"min": 5, "max": 180, "step": 5}`
4. **`enable_close_tool`**:
   - `type`: `"bool"`
   - `description`: `"注册关闭工具"`
   - `hint`: `"是否向大模型注册主动关闭浏览器的工具"`
   - `default`: `true`
5. **`system_prompt_injection`**:
   - `type`: `"text"`
   - `description`: `"系统提示词注入"`
   - `hint`: `"注入大模型的自定义系统提示词，留空则不注入"`
   - `default`: `""`

#### 分组 3：`browser` (浏览器引擎)
1. **`browser_adapter`**:
   - `type`: `"string"`
   - `description`: `"浏览器适配器"`
   - `hint`: `"底层驱动引擎：Camoufox 自带反爬指纹伪装，Playwright 支持原生多浏览器"`
   - `default`: `"camoufox"`
   - `options`: `["camoufox", "playwright"]`
   - `labels`: `["Camoufox (防检测)", "Playwright (原生引擎)"]`
   - `subtitles`: `["内置先进反检测与指纹伪装技术，爬虫防护网站首选", "原生支持 Chromium、Firefox、WebKit 及自定义可执行文件"]`
2. **`playwright_browser_type`**:
   - `type`: `"string"`
   - `description`: `"Playwright 核心"`
   - `hint`: `"Playwright 的浏览器内核类型，选择'其他'时必须填写下方路径"`
   - `default`: `"chromium"`
   - `options`: `["chromium", "firefox", "webkit", "custom"]`
   - `labels`: `["Chromium (推荐)", "Firefox", "WebKit", "其他 (自定义路径)"]`
   - `subtitles`: `["兼具最佳性能与兼容性", "Firefox 核心", "Safari 核心", "使用本地 Chrome / Edge 等定制可执行文件"]`
   - `condition`: `{"browser_adapter": "playwright"}`
3. **`browser_executable_path`**:
   - `type`: `"string"`
   - `description`: `"浏览器可执行文件路径"`
   - `hint`: `"自定义浏览器二进制文件的完整绝对路径（选择'其他'时必填）"`
   - `default`: `""`
   - `condition`: `{"playwright_browser_type": "custom"}`
4. **`camoufox_geoip`**:
   - `type`: `"bool"`
   - `description`: `"GeoIP 定位防检"`
   - `hint`: `"根据 IP 地址自动模拟时区与地理坐标"`
   - `default`: `false`
   - `condition`: `{"browser_adapter": "camoufox"}`
5. **`browser_headless`**:
   - `type`: `"bool"`
   - `description`: `"无头模式"`
   - `hint`: `"后台静默运行，无需图形桌面支持"`
   - `default`: `true`
6. **`browser_window_width`**:
   - `type`: `"int"`
   - `description`: `"窗口宽度"`
   - `hint`: `"浏览器初始视口宽度 (像素)"`
   - `default`: `1280`
   - `slider`: `{"min": 800, "max": 3840, "step": 10}`
7. **`browser_window_height`**:
   - `type`: `"int"`
   - `description`: `"窗口高度"`
   - `hint`: `"浏览器初始视口高度 (像素)"`
   - `default`: `720`
   - `slider`: `{"min": 600, "max": 2160, "step": 10}`
8. **`browser_user_agent`**:
   - `type`: `"string"`
   - `description`: `"自定义 User-Agent"`
   - `hint`: `"留空则使用适配器内置的默认 UA"`
   - `default`: `""`

#### 分组 4：`media` (截图与交互输出)
1. **`screenshot_format`**:
   - `type`: `"string"`
   - `description`: `"截图格式"`
   - `hint`: `"页面截图输出的文件格式"`
   - `default`: `"png"`
   - `options`: `["png", "jpeg"]`
   - `labels`: `["PNG (无损高清)", "JPEG (压缩优化)"]`
   - `subtitles`: `["画质最佳，体积相对较大", "支持调节压缩质量，节省网络带宽"]`
2. **`screenshot_quality`**:
   - `type`: `"int"`
   - `description`: `"截图质量"`
   - `hint`: `"JPEG 格式时的图片压缩质量 (1~100)"`
   - `default`: `80`
   - `slider`: `{"min": 1, "max": 100, "step": 1}`
   - `condition`: `{"screenshot_format": "jpeg"}`
3. **`screenshot_max_height_px`**:
   - `type`: `"int"`
   - `description`: `"长截图高度上限"`
   - `hint`: `"全屏截取的最大像素高度，超出自动截断 (像素)"`
   - `default`: `8000`
   - `slider`: `{"min": 1000, "max": 30000, "step": 500}`
4. **`screenshot_timeout_seconds`**:
   - `type`: `"int"`
   - `description`: `"长截图超时时长"`
   - `hint`: `"长截图拼接渲染的超时秒数，超时自动降级为视口截图"`
   - `default`: `15`
   - `slider`: `{"min": 5, "max": 120, "step": 1}`
5. **`allow_screenshot_to_ai`**:
   - `type`: `"bool"`
   - `description`: `"允许将截图发给 AI"`
   - `hint`: `"允许大模型直接接收页面截图进行多模态视觉理解"`
   - `default`: `false`
6. **`element_multiline_separator`**:
   - `type`: `"string"`
   - `description`: `"元素换行替换符"`
   - `hint`: `"页面可操作元素提取时，内部换行符替换文本"`
   - `default`: `" | "`

#### 分组 5：`storage_audit` (存储与审计管理, collapsed: true)
1. **`download_save_path`**: `type: "string"`, `description: "下载保存目录"`, `default: "data/downloads"`
2. **`screenshot_save_path`**: `type: "string"`, `description: "截图保存目录"`, `default: "data/screenshots"`
3. **`file_retention_days`**: `type: "int"`, `description: "文件保留天数"`, `default: 7`, `slider: {"min": 1, "max": 90, "step": 1}`
4. **`audit_retention_days`**: `type: "int"`, `description: "审计保留天数"`, `default: 30`, `slider: {"min": 1, "max": 365, "step": 1}`
5. **`audit_max_output_chars`**: `type: "int"`, `description: "审计单条字符上限"`, `hint: "0 表示不限制"`, `default: 0`
6. **`audit_save_screenshots`**: `type: "bool"`, `description: "审计持久化截图"`, `hint: "是否在审计数据库中关联保存截图文件"`, `default: true`

---

### 4.3 后端原生分组配置解析 (`main.py` & `adapts/factory.py`)

在 `main.py` 与 `adapts/factory.py` 中直接针对 5 大业务分组进行结构化读取：

```python
# 1. 业务分组提取
sec_cfg = self.config.get("security", {})
rt_cfg = self.config.get("runtime", {})
br_cfg = self.config.get("browser", {})
med_cfg = self.config.get("media", {})
store_cfg = self.config.get("storage_audit", {})

# 安全与权限
admin_only = bool(sec_cfg.get("admin_only", False))
extra_admins = [str(u).strip() for u in sec_cfg.get("extra_admin_uids", []) if str(u).strip()]
whitelist_rules = list(sec_cfg.get("whitelist_rules", []))
storage_state_path = str(sec_cfg.get("storage_state_path", ""))

# 会话与运行时
context_mode = str(rt_cfg.get("context_mode", "personal"))
idle_timeout = int(rt_cfg.get("idle_timeout_minutes", 10))
tool_timeout = int(rt_cfg.get("tool_execution_timeout_seconds", 30))
enable_close_tool = bool(rt_cfg.get("enable_close_tool", True))
self.system_prompt_injection = str(rt_cfg.get("system_prompt_injection", "")).strip()

# 截图与多媒体
screenshot_format = str(med_cfg.get("screenshot_format", "png")).lower()
screenshot_quality = int(med_cfg.get("screenshot_quality", 80))
screenshot_max_height = int(med_cfg.get("screenshot_max_height_px", 8000))
screenshot_timeout = int(med_cfg.get("screenshot_timeout_seconds", 15))
allow_screenshot_to_ai = bool(med_cfg.get("allow_screenshot_to_ai", False))
element_multiline_separator = str(med_cfg.get("element_multiline_separator", " | "))

# 存储与审计
download_save_path = str(store_cfg.get("download_save_path", "data/downloads"))
screenshot_save_path = str(store_cfg.get("screenshot_save_path", "data/screenshots"))
file_retention_days = int(store_cfg.get("file_retention_days", 7))
retention_days = int(store_cfg.get("audit_retention_days", 30))
audit_max_output_chars = int(store_cfg.get("audit_max_output_chars", 0))
audit_save_screenshots = bool(store_cfg.get("audit_save_screenshots", True))
```

在 `adapts/factory.py` 中：
```python
browser_cfg = config.get("browser", config)
adapter_type = str(browser_cfg.get("browser_adapter", "camoufox")).lower()
headless = bool(browser_cfg.get("browser_headless", True))
user_agent = str(browser_cfg.get("browser_user_agent", "") or "")
window_width = int(browser_cfg.get("browser_window_width", 1280))
window_height = int(browser_cfg.get("browser_window_height", 720))
browser_executable_path = str(browser_cfg.get("browser_executable_path", "") or "").strip()

if adapter_type == "playwright":
    browser_type = str(browser_cfg.get("playwright_browser_type", "chromium")).lower()
    if browser_type == "custom":
        if not browser_executable_path:
            raise ValueError("Playwright 原生浏览器类型选择'其他'时，必须指定可执行文件路径 (browser_executable_path)！")
        # 自定义路径浏览器基于 chromium 引擎驱动
        browser_type = "chromium"
```

---

## 5. 验证与测试策略 (Verification & Tests)

1. **Schema 结构与控件验证**：
   - 验证 `_conf_schema.json` 为合法 JSON 且包含 `security`、`runtime`、`browser`、`media`、`storage_audit` 5 大分组。
   - 验证 9 项关键控件（`sender_id`、`slider`、`template_list`、`condition`、`options` 等）全部准确配置。
2. **功能与错误校验测试**：
   - 测试 `PlaywrightToolPlugin` 初始化正常加载分组配置。
   - 测试 `playwright_browser_type == "custom"` 未传路径时抛出 `ValueError`，传入路径时正常透传。
3. **全量回归测试**：
   - 同步更新测试用例中的配置数据为新的标准分组结构。
   - 运行全量 `python -m unittest discover -s tests`，确保全部测试用例 100% 通过。
