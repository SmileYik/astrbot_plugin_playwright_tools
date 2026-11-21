# 插件配置 WebUI 体验升级与分组重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `_conf_schema.json` 重构为现代 5 大业务分组与 9 项交互控件，并适配 `adapts/factory.py` 与 `main.py` 的结构化配置原生读取与 `custom` 浏览器类型校验。

**Architecture:** 将原 29 项配置划分到 `security`、`runtime`、`browser`、`media`、`storage_audit` 5 个 `type: "object"` 分组中，利用 AstrBot 原生控件系统实现用户选择器、模板列表、多选下拉框、滑块输入联动与条件显示；后端直接按分组字典提取配置，杜绝历史包袱。

**Tech Stack:** Python 3.10+, AstrBot Star Plugin Architecture, JSON Schema / AstrBot Form Generator, unittest

**Spec:** `docs/superpowers/specs/2026-11-21-plugin-config-ui-redesign-design.md`

## Global Constraints
- 采用 5 个顶层业务分组：`security`、`runtime`、`browser`、`media`、`storage_audit`。
- `extra_admin_uids` 类型为 `list`，附带 `_special: "sender_id"`，默认值 `[]`。
- `context_mode` 下拉单选：`options: ["personal", "session"]`，附带 `labels` 与 `subtitles`。
- 5 处数值时长与像素配置统一配置 `slider`（`idle_timeout_minutes`, `tool_execution_timeout_seconds`, `screenshot_max_height_px`, `screenshot_timeout_seconds`, `screenshot_quality`）。
- `whitelist_rules` 为 `template_list`，模板 `rule` 包含 `domain` 文本与 `allowed_actions` 多选下拉（6 种权限：`read`, `click`, `fill`, `scroll`, `screenshot`, `download`）。
- `browser_adapter` 下拉单选：`options: ["camoufox", "playwright"]`。
- `playwright_browser_type` 下拉单选：`options: ["chromium", "firefox", "webkit", "custom"]`，仅在 `browser_adapter == "playwright"` 显示；当选 `custom` 时必须填入 `browser_executable_path`，且底层映射为 `chromium` 引擎。
- `screenshot_quality` 仅在 `screenshot_format == "jpeg"` 时通过 `condition` 展示。
- 全量自动化单元测试 100% 通过（`python -m unittest discover -s tests`）。

## Review Focus
- `playwright_browser_type == "custom"` 且未配置或配置空串 `browser_executable_path` 时，`AdapterFactory.create()` 必须抛出明确的 `ValueError`。
- `playwright_browser_type == "custom"` 且配置了合法路径时，`PlaywrightAdapter` 的 `browser_type` 应映射为 `"chromium"` 并正确透传 `executable_path`。
- `_conf_schema.json` 中 `whitelist_rules` 的模板项必须包含 `display_item: "domain"`，子字段 `allowed_actions` 必须为包含全部 6 种操作选项的 `list`。
- `main.py` 在空配置 `{}` 传入时，必须安全回退至所有字段的默认值，不触发 `KeyError`。
- `storage_audit` 分组必须设置 `collapsed: true`，其余 4 个基础分组保持默认展开。

---

### Task 1: 重构 `_conf_schema.json` 与更新 Schema 测试

**Files:**
- Modify: `_conf_schema.json`
- Test: `tests/test_conf_schema.py`

**Interfaces:**
- Produces: 符合 AstrBot 规范的 5 大分组配置 schema（`security`, `runtime`, `browser`, `media`, `storage_audit`），覆盖全部 29 个字段及其控件修饰属性（`slider`, `condition`, `options`, `_special`, `template_list`）。

- [ ] **Step 1: 编写针对分组结构与 9 项交互控件的失败测试**

在 `tests/test_conf_schema.py` 中更新断言：
```python
def test_conf_schema_grouped_structure():
    with open("_conf_schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    assert set(schema.keys()) == {"security", "runtime", "browser", "media", "storage_audit"}
    for group in schema.values():
        assert group["type"] == "object"
        assert "items" in group

    # 验证 9 项特异控件
    sec = schema["security"]["items"]
    assert sec["extra_admin_uids"]["type"] == "list"
    assert sec["extra_admin_uids"]["_special"] == "sender_id"
    assert sec["whitelist_rules"]["type"] == "template_list"
    assert "rule" in sec["whitelist_rules"]["templates"]

    rt = schema["runtime"]["items"]
    assert rt["context_mode"]["options"] == ["personal", "session"]
    assert "slider" in rt["idle_timeout_minutes"]
    assert "slider" in rt["tool_execution_timeout_seconds"]

    br = schema["browser"]["items"]
    assert br["browser_adapter"]["options"] == ["camoufox", "playwright"]
    assert br["playwright_browser_type"]["options"] == ["chromium", "firefox", "webkit", "custom"]
    assert br["playwright_browser_type"]["condition"] == {"browser_adapter": "playwright"}
    assert br["browser_executable_path"]["condition"] == {"playwright_browser_type": "custom"}

    med = schema["media"]["items"]
    assert med["screenshot_format"]["options"] == ["png", "jpeg"]
    assert med["screenshot_quality"]["condition"] == {"screenshot_format": "jpeg"}
    assert "slider" in med["screenshot_quality"]
    assert "slider" in med["screenshot_max_height_px"]
    assert "slider" in med["screenshot_timeout_seconds"]

    storage = schema["storage_audit"]
    assert storage.get("collapsed") is True
```

