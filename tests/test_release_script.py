import unittest
from pathlib import Path
from scripts.release import extract_version, is_path_allowed


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

    def test_is_path_allowed_excluded_dirs_and_files(self):
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


if __name__ == "__main__":
    unittest.main()
