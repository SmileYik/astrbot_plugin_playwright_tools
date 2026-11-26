import unittest
import os
import sys
import time
import asyncio
from unittest.mock import MagicMock, AsyncMock

if "astrbot" not in sys.modules:
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from astrbot_plugin_playwright_tools.tools.handlers.page_handler import PageHandler
from astrbot_plugin_playwright_tools.core.readers.base import PageSnapshot

def run_coro(coro):
    return asyncio.run(coro)

class TestPageHandler(unittest.TestCase):
    def setUp(self):
        self.mock_mgr = MagicMock()
        self.mock_sec = MagicMock()
        self.mock_sec.check_permission.return_value = (True, "")
        self.mock_sec.is_url_allowed_navigation.return_value = (True, "")
        self.mock_audit = MagicMock()

        async def mock_log(*args, **kwargs):
            return None
        self.mock_audit.log_action = mock_log

        self.mock_reader = MagicMock()
        self.fake_snapshot = PageSnapshot(
            title="Test Page",
            url="https://example.com",
            raw_content="页面正文内容",
            ref_map={"1": {"tag": "button", "text": "点击"}},
            total_pages=1,
            chunks=["=== 页面内容 [分页: 1/1] ===\n页面正文内容"],
            timestamp=time.time(),
        )
        self.mock_reader.extract_snapshot = AsyncMock(return_value=self.fake_snapshot)
        self.mock_reader.format_chunk = MagicMock(return_value="格式化切片内容 [第 1 页]")
        self.mock_reader.search = MagicMock(return_value="检索结果: 找到 1 处匹配")

        self.mock_page = MagicMock()
        self.mock_page.url = "https://example.com"
        self.mock_page.goto = AsyncMock()
        self.mock_page.title = AsyncMock(return_value="Test Page")
        self.mock_page.wait_for_load_state = AsyncMock()

        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.ref_map = {}
        self.mock_context.pages = [self.mock_page]
        self.mock_context.browser_context.pages = [self.mock_page]
        self.mock_context.current_snapshot = None
        self.mock_context.is_snapshot_dirty = False

        async def mock_resolve(session_id, sender_id, **kwargs):
            return self.mock_context, ""
        self.mock_mgr.resolve_context = mock_resolve

        self.handler = PageHandler(
            self.mock_mgr,
            self.mock_sec,
            self.mock_audit,
            reader=self.mock_reader
        )

    def test_open_url_resets_snapshot_and_returns_recommendation(self):
        res = run_coro(self.handler.open_url("s1", "u1", "https://example.com"))
        self.mock_page.goto.assert_called_once()
        self.assertIsNone(self.mock_context.current_snapshot)
        self.assertTrue(self.mock_context.is_snapshot_dirty)
        self.assertIn("已成功打开网页: https://example.com", res)
        self.assertIn("[推荐操作: 请调用 pw_read() 查看页面内容与可操作元素]", res)

    def test_switch_tab_resets_snapshot_and_recommends_pw_read(self):
        res = run_coro(self.handler.switch_tab("s1", "u1", tab_index=1))
        self.assertIsNone(self.mock_context.current_snapshot)
        self.assertTrue(self.mock_context.is_snapshot_dirty)
        self.assertIn("已成功切换至标签页 1", res)
        self.assertIn("pw_read()", res)

    def test_switch_tab_out_of_bounds(self):
        res = run_coro(self.handler.switch_tab("s1", "u1", tab_index=99))
        self.assertIn("超出范围", res)

    def test_read_page_lazy_caching_and_dirty_invalidation(self):
        # 1. 首次读取：快照为空，触发 extract_snapshot
        res1 = run_coro(self.handler.read_page("s1", "u1", page=1))
        self.assertEqual(self.mock_reader.extract_snapshot.call_count, 1)
        self.assertEqual(self.mock_context.current_snapshot, self.fake_snapshot)
        self.assertEqual(self.mock_context.ref_map, self.fake_snapshot.ref_map)
        self.assertFalse(self.mock_context.is_snapshot_dirty)
        self.assertIn("格式化切片内容", res1)

        # 2. 第二次读取：dirty 为 False，且未要求 refresh，直接复用快照
        res2 = run_coro(self.handler.read_page("s1", "u1", page=1))
        self.assertEqual(self.mock_reader.extract_snapshot.call_count, 1)  # 没有重新提取
        self.assertIn("格式化切片内容", res2)

        # 3. 强制刷新：refresh=True，重新提取快照
        res3 = run_coro(self.handler.read_page("s1", "u1", page=1, refresh=True))
        self.assertEqual(self.mock_reader.extract_snapshot.call_count, 2)

        # 4. 脏标记置位：is_snapshot_dirty=True，重新提取快照并复位 dirty
        self.mock_context.is_snapshot_dirty = True
        res4 = run_coro(self.handler.read_page("s1", "u1", page=1))
        self.assertEqual(self.mock_reader.extract_snapshot.call_count, 3)
        self.assertFalse(self.mock_context.is_snapshot_dirty)

        # 5. 快照 TTL 超时失效：超过 60 秒自动失效重新提取
        self.fake_snapshot.timestamp = time.time() - 65
        res5 = run_coro(self.handler.read_page("s1", "u1", page=1))
        self.assertEqual(self.mock_reader.extract_snapshot.call_count, 4)

        # 6. URL 变化失效：当前页面 URL 与快照 URL 不一致，自动重新提取
        self.fake_snapshot.timestamp = time.time()
        self.mock_page.url = "https://example.com/subpage"
        res6 = run_coro(self.handler.read_page("s1", "u1", page=1))
        self.assertEqual(self.mock_reader.extract_snapshot.call_count, 5)

    def test_read_page_calls_wait_page_stable(self):
        run_coro(self.handler.read_page("s1", "u1", page=1))
        self.mock_page.wait_for_load_state.assert_called()

    def test_read_page_with_keyword(self):
        res = run_coro(self.handler.read_page("s1", "u1", keyword="搜索词"))
        self.mock_reader.search.assert_called_once_with(self.fake_snapshot, "搜索词")
        self.assertIn("检索结果: 找到 1 处匹配", res)

    def test_handle_dialog_action(self):
        res = run_coro(self.handler.handle_dialog("s1", "u1", action="dismiss"))
        self.assertEqual(self.mock_context.dialog_action, {"action": "dismiss", "prompt_text": None})
        self.assertIn("已预设", res)

    def test_read_page_advances_ref_id_monotonically(self):
        self.mock_context.ref_lock = asyncio.Lock()
        self.mock_context.next_ref_id = 10
        self.fake_snapshot.allocated_count = 5
        self.fake_snapshot.timestamp = time.time() - 100

        run_coro(self.handler.read_page("s1", "u1", page=1))
        self.assertEqual(self.mock_context.next_ref_id, 15)

    def test_read_page_query_ref_link_and_img(self):
        self.fake_snapshot.ref_map = {
            "1": {"ref": "1", "tag": "a", "text": "官方文档", "href": "https://example.com/docs", "src": ""},
            "2": {"ref": "2", "tag": "img", "text": "架构图", "alt": "架构图", "href": "", "src": "https://example.com/arch.png"},
            "3": {"ref": "3", "tag": "a", "text": "大图预览", "href": "https://example.com/view", "src": "https://example.com/thumb.png"},
            "4": {"ref": "4", "tag": "button", "text": "提交"},
        }
        self.mock_context.ref_map = self.fake_snapshot.ref_map

        # 1. 链接查询
        res_link = run_coro(self.handler.read_page("s1", "u1", ref="1"))
        self.assertIn("=== Ref 元素详情查询: [1] ===", res_link)
        self.assertIn("元素类型: 超链接", res_link)
        self.assertIn("https://example.com/docs", res_link)

        # 2. 图片查询
        res_img = run_coro(self.handler.read_page("s1", "u1", ref="2"))
        self.assertIn("元素类型: 图片", res_img)
        self.assertIn("https://example.com/arch.png", res_img)

        # 3. 含图链接查询
        res_both = run_coro(self.handler.read_page("s1", "u1", ref="3"))
        self.assertIn("元素类型: 超链接 (含图片)", res_both)
        self.assertIn("https://example.com/view", res_both)
        self.assertIn("https://example.com/thumb.png", res_both)

        # 4. 普通按钮查询
        res_btn = run_coro(self.handler.read_page("s1", "u1", ref="4"))
        self.assertIn("该元素不包含可跳转的超链接或图片 URL", res_btn)

        # 5. 不存在的 Ref
        res_none = run_coro(self.handler.read_page("s1", "u1", ref="999"))
        self.assertIn("未在当前快照中找到 Ref ID 为 '999' 的元素", res_none)

    def test_read_page_aria_mode_query_ref(self):
        self.fake_snapshot.ref_map = {
            "e1": {"ref": "e1", "tag": "a", "role": "link", "text": "登录入口", "href": "https://example.com/login", "src": ""},
            "e2": {"ref": "e2", "tag": "img", "role": "img", "text": "Logo", "alt": "Logo", "href": "", "src": "https://example.com/logo.png"},
            "e3": {"ref": "e3", "tag": "a", "role": "link", "text": "详情原图", "href": "https://example.com/detail", "src": "https://example.com/preview.png"},
        }
        self.mock_context.ref_map = self.fake_snapshot.ref_map

        res_link = run_coro(self.handler.read_page("s1", "u1", ref="e1"))
        self.assertIn("=== Ref 元素详情查询: [e1] ===", res_link)
        self.assertIn("元素类型: 超链接", res_link)
        self.assertIn("https://example.com/login", res_link)

        res_img = run_coro(self.handler.read_page("s1", "u1", ref="e2"))
        self.assertIn("=== Ref 元素详情查询: [e2] ===", res_img)
        self.assertIn("元素类型: 图片", res_img)
        self.assertIn("https://example.com/logo.png", res_img)

        res_both = run_coro(self.handler.read_page("s1", "u1", ref="e3"))
        self.assertIn("=== Ref 元素详情查询: [e3] ===", res_both)
        self.assertIn("元素类型: 超链接 (含图片)", res_both)
        self.assertIn("https://example.com/detail", res_both)
        self.assertIn("https://example.com/preview.png", res_both)

    def test_read_page_input_args_ref_handling(self):
        captured_input_args = []
        original_execute_action = self.handler.execute_action

        async def spy_execute_action(*args, **kwargs):
            captured_input_args.append(kwargs.get("input_args", {}))
            return await original_execute_action(*args, **kwargs)

        self.handler.execute_action = spy_execute_action

        # 1. 默认无 ref 调用，input_args 中绝不应包含 ref (避免触发 DOM 探测)
        run_coro(self.handler.read_page("s1", "u1", page=1))
        self.assertNotIn("ref", captured_input_args[-1])

        # 2. 传入全空白字符 ref，同样被清理剔除
        run_coro(self.handler.read_page("s1", "u1", page=1, ref="   "))
        self.assertNotIn("ref", captured_input_args[-1])

        # 3. 传入有效 ref，input_args 应包含清理后的 ref
        run_coro(self.handler.read_page("s1", "u1", ref="  123  "))
        self.assertIn("ref", captured_input_args[-1])
        self.assertEqual(captured_input_args[-1]["ref"], "123")


if __name__ == "__main__":
    unittest.main()
