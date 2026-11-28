# Markdown Reader Ref 前缀与空白分隔设计

## 1. 意图与背景
优化 [`markdown_reader.py`](../../core/readers/markdown_reader.py) 及配套 [`markdown_extractor.js`](../../core/readers/markdown_extractor.js) 提炼网页 Markdown 时的可读性与 Ref 辨识度，避免多余空白以及相邻交互控件粘连（如 `[xxx][1][yyy][2]`）。

## 2. 目标与非目标
- **目标**：
  - 为 Markdown 阅读器分配的 Ref ID 统一增加 `@r` 前缀（如 `@r1`、`@r2`），DOM `data-astr-ref` 与 `ref_map` 键名同步使用 `@rN`。
  - 压缩文本节点中的多余连续空白，并在交互控件边界自动补充空格分隔（如 `[xxx][@r1] [yyy][@r2]`）。
  - 保持下游工具对 `ref` 的完全匹配机制（调用方必须传入 `@r1` 才能匹配）。
  - 同步更新 [`skills/playwright-tool/SKILL.md`](../../skills/playwright-tool/SKILL.md) 及相关文档与单元测试。
- **非目标**：
  - 不修改 ARIA 阅读器（[`aria_reader.py`](../../core/readers/aria_reader.py)）的 Ref 格式（`e1`、`f1e1`）。
  - 不在下游 Handler 中引入去掉 `@r` 前缀的模糊/兼容匹配。
- **约束**：
  - 遵守 [`AGENT.md`](../../AGENT.md) 规范，修改后运行 `python -m unittest discover tests` 验证全部单测通过。

## 3. 备选方案与选型
- **方案 A（已选）：空白压缩 + 仅在交互控件边界补空格**
  - 在文本节点将 `\s+` 压缩为单空格，在拼接行内节点时仅当连接处无空白且至少一侧为交互控件输出时插入空格。
  - 优点：解决粘连与多余空格的同时，不破坏 `<strong>100</strong>元` 等普通行内排版。
- **方案 B（未选）：所有行内节点统一用空格拼接后再压缩**
  - 实现最简单，但会在普通行内标签或标点之间引入多余空格。

## 4. 核心改动点
1. **[`core/readers/markdown_extractor.js`](../../core/readers/markdown_extractor.js)**：
   - 分配新 Ref 时生成 `@r${nextRef}`（复用已有 `data-astr-ref` 时直接使用字符串值），同时递增 `nextRef` 与 `allocatedCount`。
   - `renderInline` 与 `traverse` 的文本节点空白统一使用 `.replace(/\s+/g, ' ')` 压缩，块级输出清理连续空格（保留 `<br>` 产生的换行 `\n`）。
   - 提取行内拼接辅助函数：拼接相邻非空片段时，若边界无空白且任一侧为交互控件，则自动插入单个空格。
2. **[`core/readers/markdown_reader.py`](../../core/readers/markdown_reader.py)**：
   - 更新 `get_tool_metadata()` 中 `ref` 参数示例为 `'@r1', '@r2'`。
3. **文档与测试**：
   - 更新 [`skills/playwright-tool/SKILL.md`](../../skills/playwright-tool/SKILL.md) 中的 Ref 示例为 `@r` 前缀格式（如 `@r12`）。
   - 按 [`AGENT.md`](../../AGENT.md) 同步检查并更新相关文档与 [`tests/test_readers.py`](../../tests/test_readers.py) 等单元测试。

## 5. 留给实现的细节
- 边界空格判断中对交互控件片段的精确识别方式（如基于节点类型或交互标记，确保嵌套 `<strong><a>...</a></strong>` 等场景也能正确分隔）。
