# tools.py 字典映射分发与统一 yield 结果输出实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 [tools/tools.py](../../tools/tools.py) 中三大工具的 `call` 分发逻辑由 `if-elif-else` 重构为类方法字典映射，所有工具统一通过异步生成器 `yield` 产出结果，并在聊天截图时直接 `yield event.image_result(path)` 且静默退出。

**Architecture:** 每个工具类在初始化时维护 `self._actions: dict[str, Callable]`，将动作映射到专门的私有异步方法上；`call` 统一使用 `async def call(...)` 作为异步生成器，动作协程交由 `_execute_with_timeout` 超时保护，最终通过 `yield` 输出结果，其中聊天截图成功后执行 `yield event.image_result(img_path)` 并立刻退出。

**Tech Stack:** Python 3.10+, Playwright, AstrBot Plugin API (`FunctionTool`, `AstrMessageEvent`).

**Spec:** [docs/superpowers/specs/2026-11-19-tools-dispatch-and-yield-design.md](../specs/2026-11-19-tools-dispatch-and-yield-design.md)

## Global Constraints

- 严禁在 `call` 异步生成器内部使用带值的 `return value`（会触发 Python `SyntaxError`），退出只能使用无值 `return`。
- 严禁破坏现有参数校验规则与错误提示文案。
- 必须保留单工具全局超时控制（`tool_execution_timeout_seconds`）。
- 严格遵循 [AGENT.md](../../../AGENT.md) 规范：代码与注释保持凝练简洁，不写冗余无用逻辑。

## Review Focus

1. 未知动作输入：当 `action` 为空或非法名称时，产生明确的错误提示文案并安全退出。
2. 缺失必须参数：当 `open` 缺少 `url`、`click` 缺少 `ref` 时，产出参数错误提示，不抛出未捕获异常。
3. 执行超时异常：动作在超时保护下被阻断时，正确产出超时错误提示信息。
4. 截图权限被拒或发生异常：非 `[IMAGE_PATH:` 开头的返回内容，作为普通文本正常 `yield res`。
5. 事件对象缺少 `image_result` 方法：测试或降级上下文中未注入该方法时，安全降级产出文本，避免抛出 AttributeError。

---

### Task 1: 重构 `PwPageTool` 动作分发与生成器输出

**Files:**
- Modify: `tools/tools.py`
- Test: `tests/test_tools_v2.py`

**Interfaces:**
- Consumes: `PageHandler` (`open_url`, `read_page`, `search_page`, `switch_tab`, `handle_dialog`, `close_browser`)
- Produces: `PwPageTool` 具备 `self._actions` 字典，`call` 声明为异步生成器产出字符串

- [ ] **Step 1: 在 `tests/test_tools_v2.py` 中编写针对生成器消费与字典映射的测试用例**

```python
async def collect_gen(gen):
    results = []
    async for item in gen:
        results.append(item)
    return results

def run_gen(gen):
    # 异步生成器同步驱动辅助函数
    ...
```
编写 `test_page_tool_actions_map_exists` 与 `test_page_tool_dispatch_via_generator` 测试。

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: FAIL（因为当前 `call` 是协程函数而不是异步生成器，无 `__aiter__`）

- [ ] **Step 3: 在 `tools/tools.py` 中重构 `PwPageTool`**

1. 在 `PwPageTool` 中定义各个私有动作方法：`_action_open`, `_action_read`, `_action_search`, `_action_switch_tab`, `_action_dialog`, `_action_close`。
2. 在 `__post_init__` 中注册 `self._actions = {"open": self._action_open, ...}`。
3. 重构 `async def call(self, context: AstrAgentContext, **kwargs)`：
   - 提取 `event, session_id, sender_id = _extract_event_and_ids(context)`。
   - 查询 `handler = self._actions.get(action)`。若未找到，`yield f"未知的动作: {action}。支持的动作包括: open, read, search, switch_tab, dialog, close"` 并退出。
   - `res = await _execute_with_timeout(handler(session_id, sender_id, **kwargs), self.timeout_seconds)`。
   - `yield res`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tools/tools.py tests/test_tools_v2.py
