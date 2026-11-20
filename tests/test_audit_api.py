import unittest
import os
import sys
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

        self.assertEqual(mock_ctx.register_web_api.call_count, 4)
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


if __name__ == "__main__":
    unittest.main()
