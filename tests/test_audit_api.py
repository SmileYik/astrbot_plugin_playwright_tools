import unittest
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import astrbot_plugin_playwright_tools.api.audit_api as audit_api_module
from astrbot_plugin_playwright_tools.api.audit_api import AuditApiHandler


def run_coro(coro):
    result = None
    stack = [coro]
    while stack:
        try:
            val = stack[-1].send(None)
            if hasattr(val, "send"):
                stack.append(val)
        except StopIteration as e:
            stack.pop()
            if stack:
                try:
                    stack[-1].send(e.value)
                except StopIteration as e2:
                    stack.pop()
                    result = e2.value
            else:
                result = e.value
    return result


class TestAuditApi(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()
        self.handler = AuditApiHandler(self.mock_logger)

    def test_register_routes(self):
        mock_ctx = MagicMock()
        mock_ctx.register_web_api = MagicMock()

        self.handler.register_routes(mock_ctx, "my_plugin")

        self.assertEqual(mock_ctx.register_web_api.call_count, 5)
        calls = [c[0] for c in mock_ctx.register_web_api.call_args_list]
        routes_map = {c[0]: c[2] for c in calls}

        self.assertIn("/my_plugin/audit/logs", routes_map)
        self.assertEqual(routes_map["/my_plugin/audit/logs"], ["GET"])

        self.assertIn("/my_plugin/audit/stats", routes_map)
        self.assertEqual(routes_map["/my_plugin/audit/stats"], ["GET"])

        self.assertIn("/my_plugin/audit/export", routes_map)
        self.assertEqual(routes_map["/my_plugin/audit/export"], ["GET"])

        self.assertIn("/my_plugin/audit/clear", routes_map)
        self.assertEqual(routes_map["/my_plugin/audit/clear"], ["POST"])

        self.assertIn("/my_plugin/audit/screenshot", routes_map)
        self.assertEqual(routes_map["/my_plugin/audit/screenshot"], ["GET"])

    def test_api_audit_logs(self):
        async def mock_query(page, page_size, keyword, status, tool_name):
            return [{"id": 1}], 1
        self.mock_logger.query_logs = mock_query

        mock_req = MagicMock()
        mock_req.query.get.side_effect = lambda k, default=None: default
        audit_api_module.request = mock_req

        res = run_coro(self.handler.api_audit_logs())
        self.assertEqual(res["data"]["code"], 0)
        self.assertEqual(res["data"]["data"]["total"], 1)
        self.assertEqual(len(res["data"]["data"]["items"]), 1)

    def test_api_audit_stats(self):
        async def mock_stats():
            return {"total": 10, "allowed": 8}
        self.mock_logger.get_stats = mock_stats

        res = run_coro(self.handler.api_audit_stats())
        self.assertEqual(res["data"]["code"], 0)
        self.assertEqual(res["data"]["data"]["total"], 10)

    def test_api_audit_export(self):
        async def mock_export(fmt, keyword, status, tool_name):
            return '{"export": true}'
        self.mock_logger.export_logs = mock_export

        mock_req = MagicMock()
        mock_req.query.get.side_effect = lambda k, default=None: default
        audit_api_module.request = mock_req

        res = run_coro(self.handler.api_audit_export())
        self.assertEqual(res["data"]["code"], 0)
        self.assertEqual(res["data"]["data"], '{"export": true}')

    def test_api_audit_clear_reject_unconfirmed(self):
        mock_req = MagicMock()
        async def mock_json(default={}):
            return {"confirm": False}
        mock_req.json = mock_json
        audit_api_module.request = mock_req

        res = run_coro(self.handler.api_audit_clear())
        self.assertEqual(res["data"]["code"], -1)

    def test_api_audit_clear_confirmed(self):
        mock_req = MagicMock()
        async def mock_json(default={}):
            return {"confirm": True}
        mock_req.json = mock_json
        audit_api_module.request = mock_req

        async def mock_clear():
            return 5
        self.mock_logger.clear_logs = mock_clear

        res = run_coro(self.handler.api_audit_clear())
        self.assertEqual(res["data"]["code"], 0)
        self.assertEqual(res["data"]["data"]["cleared"], 5)

    def test_extract_query_param_multi_source_support(self):
        from astrbot_plugin_playwright_tools.api.audit_api import extract_query_param
        class FakeDashboardReqArgs:
            def __init__(self):
                self.args = {"page": "3", "keyword": "wiki"}
        req1 = FakeDashboardReqArgs()
        self.assertEqual(extract_query_param(req1, "page", 1, int), 3)
        self.assertEqual(extract_query_param(req1, "keyword", ""), "wiki")

        class FakeDashboardReqQueryParams:
            def __init__(self):
                self.query_params = {"page": "5"}
        req2 = FakeDashboardReqQueryParams()
        self.assertEqual(extract_query_param(req2, "page", 1, int), 5)

    def test_screenshot_route_blocks_directory_traversal(self):
        res = run_coro(self.handler.api_audit_screenshot(path="../../etc/passwd"))
        self.assertEqual(res["status_code"], 403)

    def test_screenshot_route_missing_path(self):
        audit_api_module.request = None
        res = run_coro(self.handler.api_audit_screenshot(path=""))
        self.assertEqual(res["status_code"], 400)

    def test_screenshot_route_file_not_found(self):
        audit_api_module.request = None
        res = run_coro(self.handler.api_audit_screenshot(path="data/audit_screenshots/non_existent.png"))
        self.assertEqual(res["status_code"], 404)

    def test_screenshot_route_png_streaming(self):
        import tempfile
        base_dir = Path(tempfile.gettempdir()) / "astrbot_test_audit_data"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.handler.base_dir = base_dir

        test_png = base_dir / "test_out.png"
        fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest_stream"
        with open(test_png, "wb") as f:
            f.write(fake_png_data)

        try:
            audit_api_module.request = None
            res = run_coro(self.handler.api_audit_screenshot(path=str(test_png), format="raw"))
            if isinstance(res, dict):
                self.assertEqual(res.get("status_code", 200), 200)
                self.assertEqual(res.get("media_type"), "image/png")
                self.assertEqual(res.get("data"), fake_png_data)
            else:
                self.assertEqual(getattr(res, "status_code", 200), 200)
                self.assertEqual(getattr(res, "media_type", ""), "image/png")
                if hasattr(res, "body"):
                    self.assertEqual(res.body, fake_png_data)
        finally:
            if test_png.exists():
                test_png.unlink()

    def test_screenshot_route_data_url_default(self):
        import tempfile
        import base64
        import json
        base_dir = Path(tempfile.gettempdir()) / "astrbot_test_audit_data"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.handler.base_dir = base_dir

        test_png = base_dir / "test_data_url.png"
        fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest_data_url"
        with open(test_png, "wb") as f:
            f.write(fake_png_data)

        try:
            audit_api_module.request = None
            res = run_coro(self.handler.api_audit_screenshot(path=str(test_png)))
            raw_payload = res.get("data", {}) if isinstance(res, dict) else json.loads(res.body)
            # handle both real Starlette JSONResponse (raw_payload["data"]) and mock wrapper (raw_payload["data"]["data"])
            if "data" in raw_payload and isinstance(raw_payload["data"], dict) and "data" in raw_payload["data"]:
                data = raw_payload["data"]["data"]
            elif "data" in raw_payload and isinstance(raw_payload["data"], dict) and "data_url" in raw_payload["data"]:
                data = raw_payload["data"]
            else:
                data = raw_payload
            expected_b64 = base64.b64encode(fake_png_data).decode("utf-8")
            self.assertEqual(data["media_type"], "image/png")
            self.assertEqual(data["data_url"], f"data:image/png;base64,{expected_b64}")
            self.assertEqual(data["filename"], "test_data_url.png")
        finally:
            if test_png.exists():
                test_png.unlink()

    def test_screenshot_route_jpeg_streaming(self):
        import tempfile
        base_dir = Path(tempfile.gettempdir()) / "astrbot_test_audit_data"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.handler.base_dir = base_dir

        test_jpg = base_dir / "test_out.jpg"
        fake_jpg_data = b"\xff\xd8\xff\xe0\x00\x10JFIFtest_stream"
        with open(test_jpg, "wb") as f:
            f.write(fake_jpg_data)

        try:
            audit_api_module.request = None
            res = run_coro(self.handler.api_audit_screenshot(path=str(test_jpg), format="raw"))
            if isinstance(res, dict):
                self.assertEqual(res.get("status_code", 200), 200)
                self.assertEqual(res.get("media_type"), "image/jpeg")
                self.assertEqual(res.get("data"), fake_jpg_data)
            else:
                self.assertEqual(getattr(res, "status_code", 200), 200)
                self.assertEqual(getattr(res, "media_type", ""), "image/jpeg")
                if hasattr(res, "body"):
                    self.assertEqual(res.body, fake_jpg_data)
        finally:
            if test_jpg.exists():
                test_jpg.unlink()


if __name__ == "__main__":
    unittest.main()