git commit -m "refactor(tools): convert PwPageTool to method dispatch map and generator call"
```

---

### Task 2: 重构 `PwInteractTool` 动作分发与生成器输出

**Files:**
- Modify: `tools/tools.py`
- Test: `tests/test_tools_v2.py`

**Interfaces:**
- Consumes: `InteractHandler` (`click`, `fill_form`, `select_option`, `hover`, `focus`, `blur`, `drag`, `press_key`, `scroll`)
- Produces: `PwInteractTool` 具备 `self._actions` 字典，`call` 声明为异步生成器产出字符串

- [ ] **Step 1: 在 `tests/test_tools_v2.py` 中更新 `PwInteractTool` 相关测试为异步生成器驱动**

适配原有 `test_interact_tool_dispatch_click` 与 `test_interact_tool_missing_ref` 为异步生成器消费。

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: FAIL（`PwInteractTool.call` 当前仍为协程返回）

- [ ] **Step 3: 在 `tools/tools.py` 中重构 `PwInteractTool`**

1. 在 `PwInteractTool` 中定义各个私有动作方法：`_action_click`, `_action_fill`, `_action_select`, `_action_hover`, `_action_focus`, `_action_blur`, `_action_drag`, `_action_press_key`, `_action_scroll`。
2. 在 `__post_init__` 中注册 `self._actions = {"click": self._action_click, ...}`。
3. 重构 `async def call(self, context: AstrAgentContext, **kwargs)` 为异步生成器，查表后送入 `_execute_with_timeout` 并统一 `yield res`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tools/tools.py tests/test_tools_v2.py
git commit -m "refactor(tools): convert PwInteractTool to method dispatch map and generator call"
```

---

### Task 3: 重构 `PwMediaTool` 动作分发与图片 direct yield 逻辑

**Files:**
- Modify: `tools/tools.py`
- Test: `tests/test_tools_v2.py`

**Interfaces:**
- Consumes: `MediaHandler` (`screenshot_viewport`, `screenshot_full`, `download_file`), `event.image_result`
- Produces: `PwMediaTool` 具备 `self._actions` 字典，`call` 在聊天截图成功时只产出 `event.image_result(path)` 并立即退出

- [ ] **Step 1: 在 `tests/test_tools_v2.py` 中增加图片直接 yield 及后续无多余消息测试**

1. 编写测试：当 `target="chat"` 且截图成功时，模拟 `event.image_result`，验证产出的第一个条目为 `image_result` 返回值，且生成器产出总长度为 1（无后续文本）。
2. 编写测试：当 `target="ai"` 或下载文件或动作失败时，验证产出对应文本。

- [ ] **Step 2: 运行测试验证失败**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: FAIL

- [ ] **Step 3: 在 `tools/tools.py` 中重构 `PwMediaTool`**

1. 定义私有动作方法：`_action_screenshot_viewport`, `_action_screenshot_full`, `_action_download`。
2. 在 `__post_init__` 中注册 `self._actions = {...}`。
3. 在 `async def call(self, context: AstrAgentContext, **kwargs)` 中：
   - 提取 action 并查找 handler。
   - `res = await _execute_with_timeout(handler(...), self.timeout_seconds)`。
   - 判断：若 action 在截图动作列表内且 `str(kwargs.get("target", "chat")).lower() == "chat"` 且 `res.startswith("[IMAGE_PATH:")`：
     - 解析出 `img_path = res.split("\n", 1)[0][len("[IMAGE_PATH:"):-1]`。
     - 若 `hasattr(event, "image_result") and callable(event.image_result)`：
       - `yield event.image_result(img_path)`
       - `return`（直接结束，不追加任何多余文本）
   - 其余情况统一步入：`yield res`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python3 -m unittest tests/test_tools_v2.py`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tools/tools.py tests/test_tools_v2.py
git commit -m "feat(tools): direct yield image_result without subsequent message in PwMediaTool"
```

---

### Task 4: 更新文档与全量测试回归验证

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Test: All tests in `tests/`

- [ ] **Step 1: 运行全量单元测试**

Run: `python3 -m unittest discover tests`
Expected: 全部测试通过 (OK)

- [ ] **Step 2: 更新架构文档与变更日志**

在 `docs/ARCHITECTURE.md` 与 `CHANGELOG.md` 中记录本次重构：消灭 `if-elif-else` 改为字典映射，统一 `call` 为生成器，聊天截图使用 `yield event.image_result` 直接交付。

- [ ] **Step 3: 运行 git status 检查并提交文档**

```bash
git add docs/ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: update architecture and changelog for tools dispatch and yield refactoring"
```