- [ ] **Step 2: 运行测试以确认失败**

运行：`.\.venv\Scripts\python -m unittest tests/test_conf_schema.py`
预期：FAIL，提示根节点缺失分组或旧字段扁平。

- [ ] **Step 3: 重写 `_conf_schema.json`**

按照 `docs/superpowers/specs/2026-11-21-plugin-config-ui-redesign-design.md` 第 4.1 & 4.2 节重构完整 JSON 文件，保证格式合法、文案精简、选项详尽。

- [ ] **Step 4: 运行测试以确认通过**

运行：`.\.venv\Scripts\python -m unittest tests/test_conf_schema.py`
预期：PASS。

- [ ] **Step 5: 提交更改**

```bash
git add _conf_schema.json tests/test_conf_schema.py
git commit -m "feat(config): redesign conf schema with 5 groups and interactive controls"
```

---

### Task 2: 适配 `adapts/factory.py` 浏览器分组提取与 `custom` 类型校验

**Files:**
- Modify: `adapts/factory.py`
- Test: `tests/test_adapter_factory.py`

**Interfaces:**
- Consumes: `config: dict`（可包含 `"browser"` 键或直接传入浏览器配置字典）。
- Produces: `AdapterFactory.create(config)` 能够提取 `browser` 分组配置；当 `playwright_browser_type == "custom"` 时校验 `browser_executable_path`，若为空抛出 `ValueError`，若有效则映射为 `chromium` 引擎并将路径透传给 `PlaywrightAdapter`。

- [ ] **Step 1: 编写 `custom` 浏览器类型与分组配置解析的失败测试**

在 `tests/test_adapter_factory.py` 中新增用例：
```python
def test_adapter_factory_grouped_browser_config():
    config = {
        "browser": {
            "browser_adapter": "playwright",
            "playwright_browser_type": "webkit",
            "browser_headless": True,
        }
    }
    adapter = AdapterFactory.create(config)
    assert isinstance(adapter, PlaywrightAdapter)
    assert adapter.browser_type == "webkit"

def test_adapter_factory_custom_browser_without_path_raises():
    config = {
        "browser": {
            "browser_adapter": "playwright",
            "playwright_browser_type": "custom",
            "browser_executable_path": "",
        }
    }
    with pytest.raises(ValueError, match="必须指定可执行文件路径"):
        AdapterFactory.create(config)

def test_adapter_factory_custom_browser_with_path_maps_chromium():
    config = {
        "browser": {
            "browser_adapter": "playwright",
            "playwright_browser_type": "custom",
            "browser_executable_path": "C:/Browser/chrome.exe",
        }
    }
    adapter = AdapterFactory.create(config)
    assert isinstance(adapter, PlaywrightAdapter)
    assert adapter.browser_type == "chromium"
    assert adapter.executable_path == "C:/Browser/chrome.exe"
```

- [ ] **Step 2: 运行测试以确认失败**

运行：`.\.venv\Scripts\python -m unittest tests/test_adapter_factory.py`
预期：FAIL，提示 `不支持的浏览器类型` 或未触发校验。

- [ ] **Step 3: 修改 `adapts/factory.py`**

在 `AdapterFactory.create` 中：
1. 提取 `browser_cfg = config.get("browser", config) if isinstance(config.get("browser"), dict) else config`。
2. 当 `adapter_type == "playwright"` 时读取 `browser_type = str(browser_cfg.get("playwright_browser_type", "chromium")).lower()`。
3. 若 `browser_type == "custom"`，校验 `browser_executable_path`；若为空抛出 `ValueError("Playwright 原生浏览器类型选择'其他'时，必须指定可执行文件路径 (browser_executable_path)！")`，否则将 `browser_type` 赋值为 `"chromium"`。

- [ ] **Step 4: 运行测试以确认通过**

