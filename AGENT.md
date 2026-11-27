# AGENTS.md

## 项目目录结构

- adapts: 浏览器适配器代码
- api: 网页 Web API 路由与业务代码
- core: 核心逻辑组件代码（含 readers 页面阅读提炼器、history_cleaner 上下文历史消减器）
- tools: AI 工具代码（handlers 与复合工具门面）
- docs: 项目文档（架构设计与技术文档）
- views: 可视化界面预构建静态资源
- web-src: 可视化界面源码（React 18 + Vite + TS）
- skills: AI 技能定义目录（playwright-tool 等）
- tests: 单元测试套件
- main.py: 插件入口
- metadata.yaml: 插件元数据

## 工具体系规范

本插件面向大模型收敛并提供四大独立复合工具：
1. `pw_page`: 页面级生命周期、标签页切换、原生弹窗预设与关闭释放
2. `pw_read`: 结构化正文提炼（内联 Markdown / ARIA 树）、Ref ID 提取、分页与关键词定位
3. `pw_interact`: 原生 Locator 键鼠与表单交互（点击、输入、选择、悬停、焦点、拖拽、按键、滚动）
4. `pw_media`: 视口与长截图生成交付、持久化审计截图与文件下载

所有工具必须统一维护 `_actions` 字典分发，禁止回退到多层 `if-elif-else` 分支；执行必须包含全局超时保护。

## 插件可视化界面

关于可视化界面, [web-src](web-src) 目录中为可视化界面源代码,
每次可视化界面源代码修改后都需要进行编译维护到 [views](views) 文件夹中.

## 文档编写规范

所有文档, 无论是代码注释, 文档还是供人看的消息(提示)文本等, 都应该在正确表达含义的基础上做到凝练简洁, 不啰嗦.
于此同时, 不准出现特别绝对的词或者语句, 如: "彻底xxx", "根治xxx"等, "杜绝xxx"等, "完全xxx"等, 实事求是.

在每一次变更时, 都需要及时变更对应文档内容. 包括但不限于: 

- [README](README.md)
- [metadata.yaml](metadata.yaml)
- [ARCHITECTURE](docs/ARCHITECTURE.md)
- [skills](skills)

## SKILLS 文档

需要维护 [skills](./skills/) 目录内的 SKILL 文档.
维护 SKILL 文档时, 应该保证在准确描述的基础上做到语言的简洁凝练.

### playwright-tool SKILL

该 SKILL 为本插件最基础的 SKILL, 其中包含本插件四大复合工具体系的用法和操作流程.
其中内容仅包含需要让 AI 学会操作流程的(用户)内容, 避免暴露内部实现信息.

## 变更(Changelog)文档

需要及时维护变更文档里的内容.

## 架构文档

需要及时更新文档内关于当前插件的结构/架构和整体功能实现. 其中还需要包含当前项目中具体存在的功能和对应的实现方法.

## 版本管理

每次 [metadata.yaml](metadata.yaml) 消息变化后, 都需要在 [main.py](main.py) 中更新对应信息.

## 环境

当前环境由uv进行管理, 虚拟环境在 [.venv](.venv) 下.

必要内容有
- python 3.12
- playwright
- camoufox[geoip]

## 测试与验证规范

每次编写或修改任何关于工具、适配器或核心组件（`tools/`、`core/`、`adapts/`）的代码后，都必须运行单元测试进行验证：
运行 `python -m unittest discover tests`，保证所有基础单测 100% 通过。不使用端到端（e2e）测试。

## 日志

需要在各个关键节点上埋下日志, 异常发生时必须完整打印和记录 traceback 调用栈，方便后续追踪调试.
特别声明：日志记录不能使用外部日志库（严禁使用 `import logging`），仅能使用 `from astrbot.api import logger`。
