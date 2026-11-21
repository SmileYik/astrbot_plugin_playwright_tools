import unittest
import json
import os
import sys
import tempfile
import yaml
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

TEMP_DIR = Path(tempfile.gettempdir()) / "astrbot_test_plugin_main"

# Ensure mock astrbot is available before importing main
def _mock_dec(*args, **kwargs):
    def wrap(f):
        return f
    return wrap

mock_astrbot = MagicMock()
mock_api = MagicMock()
mock_event = MagicMock()
mock_filter = MagicMock()
mock_filter.command.side_effect = _mock_dec
mock_filter.on_llm_request.side_effect = _mock_dec
mock_filter.llm_tool.side_effect = _mock_dec
mock_event.filter = mock_filter

mock_star_module = MagicMock()
mock_star_module.register.side_effect = _mock_dec
class Star:
    def __init__(self, ctx):
        self.context = ctx
mock_star_module.Star = Star

mock_web_module = MagicMock()
mock_web_module.json_response = lambda data, status_code=200, headers=None: {"data": data, "status_code": status_code}
mock_web_module.error_response = lambda msg, status_code=400: {"error": msg, "status_code": status_code}

sys.modules["astrbot"] = mock_astrbot
sys.modules["astrbot.api"] = mock_api
sys.modules["astrbot.api.event"] = mock_event
sys.modules["astrbot.api.star"] = mock_star_module
sys.modules["astrbot.api.web"] = mock_web_module

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
import astrbot_plugin_playwright_tools.main as main
import astrbot_plugin_playwright_tools.api.audit_api as audit_api_module
import astrbot_plugin_playwright_tools.api.lifecycle_api as lifecycle_api_module

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

def collect_async_gen(agen):
    results = []
    try:
        while True:
            val = run_coro(agen.asend(None))
            results.append(val)
    except StopAsyncIteration:
        pass
    return results

