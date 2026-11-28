# 配置默认值优化与分层文档措辞统一设计

## 1. 意图与背景

目前 [`_conf_schema.json`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/_conf_schema.json) 与运行时代码（[`main.py`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/main.py)、[`core/history_cleaner.py`](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/core/history_cleaner.py)）存在几处默认值偏差与偏保守的阈值（例如 `tool_execution_timeout_seconds=30` 与页面导航 30s 临界冲突、`page_chunk_char_limit=2000` 导致频繁翻页、`high_watermark=8000 / low_watermark=3000` 与 `300 字` 压缩提示词在现代大上下文模型下过早清理且信息损失过大）。同时，面向不同受众的文档措辞需要进一步对齐定位。

## 2. 目标与非目标

### 目标
1. **调优现代大上下文默认配置与建议范围**：降低交互轮次与临界超时报错，统一 `_conf_schema.json`、`main.py` 与 `core/history_cleaner.py` 的默认值。
2. **放宽副 AI 默认压缩提示词长度约束**：从“不超过 300 字”调整为更匹配 `24000 / 10000` 水位线的结构化提炼（不超过 `1000` 字，保留核心事实、关键结论、数据指标、已访问 URL 与重要交互结果）。
3. **按受众分层润色文档**：
   - `_conf_schema.json` 与 `README.md`：面向**普通插件用户**，语言通俗直观，明确“怎么配、填多少、为什么”。
   - `docs/AI_TOOLS.md` 与 `docs/ARCHITECTURE.md`：面向**项目整体情况与技术约定**，同步最新默认值、工具能力与模块约束。
   - `docs/EXTERNAL_API.md`：面向**懂得代码的开发者**，保持接口签名、并发机制与接入范式准确清晰。
4. **同步更新配置单测**：更新 `tests/test_conf_schema.py` 等受默认值变更影响的测试断言。

### 非目标
- 不改变配置分组结构（`security`、`runtime`、`browser`、`media`、`storage_audit`、`history_cleanup`）与配置键名。
- 不修改 `docs/superpowers/` 下的历史设计/计划文档。

## 3. 备选方案对比

- **方案一（选用）：均衡大上下文配置**
  - 在减少翻页与超时的同时保持合理 Token 预算，适合绝大多数 128k+ 上下文模型开箱即用。
- **方案二（弃用）：激进大上下文配置（8000 分页、60000 水位、默认开启 AI 识图）**
  - 对小上下文或按量计费敏感场景开销过大，且默认开启多模态截图会引入额外成本。

## 4. 详细配置调整清单

| 配置项 | 原默认值 | 新默认值 | 新 `hint` 建议范围与用户向说明 |
|---|---|---|---|
| `tool_execution_timeout_seconds` | `30` | `45` | 单个工具执行的最长等待时间 (秒)，建议 `30 ~ 90`（略高于页面加载 30 秒，避免慢站点临界超时） |
| `page_chunk_char_limit` | `2000` | `4000` | 单页正文提炼的最大字符预算（建议 `3000 ~ 6000`，最小 `500`），更大预算可减少翻页次数 |
| `browser_window_width` | `1280` | `1280` | 浏览器初始视口宽度 (像素)，常见桌面宽度建议 `1280` 或 `1920` |
| `browser_window_height` | `720` | `800` | 浏览器初始视口高度 (像素)，建议 `720 ~ 1080`，略高可减少首屏截断 |
| `screenshot_timeout_seconds` | `15` | `20` | 长截图拼接渲染超时秒数（建议 `15 ~ 30`），超时自动降级为视口截图 |
| `audit_retention_days` | `7` (Schema) / `30` (main.py) | `14` | 审计记录保存天数（建议 `7 ~ 30`），超期自动清理 |
| `high_watermark` | `8000` | `24000` | 历史工具调用总字符超过此时触发清理（建议 `16000 ~ 40000`） |
| `low_watermark` | `3000` | `10000` | 触发清理后消减到的目标字符数（建议设为高水位的 `30% ~ 50%`） |
| `compress_max_input_chars` | `0` | `0` | 送给副 AI 压缩的最大字符预算，`0` 为不限制；如需截断建议 `30000 ~ 60000` |
| `compress_prompt` | 不超过 300 字 | 不超过 1000 字 | 结构化保留核心事实、关键结论、数据指标、已访问 URL 与重要交互结果，剔除冗余排版，输出不超过 1000 字的摘要 |

## 5. 文档与代码同步范围
1. `_conf_schema.json`、`main.py`、`core/history_cleaner.py`：对齐上述默认值与用户向 `hint` 文案。
2. `README.md`：更新配置表格默认值与建议值，确保措辞通俗易懂，面向普通插件用户。
3. `docs/AI_TOOLS.md`、`docs/ARCHITECTURE.md`、`docs/EXTERNAL_API.md`：按各自受众定位审校与同步最新信息。
4. `tests/test_conf_schema.py`（及 `tests/test_history_cleaner.py` / `tests/test_plugin_main.py` 若涉及默认值断言）：更新并通过全部单测。
