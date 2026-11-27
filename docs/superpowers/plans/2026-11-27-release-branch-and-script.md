# Release Branch and Sync Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the `release` branch as the primary publication branch, update `AGENT.md` with branch management rules, and create an automated Python release script using Git worktree isolation to sync filtered code from `master` to `release`.

**Architecture:** A lightweight standard library Python script (`scripts/release.py`) checks working tree cleanliness on `master`, reads project version from `metadata.yaml`, mounts a temporary Git worktree for `release`, synchronizes only runtime code and public documentation while stripping development-only files, commits the release, and cleans up the worktree.

**Tech Stack:** Python 3.12 (standard library: `argparse`, `subprocess`, `tempfile`, `shutil`, `pathlib`, `unittest`), Git CLI.

**Spec:** [docs/superpowers/specs/2026-11-27-release-branch-and-script-design.md](file:///G:/workspace/ai/astrbot_plugin_playwright_tools/docs/superpowers/specs/2026-11-27-release-branch-and-script-design.md)

## Global Constraints

- `master` branch is the full development branch containing all assets, tests, docs, and code.
- `release` branch is the primary distribution branch containing only runtime code, pre-built `views/`, `skills/`, configurations, and public documentation.
- Excluded from `release`: `tests/`, `web-src/`, `docs/superpowers/`, `docs/old/`, `HOW-TO-CODE.md`, `AGENT.md`, `scripts/`.
- Included in `release`: `adapts/`, `api/`, `core/`, `tools/`, `main.py`, `requirements.txt`, `_conf_schema.json`, `metadata.yaml`, `views/`, `logo.png`, `skills/`, `README.md`, `CHANGELOG.md`, `LICENSE`, `docs/ARCHITECTURE.md`, `docs/EXTERNAL_API.md`, `docs/images/`, `.gitignore`.
- Execution on `master` must never leave the working directory dirty or alter checked-out branches in the main workspace.

## Review Focus

- Dirty working directory on master: script must abort unless `--allow-dirty` is provided to prevent accidental unstaged loss.
- Non-master branch execution: script must abort with clear error message if current branch is not `master`.
- Windows path separators and hidden Git metadata: ensure `temp_dir` worktree creation and cleanup handles Windows file locks cleanly (`git worktree remove --force`).
- Whitelist vs Blacklist collision: files under `docs/images/`, `docs/ARCHITECTURE.md`, `docs/EXTERNAL_API.md` must be preserved while `docs/superpowers/` and `docs/old/` are excluded.
- Target branch non-existence: if `release` branch does not exist locally or remotely, script must initialize it seamlessly from the filtered tree.

---

### Task 1: Update AGENT.md with Branch and Release Specifications

**Files:**
- Modify: `AGENT.md:62-66`

**Interfaces:**
- Produces: Updated `AGENT.md` containing `## 分支与版本发布规范` defining `master` and `release` roles, inclusion/exclusion lists, and release command instructions.

- [ ] **Step 1: Check existing AGENT.md structure**

Confirm lines around `## 版本管理` to place the new section properly.

- [ ] **Step 2: Edit `AGENT.md` to add branch and release specifications**

Add the branch management section:
```markdown
## 分支与版本发布规范

本项目采用双分支管理策略：
- **`master` 分支**：全量开发分支，包含全量源码、单测套件、前端源代码、AI 工作流与完整开发文档。所有开发工作在此分支进行。
- **`release` 分支**：正式发布分支（主要分支），仅包含经测试验证、供 AstrBot 直接安装运行的正式代码、必要配置、构建后前端视图产物及对外技术文档。

### 文件分布准则
- **release 保留**：`adapts/`, `api/`, `core/`, `tools/`, `main.py`, `requirements.txt`, `_conf_schema.json`, `metadata.yaml`, `views/`, `logo.png`, `skills/`, `README.md`, `CHANGELOG.md`, `LICENSE`, `docs/ARCHITECTURE.md`, `docs/EXTERNAL_API.md`, `docs/images/`, `.gitignore`。
- **release 排除**：`tests/`, `web-src/`, `docs/superpowers/`, `docs/old/`, `HOW-TO-CODE.md`, `AGENT.md`, `scripts/`。

### 版本发布流程
1. 确保在 `master` 分支通过所有单元测试 (`python -m unittest discover tests`)。
2. 确认 `metadata.yaml` 与 `main.py` 中的版本号同步更新。
3. 若修改了前端源码 `web-src/`，必须提前编译输出至 `views/` 目录。
4. 运行发布同步脚本：
   ```bash
   python scripts/release.py
   ```
   （若需推送到远程仓库，附加 `--push` 参数）
```

- [ ] **Step 3: Verify AGENT.md formatting and links**

Ensure markdown headers and links match project style.

- [ ] **Step 4: Commit**

```bash
git add AGENT.md
git commit -m "docs: add branch management and release specification to AGENT.md"
```

---

### Task 2: Write Unit Tests for Release Script Helpers

**Files:**
- Create: `tests/test_release_script.py`

**Interfaces:**
- Produces: Test suite validating `extract_version`, `is_path_allowed`, `check_git_clean`, and `build_release_tree`.

- [ ] **Step 1: Write failing unit tests in `tests/test_release_script.py`**

Test helper functions in `scripts.release`:
- `test_extract_version_valid`: parses version string from mock metadata.yaml.
- `test_extract_version_missing`: raises ValueError when version field is absent.
- `test_is_path_allowed`: checks paths against exclusion and inclusion rules:
  - `adapts/base.py` -> True
  - `docs/ARCHITECTURE.md` -> True
  - `docs/images/audit.png` -> True
  - `tests/test_tools.py` -> False
  - `web-src/src/App.tsx` -> False
  - `docs/superpowers/plans/foo.md` -> False
  - `docs/old/req.md` -> False
  - `AGENT.md` -> False
  - `HOW-TO-CODE.md` -> False
  - `scripts/release.py` -> False

```python
import unittest
from pathlib import Path
from scripts.release import extract_version, is_path_allowed

class TestReleaseScript(unittest.TestCase):
    def test_extract_version(self):
        content = 'name: test\nversion: "v1.4.5"\n'
        self.assertEqual(extract_version(content), "v1.4.5")

    def test_is_path_allowed(self):
        self.assertTrue(is_path_allowed(Path("adapts/base.py")))
        self.assertTrue(is_path_allowed(Path("docs/ARCHITECTURE.md")))
        self.assertTrue(is_path_allowed(Path("docs/images/audit.png")))
        self.assertFalse(is_path_allowed(Path("tests/test_tools.py")))
        self.assertFalse(is_path_allowed(Path("web-src/package.json")))
        self.assertFalse(is_path_allowed(Path("docs/superpowers/specs/spec.md")))
        self.assertFalse(is_path_allowed(Path("docs/old/req.md")))
        self.assertFalse(is_path_allowed(Path("AGENT.md")))
        self.assertFalse(is_path_allowed(Path("HOW-TO-CODE.md")))
        self.assertFalse(is_path_allowed(Path("scripts/release.py")))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_release_script.py`
Expected: FAIL (ModuleNotFoundError: No module named 'scripts')

- [ ] **Step 3: Commit initial test file**

```bash
git add tests/test_release_script.py
git commit -m "test: add unit tests for release script filter and parser functions"
```

---

### Task 3: Implement `scripts/release.py`

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/release.py`

**Interfaces:**
- Produces: CLI script supporting `--push`, `--allow-dirty`, `--message`, `--dry-run`.
- Exports:
  - `extract_version(content: str) -> str`
  - `is_path_allowed(rel_path: Path) -> bool`
  - `get_tracked_files_from_git(repo_dir: Path) -> list[Path]`
  - `run_release(repo_dir: Path, allow_dirty: bool = False, push: bool = False, message: str | None = None, dry_run: bool = False) -> int`

- [ ] **Step 1: Implement `scripts/__init__.py` and `scripts/release.py`**

Implement:
1. `extract_version(content: str) -> str`: regex match for `version:\s*["']?([^"'\s]+)["']?`.
2. `is_path_allowed(rel_path: Path) -> bool`:
   - Exact top-level excluded files: `AGENT.md`, `HOW-TO-CODE.md`.
   - Excluded root directories: `tests`, `web-src`, `scripts`, `.superpowers`, `.venv`, `__pycache__`, `data`.
   - Under `docs/`: excluded if starting with `docs/superpowers` or `docs/old`. Allowed if `docs/images`, `docs/ARCHITECTURE.md`, `docs/EXTERNAL_API.md`.
   - Default allowed if tracked and not in blacklist.
3. Git worktree orchestration:
   - Verify current branch is `master`.
   - Check if status is clean unless `allow_dirty=True`.
   - Check if `release` branch exists (`git rev-parse --verify release` or fallback to create orphan / branch).
   - Use `tempfile.TemporaryDirectory` + `git worktree add <temp_dir> release`.
   - In `finally` block: `git worktree remove --force <temp_dir>`.
   - Copy allowed files from master worktree into `temp_dir`.
   - Delete any existing files in `temp_dir` that are not allowed.
   - Run `git add -A` and `git status --porcelain`.
   - If changes detected, commit with `release: {version} (sync from master {commit_hash})`.
   - If `--push`, run `git push origin release`.

- [ ] **Step 2: Run unit tests to verify they pass**

Run: `python -m unittest tests/test_release_script.py`
Expected: PASS

- [ ] **Step 3: Run full test suite to ensure no regressions**

Run: `python -m unittest discover tests`
Expected: 100% tests pass.

- [ ] **Step 4: Commit release script**

```bash
git add scripts/ tests/test_release_script.py
git commit -m "feat: implement release branch sync script with git worktree isolation"
```

---

### Task 4: Initialize `release` Branch and Validate Release Sync

**Files:**
- Create/Sync: Git branch `release`

**Interfaces:**
- Consumes: `python scripts/release.py`
- Produces: A clean local `release` branch containing only authorized production files.

- [ ] **Step 1: Execute `scripts/release.py --dry-run` to preview synchronized files**

Run: `python scripts/release.py --dry-run`
Verify output list shows expected whitelist files and no blacklist files.

- [ ] **Step 2: Execute `python scripts/release.py`**

Run: `python scripts/release.py`
Verify execution completes with return code 0, commits to `release`, and cleans up the worktree.

- [ ] **Step 3: Verify contents of `release` branch**

Run:
```bash
git ls-tree -r --name-only release
```
Verify:
- Contains: `main.py`, `metadata.yaml`, `adapts/`, `api/`, `core/`, `tools/`, `views/`, `skills/`, `docs/ARCHITECTURE.md`, `docs/EXTERNAL_API.md`, `docs/images/`, `README.md`, `CHANGELOG.md`, `LICENSE`, `requirements.txt`, `_conf_schema.json`, `logo.png`.
- Absent: `tests/`, `web-src/`, `docs/superpowers/`, `docs/old/`, `AGENT.md`, `HOW-TO-CODE.md`, `scripts/`.

- [ ] **Step 4: Verify current branch remains `master` and working tree is clean**

Run: `git status`
Confirm on branch `master`, nothing to commit, working tree clean.
