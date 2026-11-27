#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Release branch synchronization script for astrbot_plugin_playwright_tools.

Synchronizes filtered runtime code and public documentation from 'master'
branch to 'release' branch using an isolated Git worktree.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_version(content: str) -> str:
    """Extract version string from metadata.yaml content."""
    match = re.search(r'version:\s*["\']?([^"\'\s]+)["\']?', content)
    if not match:
        raise ValueError("Could not find version field in metadata content")
    return match.group(1).strip()


def is_path_allowed(rel_path: Path | str) -> bool:
    """Check whether a path from master is allowed in the release branch."""
    path = Path(rel_path)
    parts = list(path.parts)
    if not parts:
        return False
    if parts[0] == ".":
        parts = parts[1:]
    if not parts:
        return False

    root_part = parts[0]
    posix = "/".join(parts)

    # Excluded directories at root level
    if root_part in {
        "tests",
        "web-src",
        "scripts",
        ".superpowers",
        ".venv",
        "__pycache__",
        "data",
        ".git",
    }:
        return False

    # Excluded specific files at root level
    if posix in {"AGENT.md", "HOW-TO-CODE.md"}:
        return False

    # Special rules for docs/ directory
    if root_part == "docs":
        if len(parts) > 1 and parts[1] in {"superpowers", "old"}:
            return False
        if posix in {"docs/ARCHITECTURE.md", "docs/EXTERNAL_API.md"} or (
            len(parts) > 1 and parts[1] == "images"
        ):
            return True
        return False

    # Exclude any compiled python artifacts or pycache
    if any(p == "__pycache__" or p.endswith(".pyc") for p in parts):
        return False

    return True


def run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Execute a git command and return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ["git"] + args,
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
    """Return currently checked out branch name."""
    code, stdout, stderr = run_git(["branch", "--show-current"], cwd=repo_dir)
    if code != 0 or not stdout:
        raise RuntimeError(f"Failed to get current branch: {stderr}")
    return stdout


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


def get_tracked_files_from_git(repo_dir: Path) -> list[Path]:
    """Return list of all files tracked by git in current HEAD."""
    code, stdout, stderr = run_git(["ls-tree", "-r", "--name-only", "HEAD"], cwd=repo_dir)
    if code != 0:
        raise RuntimeError(f"Failed to list tracked files: {stderr}")
    return [Path(line.strip()) for line in stdout.splitlines() if line.strip()]


def ensure_release_branch_exists(repo_dir: Path) -> None:
    """Ensure release branch exists locally, creating it if needed."""
    # Check if local release branch exists
    code, _, _ = run_git(["show-ref", "--verify", "--quiet", "refs/heads/release"], cwd=repo_dir)
    if code == 0:
        return

    # Check if remote tracking origin/release exists
    code, _, _ = run_git(["show-ref", "--verify", "--quiet", "refs/remotes/origin/release"], cwd=repo_dir)
    if code == 0:
        code_track, _, err = run_git(["branch", "--track", "release", "origin/release"], cwd=repo_dir)
        if code_track != 0:
            raise RuntimeError(f"Failed to track origin/release: {err}")
        return

    # Create local release branch based on current master HEAD
    code_create, _, err = run_git(["branch", "release", "HEAD"], cwd=repo_dir)
    if code_create != 0:
        raise RuntimeError(f"Failed to create local release branch: {err}")


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
        print(f"[!] Error: Release can only be run from 'master' branch (currently on '{current_branch}')", file=sys.stderr)
        return 1

    # 2. Check cleanliness
    if not is_working_tree_clean(repo_dir) and not allow_dirty:
        print("[!] Error: Working tree has uncommitted changes. Commit or stash them, or pass --allow-dirty.", file=sys.stderr)
        return 1

    # 3. Read metadata version
    metadata_path = repo_dir / "metadata.yaml"
    if not metadata_path.exists():
        print("[!] Error: metadata.yaml not found in repository root.", file=sys.stderr)
        return 1

    version = extract_version(metadata_path.read_text(encoding="utf-8"))
    commit_hash = get_commit_hash(repo_dir, "HEAD")
    print(f"[*] Target release version: {version} (sync from master commit {commit_hash})")

    # 4. Resolve tracked files and filter
    tracked_files = get_tracked_files_from_git(repo_dir)
    allowed_files = [p for p in tracked_files if is_path_allowed(p)]
    excluded_files = [p for p in tracked_files if not is_path_allowed(p)]

    print(f"[*] Filtered {len(allowed_files)} files to keep in release branch ({len(excluded_files)} excluded).")

    if dry_run:
        print("\n--- [DRY-RUN] Files to be retained in release branch ---")
        for p in sorted(allowed_files):
            print(f"  + {p.as_posix()}")
        print("\n--- [DRY-RUN] Files to be excluded from release branch ---")
        for p in sorted(excluded_files):
            print(f"  - {p.as_posix()}")
        print("\n[+] Dry-run completed. No changes made.")
        return 0

    # 5. Ensure release branch exists
    ensure_release_branch_exists(repo_dir)

    # 6. Mount temporary worktree
    temp_dir = Path(tempfile.mkdtemp(prefix="playwright_tools_release_wt_"))
    try:
        print(f"[*] Adding temporary git worktree at: {temp_dir}")
        code_wt, _, err_wt = run_git(["worktree", "add", str(temp_dir), "release"], cwd=repo_dir)
        if code_wt != 0:
            raise RuntimeError(f"Failed to add git worktree for release: {err_wt}")

        # 7. Clean existing tracked files in worktree (except .git)
        for item in temp_dir.iterdir():
            if item.name == ".git":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        # 8. Copy allowed files into worktree
        for rel_path in allowed_files:
            src = repo_dir / rel_path
            dst = temp_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        # 9. Check git status in worktree
        run_git(["add", "-A"], cwd=temp_dir)
        code_status, status_out, _ = run_git(["status", "--porcelain"], cwd=temp_dir)

        if not status_out.strip():
            print("[+] Release branch is already up-to-date with master. Nothing to commit.")
        else:
            commit_msg = message or f"release: {version} (sync from master {commit_hash})"
            print(f"[*] Committing to release branch with message: '{commit_msg}'...")
            code_commit, commit_out, err_commit = run_git(["commit", "-m", commit_msg], cwd=temp_dir)
            if code_commit != 0:
                raise RuntimeError(f"Git commit failed in worktree: {err_commit}")
            print(f"[+] Successfully committed release:\n{commit_out}")

        # 10. Optional Push
        if push:
            print("[*] Pushing release branch to origin...")
            code_push, push_out, err_push = run_git(["push", "origin", "release"], cwd=temp_dir)
            if code_push != 0:
                raise RuntimeError(f"Git push failed: {err_push}")
            print(f"[+] Push succeeded:\n{push_out}")

    finally:
        print(f"[*] Cleaning up temporary worktree: {temp_dir}")
        run_git(["worktree", "remove", "--force", str(temp_dir)], cwd=repo_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
        run_git(["worktree", "prune"], cwd=repo_dir)

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
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)

    code = run_release(
        repo_dir=repo_dir,
        allow_dirty=args.allow_dirty,
        push=args.push,
        message=args.message,
        dry_run=args.dry_run,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
