import unittest
import os
import sys
from unittest.mock import MagicMock, AsyncMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from astrbot_plugin_playwright_tools.tools.handlers.page_handler import PageHandler
from astrbot_plugin_playwright_tools.core.readers.base import PageSnapshot

def run_coro(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

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
            ref_map={1: {"tag": "button", "text": "点击"}},
            total_pages=1,
            chunks=["=== 页面内容 [分页: 1/1] ===\n页面正文内容"]
        )
        self.mock_reader.extract_snapshot = AsyncMock(return_value=self.fake_snapshot)
        self.mock_reader.format_chunk = MagicMock(return_value="格式化切片内容 [第 1 页]")
        self.mock_reader.search = MagicMock(return_value="检索结果: 找到 1 处匹配")

        self.mock_page = MagicMock()
        self.mock_page.url = "https://example.com"
        self.mock_page.goto = AsyncMock()
        self.mock_page.title = AsyncMock(return_value="Test Page")

        self.mock_context = MagicMock()
        self.mock_context.owner_id = "u1"
        self.mock_context.current_page = self.mock_page
        self.mock_context.ref_map = {}
        self.mock_context.pages = [self.mock_page]
        self.mock_context.browser_context.pages = [self.mock_page]
        self.mock_context.current_snapshot = None
        self.mock_context.is_snapshot_dirty = False

        async def mock_resolve(session_id, sender_id):
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

    def test_read_page_with_keyword(self):
        res = run_coro(self.handler.read_page("s1", "u1", keyword="搜索词"))
        self.mock_reader.search.assert_called_once_with(self.fake_snapshot, "搜索词")
        self.assertIn("检索结果: 找到 1 处匹配", res)

    def test_search_page_backward_compatibility(self):
        res = run_coro(self.handler.search_page("s1", "u1", keyword="搜索关键词"))
        self.mock_reader.search.assert_called_with(self.fake_snapshot, "搜索关键词")
        self.assertIn("检索结果: 找到 1 处匹配", res)

    def test_handle_dialog_action(self):
        res = run_coro(self.handler.handle_dialog("s1", "u1", action="dismiss"))
        self.assertEqual(self.mock_context.dialog_action, {"action": "dismiss", "prompt_text": None})
        self.assertIn("已预设", res)

if __name__ == "__main__":
    unittest.main()
