import json
import unittest


def test_conf_schema_contains_new_fields():
    with open("_conf_schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)

    expected_fields = [
        "browser_adapter",
        "playwright_browser_type",
        "browser_executable_path",
        "browser_window_width",
        "browser_window_height",
        "browser_user_agent",
        "browser_headless",
        "camoufox_geoip",
        "screenshot_format",
        "screenshot_quality",
        "download_save_path",
        "screenshot_save_path",
        "file_retention_days",
    ]
    for field in expected_fields:
        assert field in schema, f"Missing field {field} in _conf_schema.json"
        assert "type" in schema[field]
        assert "default" in schema[field]


def test_conf_schema_defaults_and_types():
    with open("_conf_schema.json", "r", encoding="utf-8") as f:
        schema = json.load(f)
    assert schema["browser_adapter"]["default"] == "camoufox"
    assert schema["playwright_browser_type"]["default"] == "chromium"
    assert schema["browser_executable_path"]["default"] == ""
    assert schema["browser_window_width"]["default"] == 1280
    assert schema["browser_window_height"]["default"] == 720
    assert schema["browser_headless"]["default"] is True
    assert schema["screenshot_format"]["default"] == "png"
    assert schema["screenshot_quality"]["default"] == 80
    assert schema["file_retention_days"]["default"] == 7
    assert schema["download_save_path"]["default"] == "data/downloads"
    assert schema["screenshot_save_path"]["default"] == "data/screenshots"


class TestConfSchema(unittest.TestCase):
    def test_conf_schema_contains_new_fields(self):
        test_conf_schema_contains_new_fields()

    def test_conf_schema_defaults_and_types(self):
        test_conf_schema_defaults_and_types()


if __name__ == "__main__":
    unittest.main()
