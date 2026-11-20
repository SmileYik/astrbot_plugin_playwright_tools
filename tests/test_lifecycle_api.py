import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import astrbot_plugin_playwright_tools.api.lifecycle_api as lifecycle_api_module
from astrbot_plugin_playwright_tools.api.lifecycle_api import LifecycleApiHandler


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


class TestLifecycleApi(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.gettempdir()) / "astrbot_test_lifecycle"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.mock_mgr = MagicMock()
        self.mock_mgr.contexts = {}
        self.mock_audit = MagicMock()
        self.mock_media = MagicMock()
        self.mock_media.screenshot_dir = str(self.temp_dir)
        self.mock_media.screenshot_format = "png"
        self.mock_media.screenshot_quality = 80
        self.handler = LifecycleApiHandler(
            context_mgr=self.mock_mgr,
            audit_logger=self.mock_audit,
            media_handler=self.mock_media,
        )

    def test_register_routes(self):
        mock_ctx = MagicMock()
        mock_ctx.register_web_api = MagicMock()

        self.handler.register_routes(mock_ctx, "playwright_tools")

        self.assertEqual(mock_ctx.register_web_api.call_count, 4)
        calls = [c[0] for c in mock_ctx.register_web_api.call_args_list]
        routes_map = {c[0]: c[2] for c in calls}

        self.assertIn("/playwright_tools/lifecycle/active", routes_map)
        self.assertEqual(routes_map["/playwright_tools/lifecycle/active"], ["GET"])

        self.assertIn("/playwright_tools/lifecycle/logs", routes_map)
        self.assertEqual(routes_map["/playwright_tools/lifecycle/logs"], ["GET"])

        self.assertIn("/playwright_tools/lifecycle/screenshot", routes_map)
        self.assertEqual(routes_map["/playwright_tools/lifecycle/screenshot"], ["POST"])

        self.assertIn("/playwright_tools/lifecycle/kill", routes_map)
        self.assertEqual(routes_map["/playwright_tools/lifecycle/kill"], ["POST"])

    def test_api_active_contexts(self):
        async def mock_get_detail():
            return [
                {
                    "context_key": "sess_1:user_1",
                    "session_id": "sess_1",
                    "owner_id": "user_1",
                    "tab_count": 2,
                    "active_tab_url": "https://example.com",
                }
            ]

        self.mock_mgr.get_active_contexts_detail = mock_get_detail
        res = run_coro(self.handler.api_active_contexts())

        self.assertEqual(res["data"]["code"], 0)
        self.assertEqual(res["data"]["data"]["total"], 1)
        self.assertEqual(len(res["data"]["data"]["items"]), 1)
        self.assertEqual(res["data"]["data"]["items"][0]["context_key"], "sess_1:user_1")

    def test_api_lifecycle_logs(self):
        async def mock_query(page, page_size, session_id, event_type, keyword):
            return [{"id": 10, "event_type": event_type, "session_id": session_id}], 1

        self.mock_audit.query_lifecycle_logs = mock_query

        mock_req = MagicMock()
        mock_req.query.get.side_effect = lambda k, default=None: {
            "page": "2",
            "page_size": "10",
            "session_id": "sess_1",
            "event_type": "create",
            "keyword": "test",
        }.get(k, default)
        lifecycle_api_module.request = mock_req

        res = run_coro(self.handler.api_lifecycle_logs())
        self.assertEqual(res["data"]["code"], 0)
        self.assertEqual(res["data"]["data"]["total"], 1)
        self.assertEqual(res["data"]["data"]["page"], 2)
        self.assertEqual(res["data"]["data"]["page_size"], 10)
        self.assertEqual(res["data"]["data"]["items"][0]["event_type"], "create")

    def test_api_manual_screenshot_success(self):
        mock_page_0 = MagicMock()
        mock_page_0.url = "https://example.com/tab0"
        mock_page_1 = MagicMock()
        mock_page_1.url = "https://example.com/tab1"

        async def mock_screenshot(path=None, full_page=False, **kwargs):
            return b"fake_png_binary_data"

        mock_page_1.screenshot = mock_screenshot

        mock_session_ctx = MagicMock()
        mock_session_ctx.session_id = "sess_1"
        mock_session_ctx.owner_id = "user_1"
        mock_session_ctx.current_page = mock_page_0
        mock_session_ctx.pages = [mock_page_0, mock_page_1]
        self.mock_mgr.contexts = {("sess_1", "user_1"): mock_session_ctx}
        self.mock_mgr._format_context_key = lambda k: f"{k[0]}:{k[1]}" if isinstance(k, tuple) else str(k)

        logged_actions = []

        async def mock_log_action(**kwargs):
            logged_actions.append(kwargs)

        self.mock_audit.log_action = mock_log_action

        mock_req = MagicMock()

        async def mock_json():
            return {"context_key": "sess_1:user_1", "tab_index": 1}

        mock_req.json = mock_json
        lifecycle_api_module.request = mock_req

        res = run_coro(self.handler.api_manual_screenshot())
        self.assertEqual(res["data"]["code"], 0)
        shot_path = res["data"]["data"]["screenshot_path"]
        self.assertTrue(os.path.exists(shot_path))
        with open(shot_path, "rb") as f:
            self.assertEqual(f.read(), b"fake_png_binary_data")

        # Clean up created file
        try:
            os.remove(shot_path)
        except OSError:
            pass

        self.assertEqual(len(logged_actions), 1)
        action = logged_actions[0]
        self.assertEqual(action["tool_name"], "manual_screenshot")
        self.assertTrue(action["is_permitted"])
        self.assertEqual(action["screenshot_path"], shot_path)
        self.assertEqual(action["output_result"], f"[IMAGE_PATH:{shot_path}]")
        self.assertEqual(action["session_id"], "sess_1")
        self.assertEqual(action["context_key"], "sess_1:user_1")

    def test_api_manual_screenshot_default_page(self):
        mock_page_0 = MagicMock()
        mock_page_0.url = "https://example.com/default"

        async def mock_screenshot(path=None, full_page=False, **kwargs):
            return b"default_page_screenshot"

        mock_page_0.screenshot = mock_screenshot

        mock_session_ctx = MagicMock()
        mock_session_ctx.session_id = "sess_2"
        mock_session_ctx.owner_id = "user_2"
        mock_session_ctx.current_page = mock_page_0
        mock_session_ctx.pages = [mock_page_0]
        self.mock_mgr.contexts = {"sess_2": mock_session_ctx}
        self.mock_mgr._format_context_key = lambda k: str(k)

        async def mock_log_action(**kwargs):
            pass

        self.mock_audit.log_action = mock_log_action
        lifecycle_api_module.request = None

        res = run_coro(self.handler.api_manual_screenshot(context_key="sess_2"))
        self.assertEqual(res["data"]["code"], 0)
        shot_path = res["data"]["data"]["screenshot_path"]
        self.assertTrue(os.path.exists(shot_path))
        with open(shot_path, "rb") as f:
            self.assertEqual(f.read(), b"default_page_screenshot")
        try:
            os.remove(shot_path)
        except OSError:
            pass

    def test_api_manual_screenshot_context_not_found(self):
        self.mock_mgr.contexts = {}
        lifecycle_api_module.request = None
        res = run_coro(self.handler.api_manual_screenshot(context_key="unknown_key"))
        self.assertEqual(res["status_code"], 404)

    def test_api_manual_screenshot_missing_context_key(self):
        lifecycle_api_module.request = None
        res = run_coro(self.handler.api_manual_screenshot(context_key=""))
        self.assertEqual(res["status_code"], 400)

    def test_api_force_kill_success(self):
        async def mock_kill(context_key, operator_id):
            return True, "上下文已成功强制关闭并释放资源"

        self.mock_mgr.force_kill_context = mock_kill

        mock_req = MagicMock()

        async def mock_json():
            return {"context_key": "sess_1:user_1", "operator_id": "super_admin"}

        mock_req.json = mock_json
        lifecycle_api_module.request = mock_req

        res = run_coro(self.handler.api_force_kill())
        self.assertEqual(res["data"]["code"], 0)
        self.assertIn("成功强制关闭", res["data"]["data"]["message"])

    def test_api_force_kill_failure(self):
        async def mock_kill(context_key, operator_id):
            return False, "未找到上下文: not_exist"

        self.mock_mgr.force_kill_context = mock_kill
        lifecycle_api_module.request = None

        res = run_coro(self.handler.api_force_kill(context_key="not_exist"))
        self.assertEqual(res["status_code"], 400)

    def test_api_force_kill_missing_context_key(self):
        lifecycle_api_module.request = None
        res = run_coro(self.handler.api_force_kill(context_key=""))
        self.assertEqual(res["status_code"], 400)


if __name__ == "__main__":
    unittest.main()
