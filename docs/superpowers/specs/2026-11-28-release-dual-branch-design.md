# `scripts/release.py` 双分支同步发布设计

## 1. 意图与目标
- **意图**：使 `python scripts/release.py` 每次运行默认同时同步 `release` 与 `release-market` 两个正式分支。
- **目标**：
  - `release` 分支保持现有文件白名单规则不变。
  - `release-market` 分支在 `release` 过滤结果基础上额外排除 `core/history_cleaner.py`（`main.py` 已对其做 `ImportError` 降级，缺失时可正常加载）。
  - `--dry-run` 展示两分支的文件过滤结果；`--push` 在两分支本地均提交成功后统一推送至 `origin`。
- **非目标**：不改变 `master` 分支源码，不新增按单分支过滤的 CLI 参数（按要求默认每次同时同步两分支）。

## 2. 约束
- 仅允许从 `master` 分支运行发布脚本；工作区有未提交变更时需传入 `--allow-dirty`。
- 同步更新 `AGENT.md` 中的分支管理策略描述与 `tests/test_release_script.py` 单元测试，确保单测通过。

## 3. 方案选型（方案 A）
- **已选定方案 A（声明式目标映射 + 独立 worktree 循环同步）**：
  - 在 `scripts/release.py` 中定义 `RELEASE_TARGETS = {"release": set(), "release-market": {"core/history_cleaner.py"}}`。
  - 扩展 `is_path_allowed(rel_path, extra_excluded=None)` 与 `ensure_branch_exists(repo_dir, branch_name)`，将 worktree 清理、拷贝、提交抽取为独立辅助函数。
  - `run_release()` 遍历 `RELEASE_TARGETS` 分别构建各分支的允许文件列表并执行本地 worktree 同步；若启用 `push=True`，在所有目标分支本地同步完成后统一执行 `git push origin <branch>`。
- **未选方案 B（基于 `release` 衍生删除）**：会将 `release-market` 绑定到 `release` 提交历史，若远端 `origin/release-market` 已有独立历史易引发推送冲突。

## 4. 留给实现者的细节
- 保留 `ensure_release_branch_exists` 兼容别名或直接迁移调用方（同步更新 `tests/test_release_script.py`）。
- 若需顺带确认 `tests/test_release_script.py` 中既有的 `docs/internal_spec.md` 断言是否与当前 `is_path_allowed` 逻辑一致，可在实现计划中一并核对。
