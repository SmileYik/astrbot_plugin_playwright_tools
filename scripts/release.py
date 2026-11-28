#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Release branch synchronization script for astrbot_plugin_playwright_tools.

Synchronizes filtered runtime code and public documentation from 'master'
branch to 'release' and 'release-market' branches using isolated Git worktrees.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Explicit whitelist of allowed files and directories in release branch
ALLOWED_ROOT_FILES = {
    "main.py",
    "requirements.txt",
    "_conf_schema.json",
    "metadata.yaml",
    ".gitignore",
    "logo.png",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
}

ALLOWED_ROOT_DIRS = {
    "adapts",
    "api",
    "core",
    "tools",
    "views",
    "skills",
}

BANNED_DOCS_DIRS = {
    "superpowers", 
    "old"
}

# Target release branches and their extra excluded relative POSIX paths
RELEASE_TARGETS: dict[str, set[str]] = {
    "release": set(),
    "release-market": {"core/history_cleaner.py"},
}


def extract_version(content: str) -> str:
    """Extract version string from metadata.yaml content."""
    match = re.search(r'(?m)^\s*version:\s*["\']?([^"\'\s]+)["\']?', content)
    if not match:
        raise ValueError("Could not find version field in metadata content")
    return match.group(1).strip()


def _normalize_posix(rel_path: Path | str) -> str:
    posix = str(rel_path).replace("\\", "/")
    if posix.startswith("./"):
        posix = posix[2:]
    return posix.strip("/")


def is_path_allowed(rel_path: Path | str, extra_excluded: set[str] | None = None) -> bool:
    """Check whether a path from master is allowed in the target release branch."""
    posix = _normalize_posix(rel_path)
    if not posix:
        return False

    if extra_excluded:
        normalized_excluded = {_normalize_posix(p) for p in extra_excluded}
        if posix in normalized_excluded:
            return False

    parts = [p for p in posix.split("/") if p and p != "."]
    if not parts:
        return False

    root_part = parts[0]

    # Block pycache or compiled artifacts
    if any(p == "__pycache__" or p.endswith(".pyc") for p in parts):
        return False

    # Single root file check
    if len(parts) == 1:
        return root_part in ALLOWED_ROOT_FILES

    # Allowed root directories check
    if root_part in ALLOWED_ROOT_DIRS:
        return True

    # docs/ directory specific whitelist
    if root_part == "docs":
        if len(parts) > 1 and parts[1] in BANNED_DOCS_DIRS:
            return False
        return True

    return False


def run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Execute a git command and return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false"] + args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def get_repo_root() -> Path:
    """Return Git repository root directory."""
    code, stdout, stderr = run_git(["rev-parse", "--show-toplevel"])
    if code != 0:
        raise RuntimeError(f"Failed to find git repo root: {stderr}")
    return Path(stdout).resolve()


def get_current_branch(repo_dir: Path) -> str:
    """Return currently checked out branch name, or 'HEAD (detached)'."""
    code, stdout, stderr = run_git(["branch", "--show-current"], cwd=repo_dir)
    if code == 0 and stdout:
        return stdout

    # If --show-current is empty, check if we are in detached HEAD state
    code_ref, stdout_ref, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
    if code_ref == 0 and stdout_ref == "HEAD":
        return "HEAD (detached)"

    return stdout or "unknown"


def get_commit_hash(repo_dir: Path, ref: str = "HEAD") -> str:
    """Return short commit hash for given ref."""
    code, stdout, stderr = run_git(["rev-parse", "--short=8", ref], cwd=repo_dir)
    if code != 0:
        raise RuntimeError(f"Failed to get commit hash for {ref}: {stderr}")
    return stdout


def is_working_tree_clean(repo_dir: Path) -> bool:
    """Check if repository working tree has no uncommitted changes."""
    code, stdout, _ = run_git(["status", "--porcelain"], cwd=repo_dir)
    return code == 0 and len(stdout) == 0


