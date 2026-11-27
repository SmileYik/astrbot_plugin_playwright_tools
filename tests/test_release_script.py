import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.release import (
    extract_version,
    is_path_allowed,
    run_git,
    run_release,
)


class TestReleaseScript(unittest.TestCase):
    def test_extract_version_valid(self):
        content = 'name: astrbot_plugin_playwright_tools\nversion: "v1.4.5"\nauthor: SmileYik\n'
        self.assertEqual(extract_version(content), "v1.4.5")

    def test_extract_version_single_quotes(self):
        content = "name: test\nversion: '1.2.3'\n"
        self.assertEqual(extract_version(content), "1.2.3")

    def test_extract_version_unquoted(self):
        content = "name: test\nversion: v2.0.0\n"
        self.assertEqual(extract_version(content), "v2.0.0")

    def test_extract_version_with_comment_prefix(self):
        content = "# version: 9.9.9\nmin_version: 0.1\nversion: '1.4.5'\n"
        self.assertEqual(extract_version(content), "1.4.5")

    def test_extract_version_missing(self):
        content = "name: test\nauthor: SmileYik\n"
        with self.assertRaises(ValueError):
            extract_version(content)

    def test_is_path_allowed_runtime_code(self):
        self.assertTrue(is_path_allowed(Path("main.py")))
        self.assertTrue(is_path_allowed(Path("adapts/base.py")))
        self.assertTrue(is_path_allowed(Path("api/audit_api.py")))
        self.assertTrue(is_path_allowed(Path("core/history_cleaner.py")))
        self.assertTrue(is_path_allowed(Path("tools/tools.py")))

    def test_is_path_allowed_configs_and_views(self):
        self.assertTrue(is_path_allowed(Path("requirements.txt")))
        self.assertTrue(is_path_allowed(Path("metadata.yaml")))
        self.assertTrue(is_path_allowed(Path("_conf_schema.json")))
        self.assertTrue(is_path_allowed(Path(".gitignore")))
        self.assertTrue(is_path_allowed(Path("logo.png")))
        self.assertTrue(is_path_allowed(Path("views/browser/index.html")))
        self.assertTrue(is_path_allowed(Path("skills/playwright-tool/SKILL.md")))

    def test_is_path_allowed_public_docs(self):
        self.assertTrue(is_path_allowed(Path("README.md")))
        self.assertTrue(is_path_allowed(Path("CHANGELOG.md")))
        self.assertTrue(is_path_allowed(Path("LICENSE")))
        self.assertTrue(is_path_allowed(Path("docs/ARCHITECTURE.md")))
        self.assertTrue(is_path_allowed(Path("docs/EXTERNAL_API.md")))
        self.assertTrue(is_path_allowed(Path("docs/images/audit.png")))

    def test_is_path_allowed_strict_whitelist_blocks_unauthorized_files(self):
        # Unapproved root files must be blocked
        self.assertFalse(is_path_allowed(Path("random_dev_file.py")))
        self.assertFalse(is_path_allowed(Path("setup.cfg")))
        self.assertFalse(is_path_allowed(Path(".github/workflows/ci.yml")))
        self.assertFalse(is_path_allowed(Path(".vscode/settings.json")))

        # docs/ unapproved files must be blocked
        self.assertFalse(is_path_allowed(Path("docs/internal_spec.md")))
        self.assertFalse(is_path_allowed(Path("docs/notes.txt")))

        # Excluded test files
        self.assertFalse(is_path_allowed(Path("tests/test_tools.py")))
        self.assertFalse(is_path_allowed(Path("tests/__init__.py")))

        # Excluded web-src files
        self.assertFalse(is_path_allowed(Path("web-src/package.json")))
        self.assertFalse(is_path_allowed(Path("web-src/src/App.tsx")))

        # Excluded docs subdirs
        self.assertFalse(is_path_allowed(Path("docs/superpowers/plans/foo.md")))
        self.assertFalse(is_path_allowed(Path("docs/superpowers/specs/spec.md")))
        self.assertFalse(is_path_allowed(Path("docs/old/InitialRequirementsList.md")))

        # Excluded dev doc files
        self.assertFalse(is_path_allowed(Path("AGENT.md")))
        self.assertFalse(is_path_allowed(Path("HOW-TO-CODE.md")))

        # Excluded scripts & internal tooling
        self.assertFalse(is_path_allowed(Path("scripts/release.py")))
        self.assertFalse(is_path_allowed(Path("scripts/__init__.py")))