运行：`.\.venv\Scripts\python -m unittest tests/test_adapter_factory.py`
预期：PASS。

- [ ] **Step 5: 提交更改**

```bash
git add adapts/factory.py tests/test_adapter_factory.py
git commit -m "feat(adapter): support grouped browser config and custom executable validation"
```

---

### Task 3: 适配 `main.py` 原生分组配置读取与组件依赖注入

**Files:**
- Modify: `main.py`
- Test: `tests/test_plugin_main.py`

**Interfaces:**
- Consumes: 含有 `security`, `runtime`, `browser`, `media`, `storage_audit` 结构的 `AstrBotConfig`。
- Produces: `PlaywrightToolPlugin` 正确解析各分组配置，安全注入 `SecurityManager`、`ContextManager`、`MediaHandler`、`PageExtractor`、`AuditLogger`。

- [ ] **Step 1: 编写支持分组配置注入的失败/修改测试**

在 `tests/test_plugin_main.py` 中更新 `test_conf_schema_valid_json` 与 `test_plugin_wiring_adapter_and_handlers`，将旧的扁平字典替换为新的标准 5 大分组字典：
```python
cfg = {
    "audit_db_path": db_file,
    "security": {
        "admin_only": False,
        "extra_admin_uids": ["admin_99"],
        "whitelist_rules": [{"__template_key": "rule", "domain": "*.example.com", "allowed_actions": ["read"]}],
    },
    "runtime": {
        "context_mode": "session",
        "idle_timeout_minutes": 15,
        "tool_execution_timeout_seconds": 45,
    },
    "browser": {
        "browser_adapter": "playwright",
        "playwright_browser_type": "firefox",
        "browser_headless": True,
    },
    "media": {
        "screenshot_format": "jpeg",
        "screenshot_quality": 85,
    },
    "storage_audit": {
        "download_save_path": "data/custom_downloads",
        "screenshot_save_path": "data/custom_screenshots",
        "file_retention_days": 14,
        "audit_retention_days": 60,
    }
}
```

- [ ] **Step 2: 运行测试确认原有扁平假设失败**

运行：`.\.venv\Scripts\python -m unittest tests/test_plugin_main.py`
预期：FAIL（`main.py` 仍按扁平 `self.config.get("admin_only")` 读取，导致无法提取分组下的新值）。

- [ ] **Step 3: 修改 `main.py` 中的配置解析逻辑**

在 `PlaywrightToolPlugin.__init__` 开头提取 5 大分组字典，直接安全提取各分组字段，传递给 `SecurityManager`、`ContextManager`、`PageExtractor`、`AdapterFactory` 等：
- `sec_cfg = self.config.get("security", {}) if isinstance(self.config.get("security"), dict) else {}`
- `rt_cfg = self.config.get("runtime", {}) if isinstance(self.config.get("runtime"), dict) else {}`
- `br_cfg = self.config.get("browser", {}) if isinstance(self.config.get("browser"), dict) else {}`
- `med_cfg = self.config.get("media", {}) if isinstance(self.config.get("media"), dict) else {}`
- `store_cfg = self.config.get("storage_audit", {}) if isinstance(self.config.get("storage_audit"), dict) else {}`
安全取值后，将 `self.config` 或 `br_cfg` 传递给 `AdapterFactory.create`。

- [ ] **Step 4: 运行测试以确认通过**

运行：`.\.venv\Scripts\python -m unittest tests/test_plugin_main.py`
预期：PASS。

- [ ] **Step 5: 提交更改**

```bash
git add main.py tests/test_plugin_main.py
git commit -m "feat(plugin): wire modular grouped config ingestion in main.py"
```

---

### Task 4: 全量回归测试与文档校验

**Files:**
- Test: 全量 `tests/`
- Documentation: `README.md`, `metadata.yaml`

**Interfaces:**
- Produces: 确保当前仓库 136+ 个现有单元测试 100% 绿灯通过，配置文件与文档描述完全一致。

- [ ] **Step 1: 运行全量测试套件**

运行：`.\.venv\Scripts\python -m unittest discover -s tests`
预期：所有测试全部通过（Ran 136+ tests ... OK）。

- [ ] **Step 2: 检查任何因配置结构更新受影响的现有测试**

若有任何测试在 mock `self.config` 时使用了旧字段名且未包含默认值，同步将其适配为分组字典结构，重新运行全量测试直到 0 报错。

- [ ] **Step 3: 检查 README.md 配置说明**

若 `README.md` 中有提及配置项名称或说明，同步简要更新为新的分组结构与字段名。

- [ ] **Step 4: 提交全量回归成果**

```bash
git add .
git commit -m "test(regression): verify 100% test pass on new grouped config architecture"
```