def get_candidate_files(repo_dir: Path, allow_dirty: bool = False) -> list[Path]:
    """Return list of candidate files from master to consider for release sync."""
    code, stdout, stderr = run_git(["ls-files"], cwd=repo_dir)
    if code != 0:
        raise RuntimeError(f"Failed to list tracked files: {stderr}")

    files_set = {Path(line.strip()) for line in stdout.splitlines() if line.strip()}

    if allow_dirty:
        code_oth, out_oth, _ = run_git(["ls-files", "--others", "--exclude-standard"], cwd=repo_dir)
        if code_oth == 0:
            for line in out_oth.splitlines():
                if line.strip():
                    files_set.add(Path(line.strip()))

    # Only keep files that actually exist on disk (prevents FileNotFoundError on deleted files)
    existing_files = [p for p in files_set if (repo_dir / p).is_file()]
    return sorted(existing_files)


def ensure_branch_exists(repo_dir: Path, branch_name: str) -> None:
    """Ensure target branch exists locally, creating it from origin or HEAD if needed."""
    code, _, _ = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"], cwd=repo_dir)
    if code == 0:
        return

    code, _, _ = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch_name}"],
        cwd=repo_dir,
    )
    if code == 0:
        code_track, _, err = run_git(
            ["branch", "--track", branch_name, f"origin/{branch_name}"],
            cwd=repo_dir,
        )
        if code_track != 0:
            raise RuntimeError(f"Failed to track origin/{branch_name}: {err}")
        return

    code_create, _, err = run_git(["branch", branch_name, "HEAD"], cwd=repo_dir)
    if code_create != 0:
        raise RuntimeError(f"Failed to create local {branch_name} branch: {err}")


def ensure_release_branch_exists(repo_dir: Path) -> None:
    """Ensure release branch exists locally, creating it if needed."""
    ensure_branch_exists(repo_dir, "release")


