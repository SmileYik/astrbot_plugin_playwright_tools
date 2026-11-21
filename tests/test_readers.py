import os
import sys
import unittest
from unittest.mock import AsyncMock

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.readers.markdown_reader import InlineMarkdownReader
from core.readers.base import BasePageReader, PageSnapshot


def run_coro(coro):
    """在无网络沙箱环境下无开销执行普通协程，规避 socket.socketpair 挂起问题。"""
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


class TestInlineMarkdownReader(unittest.TestCase):
    def test_semantic_block_chunking_preserves_elements(self):
        reader = InlineMarkdownReader(chunk_char_limit=150, mask_passwords=True)
        blocks = [
            "# 标题一",
            "这是第一节详细介绍段落，长度适中。",
            "## 标题二\n- [Ref: 1] [按钮: 点击下载]\n- 状态说明: 推荐选项",
            "## 标题三\n- [Ref: 2] [链接: 历史版本目录]",
        ]
        chunks = reader._chunk_blocks(blocks, "https://example.com", "测试网页")
        self.assertGreaterEqual(len(chunks), 2)
        # 验证每个切片内 ref 完整，且切片首尾包含分页提示
        self.assertIn("[Ref: 1]", "".join(chunks))
        self.assertIn("[分页:", chunks[0])

    def test_password_masking_switch(self):
        reader_masked = InlineMarkdownReader(mask_passwords=True)
        html_script = reader_masked.get_js_extractor_script()
        self.assertIn("******", html_script)
        reader_unmasked = InlineMarkdownReader(mask_passwords=False)
        html_script_unmasked = reader_unmasked.get_js_extractor_script()
        self.assertNotIn("******", html_script_unmasked)

    def test_extract_snapshot_with_mock_page(self):
        reader = InlineMarkdownReader(chunk_char_limit=2000, mask_passwords=True)
        mock_page = AsyncMock()

        async def fake_eval(script):
            return {
                "title": "测试控制台",
                "url": "https://example.com/dashboard",
                "blocks": [
                    "# 控制台",
                    "欢迎来到管理后台。",
                    "- [Ref: 1] [按钮: 退出登录]",
                ],
                "elements": [
                    {"ref": 1, "tag": "button", "text": "退出登录"},
                ],
            }

        mock_page.evaluate = fake_eval

        snapshot = run_coro(reader.extract_snapshot(mock_page, "https://example.com/dashboard"))
        self.assertIsInstance(snapshot, PageSnapshot)
        self.assertEqual(snapshot.title, "测试控制台")
        self.assertEqual(snapshot.url, "https://example.com/dashboard")
        self.assertEqual(len(snapshot.chunks), 1)
        self.assertEqual(snapshot.total_pages, 1)
        self.assertIn(1, snapshot.ref_map)
        self.assertEqual(snapshot.ref_map[1]["text"], "退出登录")
        self.assertIn("[Ref: 1] [按钮: 退出登录]", snapshot.chunks[0])

    def test_format_chunk(self):
        reader = InlineMarkdownReader(chunk_char_limit=150)
        snapshot = PageSnapshot(
            title="标题",
            url="https://example.com",
            raw_content=["# 标题", "内容"],
            ref_map={},
            total_pages=2,
            chunks=["第 1 页内容", "第 2 页内容"],
        )
        self.assertEqual(reader.format_chunk(snapshot, 1), "第 1 页内容")
        self.assertEqual(reader.format_chunk(snapshot, 2), "第 2 页内容")
        # 边界容错
        self.assertEqual(reader.format_chunk(snapshot, 999), "第 2 页内容")
        self.assertEqual(reader.format_chunk(snapshot, 0), "第 1 页内容")

    def test_search_snapshot(self):
        reader = InlineMarkdownReader()
        snapshot = PageSnapshot(
            title="标题",
            url="https://example.com",
            raw_content=[
                "# 文档中心",
                "Playwright 工具套件说明",
                "- [Ref: 1] [链接: 下载客户端]",
            ],
            ref_map={1: {"ref": 1, "text": "下载客户端"}},
            total_pages=1,
            chunks=["快照全文"],
        )
        res_found = reader.search(snapshot, "下载客户端")
        self.assertIn("找到 1 处匹配", res_found)
        self.assertIn("[Ref: 1] [链接: 下载客户端]", res_found)

        res_not_found = reader.search(snapshot, "不存在的关键词")
        self.assertIn("未在页面正文中找到匹配", res_not_found)

        res_empty = reader.search(snapshot, "")
        self.assertIn("检索失败", res_empty)

    def test_tool_metadata(self):
        reader = InlineMarkdownReader()
        meta = reader.get_tool_metadata()
        self.assertEqual(meta["name"], "pw_read")
        self.assertIn("Markdown", meta["description"])
        self.assertIn("page", meta["parameters"]["properties"])
        self.assertIn("keyword", meta["parameters"]["properties"])
        self.assertIn("refresh", meta["parameters"]["properties"])


if __name__ == "__main__":
    unittest.main()
