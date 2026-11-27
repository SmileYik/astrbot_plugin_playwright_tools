# 副 AI 压缩提示词用户意图占位符设计规范 (Compress Prompt User Input Placeholder Spec)

## 1. 概述与设计目标

在长上下文工具历史消减过程中，副 AI 负责对历史工具调用（网页正文、交互过程）进行结构化提炼。若副 AI 仅依据通用的静态系统提示词，容易在提炼时丢失与当前用户目标高度相关的核心事实。

通过在 `compress_prompt` 中引入 `{{user_input}}` 动态占位符，支持用户在提示词中显式注入当前会话的目标问题（例如：“结合用户的问题‘{{user_input}}’，提炼网页关键事实”），使副 AI 能够执行目标导向的聚焦摘要（Query-Focused Summarization）。

---

## 2. 详细设计规范

### 2.1 用户消息提取算法 (`_extract_user_input`)
在 `core/history_cleaner.py` 中新增方法：
```python
def _extract_user_input(self, contexts: list[Any] | None = None, event: Any = None) -> str:
    """从上下文列表中提取最近的一条用户消息文本，若无则从事件中提取。"""
```
提取优先级：
1. **优先从 `contexts` 逆序提取**：
   - 遍历 `reversed(contexts)`，找到第一个 `self._get_role(msg) == "user"` 的消息；
   - 使用 `self._get_content(msg)` 提取纯文本字符串；
   - 若提取出的字符串非空，则直接返回该字符串。
2. **回退尝试从 `event` 中提取**：
   - 若 `event` 存在，检查 `getattr(event, "message_str", None)`；
   - 若不存在，尝试调用 `getattr(event, "get_message_str", None)()`；
   - 提取并清理首尾空白字符后返回。
3. **安全回退**：若以上均未提取到非空文本，返回 `""`。

### 2.2 提示词组装与占位符替换 (`_resolve_system_prompt`)
更新 `core/history_cleaner.py` 中的 `_resolve_system_prompt`：
```python
async def _resolve_system_prompt(self, user_input: str = "") -> str:
    base_prompt = self.compress_prompt
    if "{{user_input}}" in base_prompt:
        base_prompt = base_prompt.replace("{{user_input}}", user_input)
    ...
```
- 若 `compress_prompt` 包含 `{{user_input}}`，执行全局字符串替换；
- 若未包含 `{{user_input}}`，保持原有静态提示词不变（100% 向后兼容）；
- 替换后的 `base_prompt` 继续与人设面具提示词（`persona_prompt`）按原逻辑融合。

在 `_compress_batch` 中：
```python
user_input = self._extract_user_input(contexts, event)
sys_prompt = await self._resolve_system_prompt(user_input=user_input)
```

### 2.3 配置模式更新 (`_conf_schema.json`)
更新 `history_cleanup.items.compress_prompt` 的 `hint`：
在说明中增加：“支持使用 `{{user_input}}` 占位符引入当前用户问题，引导副 AI 针对性提炼”。

---

## 3. 测试与验证规范

1. **多态用户消息测试**：
   - 测试 `content` 为纯字符串时的提取；
   - 测试 `content` 为 `[TextPart(text="...")]`（如 AstrBot 消息）时的提取；
   - 测试多轮对话中存在多个 user 消息时，准确提取最近的一条。
2. **占位符替换测试**：
   - 测试 `compress_prompt="提炼针对 '{{user_input}}' 的内容"`，断言组装后的 system_prompt 包含实际用户消息；
   - 测试没有占位符时提示词不受影响；
   - 测试上下文无 user 消息时占位符被替换为 `""` 且不抛出异常。
3. **全测试套件无回归**：
   - 运行全量单元测试确认 100% 通过。