def _sync_branch_worktree(
    repo_dir: Path,
    branch_name: str,
    allowed_files: list[Path],
    commit_msg: str,
) -> None:
    """Sync filtered files into a target branch using a temporary Git worktree."""
    ensure_branch_exists(repo_dir, branch_name)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"playwright_tools_{branch_name}_wt_"))
    try:
        print(f"[*] Adding temporary git worktree for '{branch_name}' at: {temp_dir}")
        code_wt, _, err_wt = run_git(["worktree", "add", str(temp_dir), branch_name], cwd=repo_dir)
        if code_wt != 0:
            raise RuntimeError(f"Failed to add git worktree for {branch_name}: {err_wt}")

        for item in temp_dir.iterdir():
            if item.name == ".git":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        for rel_path in allowed_files:
            src = repo_dir / rel_path
            dst = temp_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        code_add, _, err_add = run_git(["add", "-A"], cwd=temp_dir)
        if code_add != 0:
            raise RuntimeError(f"git add -A failed in worktree ({branch_name}): {err_add}")

        code_status, status_out, err_status = run_git(["status", "--porcelain"], cwd=temp_dir)
        if code_status != 0:
            raise RuntimeError(f"git status failed in worktree ({branch_name}): {err_status}")

        if not status_out.strip():
            print(f"[+] Branch '{branch_name}' is already up-to-date with master. Nothing to commit.")
        else:
            print(f"[*] Committing to '{branch_name}' branch with message: '{commit_msg}'...")
            code_commit, commit_out, err_commit = run_git(["commit", "-m", commit_msg], cwd=temp_dir)
            if code_commit != 0:
                raise RuntimeError(f"Git commit failed in worktree ({branch_name}): {err_commit}")
            print(f"[+] Successfully committed '{branch_name}':\n{commit_out}")
    finally:
        print(f"[*] Cleaning up temporary worktree: {temp_dir}")
        run_git(["worktree", "remove", "--force", str(temp_dir)], cwd=repo_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
        run_git(["worktree", "prune"], cwd=repo_dir)


def run_release(
    repo_dir: Path,
    allow_dirty: bool = False,
    push: bool = False,
    message: str | None = None,
    dry_run: bool = False,
) -> int:
    """Main release synchronization logic."""
    print(f"[*] Repository root: {repo_dir}")

    # 1. Check current branch
    current_branch = get_current_branch(repo_dir)
    if current_branch != "master":
        print(
            f"[!] Error: Release can only be run from 'master' branch (currently on '{current_branch}')",
            file=sys.stderr,
        )
        return 1

    # 2. Check cleanliness
    is_clean = is_working_tree_clean(repo_dir)
    if not is_clean and not allow_dirty:
        print(
            "[!] Error: Working tree has uncommitted changes. Commit or stash them, or pass --allow-dirty.",
            file=sys.stderr,
        )
        return 1

    # 3. Read metadata version
    metadata_path = repo_dir / "metadata.yaml"
    if not metadata_path.exists():
        print("[!] Error: metadata.yaml not found in repository root.", file=sys.stderr)
        return 1

    version = extract_version(metadata_path.read_text(encoding="utf-8"))
    commit_hash = get_commit_hash(repo_dir, "HEAD")
    dirty_marker = " (dirty)" if not is_clean else ""
    print(f"[*] Target release version: {version} (sync from master commit {commit_hash}{dirty_marker})")

    # 4. Resolve tracked files and filter per target branch
    candidate_files = get_candidate_files(repo_dir, allow_dirty=allow_dirty)
    target_plans: dict[str, tuple[list[Path], list[Path]]] = {}
    for branch_name, extra_excluded in RELEASE_TARGETS.items():
        allowed_files = [
            p for p in candidate_files if is_path_allowed(p, extra_excluded=extra_excluded)
        ]
        excluded_files = [
            p for p in candidate_files if not is_path_allowed(p, extra_excluded=extra_excluded)
        ]
        target_plans[branch_name] = (allowed_files, excluded_files)
        print(
            f"[*] [{branch_name}] Filtered {len(allowed_files)} files to keep ({len(excluded_files)} excluded)."
        )

    if dry_run:
        for branch_name, (allowed_files, excluded_files) in target_plans.items():
            print(f"\n--- [DRY-RUN:{branch_name}] Files to be retained ({len(allowed_files)}) ---")
            for p in sorted(allowed_files):
                print(f"  + {p.as_posix()}")
            print(f"\n--- [DRY-RUN:{branch_name}] Files to be excluded ({len(excluded_files)}) ---")
            for p in sorted(excluded_files):
                print(f"  - {p.as_posix()}")
        print("\n[+] Dry-run completed. No changes made.")
        return 0

    # 5. Sync all target branches locally first
    commit_msg = message or f"release: {version} (sync from master {commit_hash}{dirty_marker})"
    for branch_name, (allowed_files, _) in target_plans.items():
        _sync_branch_worktree(repo_dir, branch_name, allowed_files, commit_msg)

    # 6. Optional Push (only after all local branch commits succeed)
    if push:
        for branch_name in RELEASE_TARGETS:
            print(f"[*] Pushing '{branch_name}' branch to origin...")
            code_push, push_out, err_push = run_git(["push", "origin", branch_name], cwd=repo_dir)
            if code_push != 0:
                raise RuntimeError(f"Git push failed for {branch_name}: {err_push}")
            print(f"[+] Push succeeded for '{branch_name}':\n{push_out}")

    print("[+] Release sync workflow finished successfully.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synchronize filtered code from 'master' branch to 'release' branch."
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push release branch to origin after successful commit.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow running when master branch has uncommitted changes.",
    )
    parser.add_argument(
        "-m",
        "--message",
        type=str,
        default=None,
        help="Custom commit message for release commit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview files to be included and excluded without making any changes.",
    )

    args = parser.parse_args()

    try:
        repo_dir = get_repo_root()
        code = run_release(
            repo_dir=repo_dir,
            allow_dirty=args.allow_dirty,
            push=args.push,
            message=args.message,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