class TestReleaseScriptGitOrchestration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_release_git_")
        self.repo = Path(self.temp_dir)

        # Initialize mock git repository
        run_git(["init", "-b", "master"], cwd=self.repo)
        run_git(["config", "user.name", "Test User"], cwd=self.repo)
        run_git(["config", "user.email", "test@example.com"], cwd=self.repo)

        # Create basic files
        (self.repo / "metadata.yaml").write_text('name: test\nversion: "1.0.0"\n', encoding="utf-8")
        (self.repo / "main.py").write_text("# main entry\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# readme\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_dummy.py").write_text("# test\n", encoding="utf-8")
        (self.repo / "web-src").mkdir()
        (self.repo / "web-src" / "package.json").write_text("{}\n", encoding="utf-8")

        run_git(["add", "-A"], cwd=self.repo)
        run_git(["commit", "-m", "initial commit"], cwd=self.repo)

    def tearDown(self):
        # Prune worktrees before removing directory
        run_git(["worktree", "prune"], cwd=self.repo)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_non_master_branch_rejected(self):
        run_git(["checkout", "-b", "feature/dev"], cwd=self.repo)
        code = run_release(self.repo)
        self.assertEqual(code, 1)

    def test_detached_head_rejected(self):
        run_git(["checkout", "--detach", "HEAD"], cwd=self.repo)
        code = run_release(self.repo)
        self.assertEqual(code, 1)

    def test_dirty_tree_aborts_without_allow_dirty(self):
        (self.repo / "main.py").write_text("# dirty edit\n", encoding="utf-8")
        code = run_release(self.repo, allow_dirty=False)
        self.assertEqual(code, 1)

    def test_allow_dirty_handles_dirty_changes_and_commits(self):
        # Modify existing file and create new allowed file
        (self.repo / "main.py").write_text("# modified\n", encoding="utf-8")
        (self.repo / "requirements.txt").write_text("playwright\n", encoding="utf-8")
        code = run_release(self.repo, allow_dirty=True)
        self.assertEqual(code, 0)

        # Verify release branch has the new file and modified content
        code_files, stdout, _ = run_git(["ls-tree", "-r", "--name-only", "release"], cwd=self.repo)
        self.assertEqual(code_files, 0)
        self.assertIn("requirements.txt", stdout.splitlines())

    def test_dry_run_does_not_create_release_branch(self):
        code = run_release(self.repo, dry_run=True)
        self.assertEqual(code, 0)
        check_code, _, _ = run_git(["show-ref", "--verify", "--quiet", "refs/heads/release"], cwd=self.repo)
        self.assertNotEqual(check_code, 0)

    def test_clean_sync_creates_filtered_release_branch_and_cleans_worktree(self):
        code = run_release(self.repo)
        self.assertEqual(code, 0)

        # Check release branch exists
        check_code, _, _ = run_git(["show-ref", "--verify", "--quiet", "refs/heads/release"], cwd=self.repo)
        self.assertEqual(check_code, 0)

        # Check files on release branch
        code_files, stdout, _ = run_git(["ls-tree", "-r", "--name-only", "release"], cwd=self.repo)
        self.assertEqual(code_files, 0)
        files = stdout.splitlines()

        self.assertIn("main.py", files)
        self.assertIn("metadata.yaml", files)
        self.assertIn("README.md", files)
        self.assertNotIn("tests/test_dummy.py", files)
        self.assertNotIn("web-src/package.json", files)

        # Check worktrees are cleaned up
        code_wt, wt_out, _ = run_git(["worktree", "list"], cwd=self.repo)
        self.assertEqual(code_wt, 0)
        self.assertEqual(len(wt_out.splitlines()), 1)  # Only master worktree


if __name__ == "__main__":
    unittest.main()
