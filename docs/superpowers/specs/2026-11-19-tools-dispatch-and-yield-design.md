# 规格设计：tools.py 字典映射分发与统一 yield 结果输出

## 1. 意图与背景 (Intent & The Why)
当前 [tools/tools.py](../../tools/tools.py) 中 `PwPageTool`、`PwInteractTool`、`PwMediaTool` 三大工具的 `call` 方法采用多层 `if-elif-else` 分支进行动作分发，代码冗长且不易维护。同时，在截图发送给聊天用户时，原逻辑采用 `event.send` 后 `return` 提示文本的方式，导致后续文本消息在聊天界面覆盖之前发送的图像消息。
本次重构旨在消灭 `if-elif-else` 分支，并将所有工具的 `call` 输出形式统一为异步生成器（`yield`），在发送截图时使用 `yield event.image_result(path)` 并立即退出。

## 2. 目标与非目标 (Goals & Non-Goals)
### 目标 (Goals)
1. **消灭 if-elif-else**：三大工具统一采用方法级字典映射（`self._actions`）进行动作路由。
2. **统一 yield 产出**：所有工具的 `call` 签名与产出统一为异步生成器，非图片操作和错误信息统一 `yield res`。
3. **防止消息覆盖**：`target="chat"` 截图成功时，直接执行 `yield event.image_result(img_path)` 并立即 `return` 结束，绝不追加任何后续文本。
4. **保留超时保护**：底层动作执行协程依然受 `_execute_with_timeout` 保护。
5. **单元测试对齐**：更新并补全 [tests/test_tools_v2.py](../../tests/test_tools_v2.py)，确保对异步生成器 `call` 的全覆盖。

### 非目标 (Non-Goals)
1. 不修改外部工具 Schema（[tools/schemas.py](../../tools/schemas.py)）及大模型感知到的工具参数定义。
2. 不修改 `PageHandler`、`InteractHandler`、`MediaHandler` 内部实现。

## 3. 技术约束 (Constraints)
1. **异步生成器约束**：Python 异步生成器内禁止带值返回（`return <value>` 会抛出 `SyntaxError`），必须通过 `yield` 输出结果，提前退出只能使用无参数 `return`。
2. **文档规范**：严格遵循 [AGENT.md](../../../AGENT.md)，所有代码注释与文档保持凝练简洁。

## 4. 架构备选方案评估 (Approaches)
- **方案 1：类方法级字典映射（Method Dispatch Map）—— [已选定]**
  - **实现**：将各 action 的参数检查与 Handler 调用解耦为类的私有异步方法（如 `_do_open`、`_do_click` 等），并在 `__post_init__` 中维护 `self._actions: dict[str, Callable]` 进行路由分发。
  - **权衡**：动作高内聚低耦合，参数校验明确，单测易写易调。用户已明确选定该方案。
- **方案 2：call 内部局部函数字典（Local Function Dispatch Map）—— [已放弃]**
  - **实现**：在 `call` 内部定义局部 async 函数字典。
  - **权衡**：每次调用重复创建局部闭包，`call` 仍过于臃肿。
- **方案 3：声明式通用参数提取引擎 —— [已放弃]**
  - **权衡**：过度抽象，违背 `AGENT.md` 的极简原则。

## 5. 详细实现设计 (Detailed Implementation)
### 5.1 `PwPageTool`
- 映射字典包含：`open`, `read`, `search`, `switch_tab`, `dialog`, `close`。
- 各私有方法（如 `_do_open(self, session_id, sender_id, kwargs)`）负责参数校验并调用 `self.page_handler`。
- `call` 中查表执行并直接 `yield res`。

### 5.2 `PwInteractTool`
- 映射字典包含：`click`, `fill`, `select`, `hover`, `focus`, `blur`, `drag`, `press_key`, `scroll`。
- 各私有方法校验参数并调用 `self.interact_handler`。
- `call` 中查表执行并直接 `yield res`。

### 5.3 `PwMediaTool`
- 映射字典包含：`screenshot_viewport`, `screenshot_full`, `download`。
- `call` 执行动作后：
  - 若动作为截图且返回以 `[IMAGE_PATH:` 开头：解析提取路径，若 `hasattr(event, "image_result")` 则 `yield event.image_result(img_path)`；随后直接 `return` 退出。
  - 其余情况（包含 `target="ai"`、下载文件或报错）：统一 `yield res`。

### 5.4 单元测试适配 (`tests/test_tools_v2.py`)
- 更新测试辅助函数以消费异步生成器产出的所有条目，验证 `yield event.image_result(...)` 且不再输出多余消息。

## 6. 留给构建者的细节 (Left to the Builder)
1. 保证 `_execute_with_timeout` 依旧平滑包裹各个私有动作方法执行过程。
2. 保持兼容性：在未模拟真实 AstrBot 事件环境（如单测或降级模式）下，若 `event` 缺乏 `image_result` 方法，可安全回退到返回路径文本。
