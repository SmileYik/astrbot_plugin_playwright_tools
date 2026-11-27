# 双分支发布规范与自动化发布脚本设计规范 (Release Branch and Sync Script Design Spec)

## 1. 概述与设计背景

### 1.1 背景
本项目（`astrbot_plugin_playwright_tools`）是一个 AstrBot 浏览器自动化与大模型网页交互插件。
目前代码库中除了插件运行所需的 Python 核心代码、适配器与静态前端构建产物（`views/`）外，还包含了全量的单测套件（`tests/`）、React 前端源码（`web-src/`）、AI 规划与工作流规范（`docs/superpowers/`）、历史开发文档（`docs/old/`、`HOW-TO-CODE.md`）及 Agent 约定（`AGENT.md`）。

当面向终端用户、插件市场或轻量分发时，携带上述开发期资产会显著增加克隆和下载体积，且无助于实际运行。因此需要建立清晰的双分支管理策略，并配备自动化脚本完成分支同步与发布。

### 1.2 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

- **目标 (Goals)**：
  1. 确立 `master`（全量开发分支）与 `release`（正式发布主分支）的双分支体系；
  2. 将该分支定位与文件保留/排除边界完整写入 `AGENT.md`；
  3. 编写自动化发布脚本 `scripts/release.py`，实现从 `master` 分支自动过滤、清点并提交到 `release` 分支；
  4. 初始化本地 `release` 分支，验证初次同步后 `release` 分支内容的完整性与纯净度。
- **非目标 (Non-Goals)**：
  - 默认不向远程仓库（GitHub 等）发起强制推送（除非显式传入 `--push` 参数）；
  - 不修改现有业务逻辑代码或既有单元测试；
  - 不改变 `views/` 预编译静态资源的生成逻辑（`views/` 仍由 `web-src` 提前编译）。
- **反目标 (Anti-Goals)**：
  - 严禁在 `release` 分支中混入任何开发测试、前端源码或内部 AI/开发规范文档；
  - 严禁发布脚本在执行时切变本地工作区分支或污染当前 `master` 正在进行的未暂存修改。

---

## 2. 分支职责与文件清单界定

### 2.1 分支职责
- **`master` 分支**：全量开发分支，包含所有功能代码、单测、前端源代码、AI 工作流文档、开发指引等，所有新特性的开发、重构与日常调试均在此分支进行。
- **`release` 分支**：正式发布分支（主要分支），仅包含经测试验证、可直接供 AstrBot 插件系统载入运行的正式代码、必要配置、构建后视图产物及对外技术文档。

### 2.2 文件保留清单 (Whitelist for `release`)
在 `release` 分支中必须完整保留并同步更新的路径：
- **核心业务与工具代码**：
  - `adapts/`（浏览器底层适配器代码）
  - `api/`（网页 Web API 路由与业务逻辑）
  - `core/`（核心生命周期、读者提炼器、审计日志与上下文消减器）
  - `tools/`（大模型调用工具定义与 Handlers）
  - `main.py`（插件主入口）
- **依赖与配置**：
  - `requirements.txt`（运行时 Python 依赖）
  - `_conf_schema.json`（插件可视配置 Schema）
  - `metadata.yaml`（插件元信息）
  - `.gitignore`（基础忽略配置）
- **静态资源与界面**：
  - `views/`（前端预构建产物 HTML/JS/CSS）
  - `logo.png`（插件图标）
- **运行时技能**：
  - `skills/`（面向大模型的 `playwright-tool` 等运行时技能）
- **对外公开技术文档与说明**：
  - `README.md`
  - `CHANGELOG.md`
  - `LICENSE`
  - `docs/ARCHITECTURE.md`（整体架构文档）
  - `docs/EXTERNAL_API.md`（外部集成 API 文档）
  - `docs/images/`（文档插图与架构图）

### 2.3 文件排除清单 (Blacklist for `release`)
严禁在 `release` 分支中出现的内容：
- `tests/`（单元测试套件）
- `web-src/`（前端 React/Vite 源码）
- `docs/superpowers/`（AI 工作流规格与计划）
- `docs/old/`（历史开发需求文档）
- `HOW-TO-CODE.md`（开发人员编码指南）
- `AGENT.md`（开发 Agent 协作规范）
- `scripts/`（发布脚本及内部开发脚本本身）
- 任何本地运行产生的缓存或未跟踪临时文件（如 `.venv/`、`__pycache__/`、`data/`、`.superpowers/` 等）

---

## 3. 方案对比与技术选型 (Approaches Considered)