class TestPluginMain(unittest.TestCase):
    def test_conf_schema_valid_json(self):
        schema_path = Path("_conf_schema.json")
        self.assertTrue(schema_path.exists(), "_conf_schema.json must exist")
        with open(schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("security", data)
        self.assertIn("runtime", data)
        self.assertIn("browser", data)
        self.assertIn("media", data)
        self.assertIn("storage_audit", data)

    def test_metadata_synced(self):
        meta_path = Path("metadata.yaml")
        self.assertTrue(meta_path.exists())
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f)
        self.assertEqual(meta["name"], "astrbot_plugin_playwright_tools")
        self.assertEqual(meta["display_name"], "PlaywrightTool")
        self.assertEqual(meta["version"], "v1.0.0")

    def test_conf_schema_v2_fields(self):
        with open("_conf_schema.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("tool_execution_timeout_seconds", data["runtime"]["items"])
        self.assertIn("screenshot_max_height_px", data["media"]["items"])
        self.assertIn("screenshot_timeout_seconds", data["media"]["items"])
        self.assertIn("system_prompt_injection", data["runtime"]["items"])
        self.assertIn("mask_password_inputs", data["security"]["items"])
        self.assertIn("content_extraction_mode", data["runtime"]["items"])
        self.assertIn("page_chunk_char_limit", data["runtime"]["items"])

    def test_storage_paths_default_to_plugin_data(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        mock_ctx = MagicMock()
        mock_ctx.add_llm_tools = MagicMock()
        with patch.object(main.AuditLogger, "_ensure_db", return_value=None):
            self.plugin = main.PlaywrightToolPlugin(mock_ctx, config={})
        self.assertEqual(
            self.plugin.download_save_path,
            "data/plugin_data/astrbot_plugin_playwright_tools/downloads",
        )
        self.assertEqual(
            self.plugin.screenshot_save_path,
            "data/plugin_data/astrbot_plugin_playwright_tools/screenshots",
        )
        self.assertEqual(
            self.plugin.audit_db_path,
            "data/plugin_data/astrbot_plugin_playwright_tools/audit.db",
        )
        self.assertEqual(
            self.plugin.media_handler.download_dir,
            "data/plugin_data/astrbot_plugin_playwright_tools/downloads",
        )
        self.assertEqual(
            self.plugin.media_handler.screenshot_dir,
            "data/plugin_data/astrbot_plugin_playwright_tools/screenshots",
        )
        self.assertEqual(
            self.plugin.media_handler.audit_screenshots_dir,
            "data/plugin_data/astrbot_plugin_playwright_tools/audit_screenshots",
        )

    def test_requirements_playwright_version(self):
        req_path = Path("requirements.txt")
        self.assertTrue(req_path.exists())
        content = req_path.read_text(encoding="utf-8")
        self.assertIn("playwright>=1.62.0", content)


    def test_plugin_init_and_tool_registration(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "reg_test.db")
        mock_ctx = MagicMock()
        mock_ctx.add_llm_tools = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
            "tool_execution_timeout_seconds": 25,
            "system_prompt_injection": "你是一个网页浏览助手。",
        })
        self.assertTrue(plugin.mask_password_inputs)
        self.assertTrue(plugin.page_handler.mask_password_inputs)
        self.assertTrue(plugin.interact_handler.mask_password_inputs)
        self.assertTrue(plugin.media_handler.mask_password_inputs)
        self.assertEqual(plugin.content_extraction_mode, "inline_markdown")
        self.assertEqual(plugin.page_chunk_char_limit, 2000)
        from astrbot_plugin_playwright_tools.core.readers import InlineMarkdownReader
        self.assertIsInstance(plugin.reader, InlineMarkdownReader)
        mock_ctx.add_llm_tools.assert_called_once()
        tools_registered = mock_ctx.add_llm_tools.call_args[0]
        self.assertEqual(len(tools_registered), 4)
        tool_names = [t.name for t in tools_registered]
        self.assertIn("pw_page", tool_names)
        self.assertIn("pw_read", tool_names)
        self.assertIn("pw_interact", tool_names)
        self.assertIn("pw_media", tool_names)

    def test_plugin_init_custom_extraction_and_security_configs(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "custom_cfg_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
            "security": {
                "mask_password_inputs": False,
            },
            "runtime": {
                "content_extraction_mode": "aria_snapshot",
                "page_chunk_char_limit": 3500,
            },
        })
        self.assertFalse(plugin.mask_password_inputs)
        self.assertFalse(plugin.page_handler.mask_password_inputs)
        self.assertFalse(plugin.interact_handler.mask_password_inputs)
        self.assertFalse(plugin.media_handler.mask_password_inputs)
        self.assertEqual(plugin.content_extraction_mode, "aria_snapshot")
        self.assertEqual(plugin.page_chunk_char_limit, 3500)
        from astrbot_plugin_playwright_tools.core.readers import AriaSnapshotReader
        self.assertIsInstance(plugin.reader, AriaSnapshotReader)

    def test_on_llm_request_injection(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "inj_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
            "system_prompt_injection": "CUSTOM_PROMPT",
        })
        req = MagicMock()
        req.system_prompt = "ORIGINAL_PROMPT"
        event = MagicMock()
        run_coro(plugin.on_llm_request(event, req))
        self.assertEqual(req.system_prompt, "ORIGINAL_PROMPT\n\nCUSTOM_PROMPT")

    def test_on_llm_request_empty_no_injection(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "empty_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
            "system_prompt_injection": "",
        })
        req = MagicMock()
        req.system_prompt = "ORIGINAL_PROMPT"
        event = MagicMock()
        event.get_sender_id.return_value = "admin_999"
        event.is_admin.return_value = True

        run_coro(plugin.on_llm_request(event, req))
        self.assertEqual(req.system_prompt, "ORIGINAL_PROMPT")
        self.assertIn("admin_999", plugin.security_manager.admin_uids)

    def test_metadata_views_declared(self):
        meta_path = Path("metadata.yaml")
        self.assertTrue(meta_path.exists())
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f)
        self.assertIn("views", meta)
        views = meta["views"]
        self.assertIsInstance(views, list)
        self.assertEqual(len(views), 1, "Should only declare a single unified SPA view")
        browser_view = views[0]
        self.assertEqual(browser_view.get("name"), "browser")
        self.assertEqual(browser_view.get("target"), "plugin_page")
        self.assertEqual(browser_view.get("title"), "网页工具控制台")

    def test_web_api_routes_registered(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "web_api_test.db")
        mock_ctx = MagicMock()
        mock_ctx.register_web_api = MagicMock()

        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
        })

        self.assertEqual(mock_ctx.register_web_api.call_count, 9)
        registered_calls = [c[0] for c in mock_ctx.register_web_api.call_args_list]
        routes_map = {call[0]: call[2] for call in registered_calls}

        self.assertIn("/astrbot_plugin_playwright_tools/audit/logs", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/audit/logs"], ["GET"])

        self.assertIn("/astrbot_plugin_playwright_tools/audit/stats", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/audit/stats"], ["GET"])

        self.assertIn("/astrbot_plugin_playwright_tools/audit/export", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/audit/export"], ["GET"])

        self.assertIn("/astrbot_plugin_playwright_tools/audit/clear", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/audit/clear"], ["POST"])

        self.assertIn("/astrbot_plugin_playwright_tools/audit/screenshot", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/audit/screenshot"], ["GET"])

        self.assertIn("/astrbot_plugin_playwright_tools/lifecycle/active", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/lifecycle/active"], ["GET"])

        self.assertIn("/astrbot_plugin_playwright_tools/lifecycle/logs", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/lifecycle/logs"], ["GET"])

        self.assertIn("/astrbot_plugin_playwright_tools/lifecycle/screenshot", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/lifecycle/screenshot"], ["POST"])

        self.assertIn("/astrbot_plugin_playwright_tools/lifecycle/kill", routes_map)
        self.assertEqual(routes_map["/astrbot_plugin_playwright_tools/lifecycle/kill"], ["POST"])

    def test_web_api_handlers_call(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "handlers_call_test.db")
        if os.path.exists(db_file):
            os.remove(db_file)
        mock_ctx = MagicMock()
        mock_ctx.register_web_api = MagicMock()

        # 配置 mock request
        mock_req = MagicMock()
        mock_req.query.get.side_effect = lambda k, default=None, **kw: default
        audit_api_module.request = mock_req
        main.request = mock_req

        plugin = main.PlaywrightToolPlugin(mock_ctx, config={
            "audit_db_path": db_file,
        })

        # 写入一条审计记录
        run_coro(plugin.audit_logger.log_action(
            session_id="s1", context_key="c1", sender_id="u1",
            tool_name="click", is_permitted=True, session_name="群1", sender_name="用户1"
        ))

        # 1. 验证 api_audit_logs
        res_logs = run_coro(plugin.api_audit_logs())
        self.assertNotIn("code", res_logs["data"])
        self.assertEqual(res_logs["data"]["total"], 1)

        # 2. 验证 api_audit_stats
        res_stats = run_coro(plugin.api_audit_stats())
        self.assertNotIn("code", res_stats["data"])
        self.assertEqual(res_stats["data"]["total"], 1)

        # 3. 验证 api_audit_export
        res_export = run_coro(plugin.api_audit_export())
        self.assertNotIn("code", res_export["data"])
        self.assertIn("用户1", res_export["data"]["content"])

        # 4. 验证 api_audit_clear 拒绝未确认
        res_clear_reject = run_coro(plugin.api_audit_clear())
        self.assertEqual(res_clear_reject["data"]["code"], -1)

        # 模拟确认清空
        async def mock_json(default={}):
            return {"confirm": True}
        mock_req2 = MagicMock()
        mock_req2.json = mock_json
        audit_api_module.request = mock_req2
        main.request = mock_req2

        res_clear = run_coro(plugin.api_audit_clear())
        self.assertEqual(res_clear["data"]["code"], 0)
        self.assertEqual(res_clear["data"]["data"]["cleared"], 1)

        # 再次获取 stats 验证已被清空
        res_stats_after = run_coro(plugin.api_audit_stats())
        self.assertEqual(res_stats_after["data"]["total"], 0)

    def test_plugin_config_initialization_with_new_audit_and_extractor_settings(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "new_cfg_test.db")
        mock_ctx = MagicMock()
        mock_ctx.add_llm_tools = MagicMock()
        cfg = {
            "audit_db_path": db_file,
            "audit_max_output_chars": 5000,
            "audit_save_screenshots": False,
            "element_multiline_separator": " / "
        }
        plugin = main.PlaywrightToolPlugin(mock_ctx, config=cfg)
        self.assertEqual(plugin.audit_logger.max_output_chars, 5000)
        self.assertFalse(plugin.media_handler.audit_save_screenshots)

    def test_plugin_wiring_adapter_and_handlers(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "wiring_test.db")
        mock_ctx = MagicMock()
        mock_ctx.add_llm_tools = MagicMock()
        mock_ctx.register_web_api = MagicMock()

        cfg = {
            "audit_db_path": db_file,
            "browser": {
                "browser_adapter": "playwright",
                "playwright_browser_type": "firefox",
                "browser_headless": True,
            },
            "media": {
                "screenshot_format": "jpeg",
                "screenshot_quality": 85,
            },
            "storage_audit": {
                "download_save_path": "data/custom_downloads",
                "screenshot_save_path": "data/custom_screenshots",
                "file_retention_days": 14,
            },
        }
        plugin = main.PlaywrightToolPlugin(mock_ctx, config=cfg)

        # 1. AdapterFactory 接入与 PlaywrightAdapter 实例化
        from astrbot_plugin_playwright_tools.adapts.playwright_adapter import PlaywrightAdapter
        self.assertIsInstance(plugin.adapter, PlaywrightAdapter)
        self.assertEqual(plugin.adapter.browser_type, "firefox")

        # 2. ContextManager 注入 audit_logger
        self.assertIs(plugin.context_manager.audit_logger, plugin.audit_logger)

        # 3. MediaHandler 接入扩展配置
        self.assertEqual(plugin.media_handler.screenshot_format, "jpeg")
        self.assertEqual(plugin.media_handler.screenshot_quality, 85)
        self.assertEqual(plugin.media_handler.download_dir, "data/custom_downloads")
        self.assertEqual(plugin.media_handler.screenshot_dir, "data/custom_screenshots")
        self.assertEqual(plugin.media_handler.file_retention_days, 14)

        # 4. LifecycleApiHandler 实例
        from astrbot_plugin_playwright_tools.api.lifecycle_api import LifecycleApiHandler
        self.assertIsInstance(plugin.lifecycle_api, LifecycleApiHandler)
        self.assertIs(plugin.lifecycle_api.context_mgr, plugin.context_manager)
        self.assertIs(plugin.lifecycle_api.audit_logger, plugin.audit_logger)
        self.assertIs(plugin.lifecycle_api.media_handler, plugin.media_handler)

    def test_browser_cmd_list_empty_and_populated(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "cmd_list_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={"audit_db_path": db_file})

        event = MagicMock()
        event.session_id = "sess_100"
        event.get_sender_id.return_value = "user_100"
        event.is_admin.return_value = False
        event.plain_result = lambda text: text

        # 1. 活跃上下文为空
        async def mock_active_empty():
            return []
        plugin.context_manager.get_active_contexts_detail = mock_active_empty
        results = collect_async_gen(plugin.browser_cmd(event, sub_cmd="list"))
        self.assertEqual(results, ["当前会话暂无活跃的浏览器上下文。"])

        # 2. 存在不属于本会话的上下文
        async def mock_active_other():
            return [
                {
                    "context_key": "other:user_2:admin",
                    "session_id": "sess_other",
                    "owner_id": "user_2",
                    "allowed_users": ["user_2"],
                    "tab_count": 1,
                    "active_tab_url": "https://other.com",
                }
            ]
        plugin.context_manager.get_active_contexts_detail = mock_active_other
        results = collect_async_gen(plugin.browser_cmd(event, sub_cmd="list"))
        self.assertEqual(results, ["当前会话暂无活跃的浏览器上下文。"])

        # 3. 存在属于本会话的活跃上下文
        async def mock_active_matched():
            return [
                {
                    "context_key": "sess_100:user_100",
                    "session_id": "sess_100",
                    "owner_id": "user_100",
                    "allowed_users": ["user_100", "user_collab"],
                    "tab_count": 2,
                    "active_tab_url": "https://astrbot.org",
                }
            ]
        plugin.context_manager.get_active_contexts_detail = mock_active_matched
        results = collect_async_gen(plugin.browser_cmd(event, sub_cmd="list"))
        self.assertEqual(len(results), 1)
        out = results[0]
        self.assertIn("【当前会话活跃浏览器】", out)
        self.assertIn("共 1 个活跃上下文:", out)
        self.assertIn("1. Key: sess_100:user_100 | 所有者: user_100 | 协作者: user_100, user_collab | 标签页数: 2 | 当前: https://astrbot.org", out)

    def test_browser_cmd_list_all_admin_permission(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "cmd_list_all_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={"audit_db_path": db_file})

        # 1. 普通用户被拒绝
        event_user = MagicMock()
        event_user.session_id = "sess_1"
        event_user.get_sender_id.return_value = "normal_user"
        event_user.is_admin.return_value = False
        event_user.plain_result = lambda text: text

        results = collect_async_gen(plugin.browser_cmd(event_user, sub_cmd="list-all"))
        self.assertEqual(results, ["无权限：仅管理员可查看全部会话的活跃上下文。"])

        # 2. 管理员查看 - 暂无活跃
        event_admin = MagicMock()
        event_admin.session_id = "sess_1"
        event_admin.get_sender_id.return_value = "admin_user"
        event_admin.is_admin.return_value = True
        event_admin.plain_result = lambda text: text

        async def mock_active_empty():
            return []
        plugin.context_manager.get_active_contexts_detail = mock_active_empty
        results = collect_async_gen(plugin.browser_cmd(event_admin, sub_cmd="list-all"))
        self.assertEqual(results, ["全平台暂无活跃的浏览器上下文。"])

        # 3. 管理员查看 - 存在全平台上下文
        async def mock_active_all():
            return [
                {
                    "context_key": "sess_1:user_1",
                    "session_id": "sess_1",
                    "owner_id": "user_1",
                    "allowed_users": ["user_1"],
                    "tab_count": 1,
                    "active_tab_url": "https://test.com",
                },
                {
                    "context_key": "sess_2:user_2",
                    "session_id": "sess_2",
                    "owner_id": "user_2",
                    "allowed_users": ["user_2"],
                    "tab_count": 3,
                    "active_tab_url": "about:blank",
                }
            ]
        plugin.context_manager.get_active_contexts_detail = mock_active_all
        results = collect_async_gen(plugin.browser_cmd(event_admin, sub_cmd="list-all"))
        self.assertEqual(len(results), 1)
        out = results[0]
        self.assertIn("【全平台活跃浏览器】", out)
        self.assertIn("共 2 个活跃上下文:", out)
        self.assertIn("1. Key: sess_1:user_1 (会话: sess_1) | 所有者: user_1 | 协作者: user_1 | 标签页数: 1 | 当前: https://test.com", out)
        self.assertIn("2. Key: sess_2:user_2 (会话: sess_2) | 所有者: user_2 | 协作者: user_2 | 标签页数: 3 | 当前: about:blank", out)

    def test_browser_cmd_kill_permission_and_execution(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "cmd_kill_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={"audit_db_path": db_file})

        # 1. 普通用户被拒绝
        event_user = MagicMock()
        event_user.session_id = "sess_1"
        event_user.get_sender_id.return_value = "normal_user"
        event_user.is_admin.return_value = False
        event_user.plain_result = lambda text: text

        results = collect_async_gen(plugin.browser_cmd(event_user, sub_cmd="kill", arg="key1"))
        self.assertEqual(results, ["无权限：仅管理员可强行关闭上下文。"])

        # 2. 管理员缺少参数
        event_admin = MagicMock()
        event_admin.session_id = "sess_1"
        event_admin.get_sender_id.return_value = "admin_user"
        event_admin.is_admin.return_value = True
        event_admin.plain_result = lambda text: text

        results = collect_async_gen(plugin.browser_cmd(event_admin, sub_cmd="kill", arg="   "))
        self.assertEqual(results, ["请提供要关闭的 context_key，例如: /browser kill default:123456:admin"])

        # 3. 管理员成功销毁
        killed_args = []
        async def mock_force_kill(target_key, operator_id=None):
            killed_args.append((target_key, operator_id))
            return True, "上下文已成功强制关闭并释放资源"
        plugin.context_manager.force_kill_context = mock_force_kill

        results = collect_async_gen(plugin.browser_cmd(event_admin, sub_cmd="kill", arg="sess_1:user_1"))
        self.assertEqual(results, ["上下文已成功强制关闭并释放资源"])
        self.assertEqual(killed_args, [("sess_1:user_1", "admin_user")])

    def test_browser_cmd_help_text(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / "cmd_help_test.db")
        mock_ctx = MagicMock()
        plugin = main.PlaywrightToolPlugin(mock_ctx, config={"audit_db_path": db_file})

        event = MagicMock()
        event.session_id = "sess_1"
        event.get_sender_id.return_value = "user_1"
        event.is_admin.return_value = False
        event.plain_result = lambda text: text

        results = collect_async_gen(plugin.browser_cmd(event, sub_cmd="unknown_cmd"))
        self.assertEqual(len(results), 1)
        help_msg = results[0]
        self.assertIn("/browser list", help_msg)
        self.assertIn("/browser list-all", help_msg)
        self.assertIn("/browser kill", help_msg)

    def test_api_traceback_and_lifecycle_metadata_integration(self):
        import uuid
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        db_file = str(TEMP_DIR / f"api_traceback_test_{uuid.uuid4().hex}.db")
        mock_ctx = MagicMock()
        mock_req = MagicMock()
        mock_req.query.get.side_effect = lambda k, default=None, **kw: default
        audit_api_module.request = mock_req
        lifecycle_api_module.request = mock_req
        main.request = mock_req

        plugin = main.PlaywrightToolPlugin(mock_ctx, config={"audit_db_path": db_file})

        # 1. 验证记录并拉取异常堆栈
        traceback_content = "Exception: Page.evaluate failure\n\nTraceback (most recent call last):\n  File 'test.py', line 10\n"
        run_coro(plugin.audit_logger.log_action(
            session_id="s_err", context_key="s_err:u1", sender_id="u1",
            tool_name="read_page", is_permitted=True, is_error=True,
            error_message=traceback_content, session_name="异常会话", sender_name="用户A"
        ))
        res_logs = run_coro(plugin.api_audit_logs())
        items = res_logs["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertIn("Traceback (most recent call last):", items[0]["error_message"])

        # 2. 验证生命周期记录名称与ID完整返回
        run_coro(plugin.audit_logger.log_lifecycle(
            session_id="s_lc", context_key="s_lc:u2", owner_id="u2",
            event_type="create", operator_id="u2",
            session_name="开发群", operator_name="李四", owner_name="李四"
        ))
        res_lc = run_coro(plugin.lifecycle_api.api_lifecycle_logs())
        lc_items = res_lc["data"]["items"]
        self.assertEqual(len(lc_items), 1)
        self.assertEqual(lc_items[0]["session_name"], "开发群")
        self.assertEqual(lc_items[0]["session_id"], "s_lc")
        self.assertEqual(lc_items[0]["operator_name"], "李四")
        self.assertEqual(lc_items[0]["operator_id"], "u2")
        self.assertEqual(lc_items[0]["owner_name"], "李四")
        self.assertEqual(lc_items[0]["owner_id"], "u2")

if __name__ == "__main__":
    unittest.main()
