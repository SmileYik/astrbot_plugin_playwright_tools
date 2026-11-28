# `scripts/release.py` 双分支同步发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造 `scripts/release.py`，使其每次运行默认同时同步 `release` 与 `release-market` 两个发布分支，其中 `release-market` 额外排除 `core/history_cleaner.py`。

**Architecture:** 在 `scripts/release.py` 中声明 `RELEASE_TARGETS` 映射表，扩展 `is_path_allowed` 与 `ensure_branch_exists` 支持按目标分支过滤与建分支，将单分支 worktree 同步抽取为 `_sync_branch_worktree`；`run_release` 遍历所有目标分支先完成本地提交，再在 `push=True` 时统一推送到 `origin`。

**Tech Stack:** Python 3.12, `subprocess` / `git worktree`, `unittest`

**Spec:** [2026-11-28-release-dual-branch-design.md](file:///run/media/smileyik/G/Workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-28-release-dual-branch-design.md)

## Global Constraints

- 仅允许从 `master` 分支运行；未提交变更须显式传 `--allow-dirty`。
- 日志与输出保持简洁，不使用绝对化措辞。
- 完成后运行 `.venv/bin/python -m unittest tests/test_release_script.py -v` 验证通过，并同步更新 `AGENT.md`。

## Review Focus

1. **`core/history_cleaner.py` 跨平台路径归一化**：无论传入 `"core/history_cleaner.py"` 还是 Windows 反斜杠路径，`extra_excluded` 匹配都必须基于规范化 POSIX 路径。
2. **两分支均有改动或仅单分支有改动**：若 `release` 已是最新（无需提交）而 `release-market` 有变动（或反之），每个分支必须独立判断 `status --porcelain` 并按需提交，不能互相跳过。
3. **`--push` 原子性顺序**：先完成两个分支的本地 worktree 提交，全部成功后再统一推送，避免一个分支失败时另一个分支已提前推到远端。
4. **`--dry-run` 输出完整**：需清晰列出 `release` 与 `release-market` 各自的保留/排除情况（或额外排除文件）。

---

### Task 1: 改造 `scripts/release.py` 支持双分支同步与 `--dry-run` / `--push`

**Files:**
- Modify: `scripts/release.py`
- Test: `tests/test_release_script.py`

**Interfaces:**
- Produces:
  - `RELEASE_TARGETS: dict[str, set[str]] = {"release": set(), "release-market": {"core/history_cleaner.py"}}`
  - `is_path_allowed(rel_path: Path | str, extra_excluded: set[str] | None = None) -> bool`
  - `ensure_branch_exists(repo_dir: Path, branch_name: str) -> None`（保留 `ensure_release_branch_exists(repo_dir)` 委托给 `ensure_branch_exists(repo_dir, "release")`）
  - `run_release(repo_dir: Path, allow_dirty: bool = False, push: bool = False, message: str | None = None, dry_run: bool = False) -> int`

- [ ] **Step 1: Write failing tests in `tests/test_release_script.py`**

Add tests:
- `test_is_path_allowed_extra_excluded_blocks_history_cleaner`: `is_path_allowed(Path("core/history_cleaner.py"))` is `True`, while `is_path_allowed(Path("core/history_cleaner.py"), extra_excluded={"core/history_cleaner.py"})` is `False`.
- `test_run_release_syncs_both_release_and_release_market`: create temp git repo on `master` containing `main.py`, `metadata.yaml`, `requirements.txt`, `core/history_cleaner.py`, `tests/test_dummy.py`; run `run_release(repo_dir)`; assert both `release` and `release-market` branches exist; `git ls-tree -r --name-only release` contains `core/history_cleaner.py` (and not `tests/test_dummy.py`), while `git ls-tree -r --name-only release-market` does NOT contain `core/history_cleaner.py` (nor `tests/test_dummy.py`), and both contain `main.py` and `metadata.yaml`.
- `test_run_release_dry_run_shows_both_branches_without_creating_branches`: run `run_release(repo_dir, dry_run=True)` and assert neither `release` nor `release-market` branch is created.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests/test_release_script.py -v`
Expected: FAIL (`TypeError` for `extra_excluded` / missing `release-market` branch)

- [ ] **Step 3: Implement dual-branch sync in `scripts/release.py`**

- Define `RELEASE_TARGETS = {"release": set(), "release-market": {"core/history_cleaner.py"}}`.
- Update `is_path_allowed(rel_path: Path | str, extra_excluded: set[str] | None = None) -> bool` to normalize POSIX path and return `False` if in `extra_excluded`.
- Generalize `ensure_branch_exists(repo_dir: Path, branch_name: str) -> None` (keeping `ensure_release_branch_exists` delegating to `"release"`).
- Extract `_sync_branch_worktree(repo_dir: Path, branch_name: str, allowed_files: list[Path], commit_msg: str) -> None` with `try/finally` worktree cleanup.
- Update `run_release` to compute per-target `allowed_files` / `excluded_files`, handle `--dry-run` for both targets, sync all targets locally first, and then push each target branch if `push=True`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests/test_release_script.py -v`
Expected: New dual-branch tests PASS (note: check pre-existing `docs/internal_spec.md` assertion in `test_release_script.py`).

- [ ] **Step 5: Commit**

```bash
git add scripts/release.py tests/test_release_script.py
git commit -m "feat(release): sync both release and release-market branches in release script"
```

---

### Task 2: 更新 `AGENT.md` 分支管理策略文档

**Files:**
- Modify: `AGENT.md:66-75`

- [ ] **Step 1: Update `AGENT.md` branch strategy**

Document `release` and `release-market` (noting `release-market` matches `release` except excluding `core/history_cleaner.py`), and note `python scripts/release.py` syncs both branches by default.

- [ ] **Step 2: Verify with `--dry-run` on real repo**

Run: `.venv/bin/python scripts/release.py --dry-run`
Expected: Exits with 0, displays both `release` and `release-market`, and `release-market` excludes `core/history_cleaner.py`.

- [ ] **Step 3: Commit**

```bash
git add AGENT.md
git commit -m "docs: document release-market branch in AGENT.md"
```