| 方案 | 机制说明 | 优点 | 缺点 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| **方案 1：Git Worktree 隔离（已选）** | 在系统临时目录通过 `git worktree add` 检出 `release`，在临时目录同步、过滤并提交，完成后移除 worktree | 1. 对当前工作区零污染、零切换，无 IDE 刷新或未保存文件风险；<br>2. 异常时自动安全卸载清理；<br>3. 跨平台支持完备 | 需要临时目录（由 Python `tempfile` 自动安全托管） | **采纳** |
| **方案 2：原地分支检出与切换** | 本地 `git stash` -> `git checkout release` -> 从 master 覆盖 -> 删除排除文件 -> 提交 -> 切回 master | 流程概念直观，不依赖临时目录 | 在 Windows 下极易因文件锁定导致删除失败（`EBUSY`/权限拒绝）；异常中断会导致停留在脏 release 分支 | 否决 |
| **方案 3：Git 底层树对象管道** | 使用 `git mktree`、`git commit-tree` 直接在 Git 数据库中过滤并生成提交 | 速度最快，纯内存/对象操作 | 嵌套目录（如部分保留 `docs/`）过滤逻辑复杂晦涩，维护成本过高 | 否决 |

---

## 4. 详细设计 (Detailed Design)

### 4.1 AGENT.md 规范更新
在 `AGENT.md` 中增加 `## 分支与版本发布规范` 章节：
1. 阐明 `master` 为全量开发分支，`release` 为主要发布分支。
2. 明确列出 release 分支所包含与剔除的目录/文件范围。
3. 规范每次发布流程：
   - 确保在 `master` 上完成功能开发与单测通过；
   - 确认 `metadata.yaml` 与 `main.py` 的版本号已更新一致；
   - 确认前端如有改动已编译输出至 `views/`；
   - 运行发布脚本 `python scripts/release.py` 同步到 `release` 分支。

### 4.2 发布脚本设计 (`scripts/release.py`)
编写纯 Python 脚本，不引入外部第三方重度依赖，仅依赖 Python 标准库及系统已安装的 `git` CLI。

#### 4.2.1 脚本参数与选项
```text
python scripts/release.py [options]

选项：
  --push            同步成功后自动将 release 分支推送到 origin/release
  --allow-dirty     允许 master 存在未提交修改时执行（默认要求 master 干净）
  --message, -m     自定义 release 提交信息（默认为 "release: {version} (sync from master {commit_hash})")
  --dry-run         仅演练同步过程，打印变更文件列表，不实际创建 commit
```

#### 4.2.2 核心执行生命周期
1. **环境与状态前置检查**：
   - 检查当前执行工作目录是否为 Git 仓库根目录；
   - 检查当前分支是否为 `master`（若不是则提示错误并终止）；
   - 检查当前工作区是否干净（若有未提交修改且未指定 `--allow-dirty` 则终止）；
   - 从 `metadata.yaml` 解析 `version` 字段，获取当前 `master` 最新 commit hash（前 8 位）。
2. **目标分支检查与初始化**：
   - 检查本地是否已存在 `release` 分支：
     - 若不存在：检查远程 `origin/release` 是否存在，若存在则基于远程创建本地跟踪分支；若远程亦不存在，则基于当前提交创建本地 `release` 分支。
3. **临时 Worktree 挂载**：
   - 使用 `tempfile.TemporaryDirectory` 创建隔离的临时目录；
   - 执行 `git worktree add <temp_dir> release`，将 `release` 分支检出至隔离目录。
4. **文件清点与精准同步**：
   - 从 `master` 对应的 tree 中提取需要保留的目标文件路径列表（支持白名单与排除规则交叉校验）；
   - 清理 `temp_dir` 中除 `.git` 之外的全部旧文件；
   - 将 `master` 中当前保留清单的文件递归复制到 `temp_dir`，确保排除项（如 `tests/`、`web-src/`、`docs/superpowers/`、`docs/old/`、`HOW-TO-CODE.md`、`AGENT.md`、`scripts/`）绝不出现在 `temp_dir`；
   - 针对 `docs/` 目录，精准确保只复制 `docs/ARCHITECTURE.md`、`docs/EXTERNAL_API.md` 及 `docs/images/`。
5. **变更检测与提交**：
   - 在 `temp_dir` 中执行 `git status --porcelain`；
   - 若无任何变更，提示 `Release 分支已是最新，无差异变更`；
   - 若存在变更：
     - 执行 `git add -A`；
     - 执行 `git commit -m "{commit_message}"`；
     - 打印变更统计与提交成功信息。
6. **可选远程推送**：
   - 若指定了 `--push`，在 `temp_dir` 执行 `git push origin release`。
7. **清理保障 (Finally Guard)**：
   - 在 `finally` 保护块中：
     - 执行 `git worktree remove --force <temp_dir>`；
     - 自动销毁 `TemporaryDirectory`。

---

## 5. 留给实现者 (Builder) 的具体细节

1. **版本信息提取兼容**：
   - 使用正则匹配 `metadata.yaml` 中的 `version:\s*["']?([^"'\s]+)["']?`，避免因无额外 pyyaml 依赖导致脚本无法在纯环境运行。
2. **Git 命令封装**：
   - 提供带错误处理与明确 stderr 捕获的 `run_git(args, cwd=None)` 辅助函数。
3. **文件复制方式**：
   - 使用 `shutil.copy2` 保持文件元信息，支持跨层级自动创建父目录。
