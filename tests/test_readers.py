import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

if "astrbot" not in sys.modules:
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.readers.markdown_reader import InlineMarkdownReader
from core.readers.aria_reader import AriaSnapshotReader
from core.readers.base import BasePageReader, PageSnapshot


class TestPageSnapshot(unittest.TestCase):
    def test_page_snapshot_timestamp_and_string_ref_map(self):
        snapshot = PageSnapshot(
            title="Title",
            url="https://example.com",
            raw_content="content",
            ref_map={"e1": {"ref": "e1"}},
            total_pages=1,
            chunks=["chunk"],
        )
        self.assertIsInstance(snapshot.timestamp, float)
        self.assertGreater(snapshot.timestamp, 0)
        self.assertIn("e1", snapshot.ref_map)


class TestInlineMarkdownReader(unittest.IsolatedAsyncioTestCase):
    def test_inline_markdown_reader_script_syntax_and_escapes(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script()
        self.assertNotIn("replace(/[\r", script)
        self.assertNotIn("replace(/[\n", script)
        self.assertIn(r"replace(/[\r\n\t]+/g, ' ')", script)

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

    def test_inline_markdown_reader_start_ref_parameter(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script(start_ref=42)
        self.assertIn("let nextRef = 42;", script)
        self.assertIn("allocated_count", script)

    async def test_extract_snapshot_with_mock_page(self):
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

        snapshot = await reader.extract_snapshot(mock_page, "https://example.com/dashboard")
        self.assertIsInstance(snapshot, PageSnapshot)
        self.assertEqual(snapshot.title, "测试控制台")
        self.assertEqual(snapshot.url, "https://example.com/dashboard")
        self.assertEqual(len(snapshot.chunks), 1)
        self.assertEqual(snapshot.total_pages, 1)
        self.assertIn("1", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["1"]["text"], "退出登录")
        self.assertIn("[Ref: 1] [按钮: 退出登录]", snapshot.chunks[0])
        self.assertIsInstance(snapshot.timestamp, float)
        self.assertGreater(snapshot.timestamp, 0)

    async def test_inline_markdown_reader_extracts_img_ref_and_urls(self):
        reader = InlineMarkdownReader(chunk_char_limit=2000, mask_passwords=True)
        mock_page = AsyncMock()

        async def fake_eval(script):
            return {
                "title": "测试图文页",
                "url": "https://example.com/article",
                "blocks": [
                    "# 文章标题",
                    "[Ref: 1] [图片: 架构图]",
                    "- [Ref: 2] [链接: 官方文档]",
                    "- [Ref: 3] [链接 (含图片): 查看原图]",
                ],
                "elements": [
                    {"ref": 1, "tag": "img", "text": "架构图", "alt": "架构图", "src": "https://example.com/arch.png", "href": ""},
                    {"ref": 2, "tag": "a", "text": "官方文档", "alt": "", "src": "", "href": "https://example.com/docs"},
                    {"ref": 3, "tag": "a", "text": "查看原图", "alt": "缩略图", "src": "https://example.com/thumb.png", "href": "https://example.com/view"},
                ],
                "allocated_count": 3,
            }

        mock_page.evaluate = fake_eval
        snapshot = await reader.extract_snapshot(mock_page, "https://example.com/article")
        self.assertIn("1", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["1"]["tag"], "img")
        self.assertEqual(snapshot.ref_map["1"]["src"], "https://example.com/arch.png")
        self.assertEqual(snapshot.ref_map["1"]["url"], "https://example.com/arch.png")
        self.assertIn("2", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["2"]["href"], "https://example.com/docs")
        self.assertEqual(snapshot.ref_map["2"]["url"], "https://example.com/docs")
        self.assertIn("3", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["3"]["href"], "https://example.com/view")
        self.assertEqual(snapshot.ref_map["3"]["src"], "https://example.com/thumb.png")

    def test_inline_markdown_reader_script_contains_img_ref(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script()
        self.assertIn("img", script)
        self.assertIn("[Ref: ${ref}] [图片", script)
        self.assertIn("href", script)
        self.assertIn("src", script)

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
            ref_map={"1": {"ref": "1", "text": "下载客户端"}},
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


class TestAriaSnapshotReader(unittest.IsolatedAsyncioTestCase):
    def test_aria_reader_tool_metadata(self):
        reader = AriaSnapshotReader(chunk_char_limit=1500)
        meta = reader.get_tool_metadata()
        self.assertIn("ARIA", meta["description"])
        self.assertIn("page", meta["parameters"]["properties"])

    def test_aria_chunking(self):
        reader = AriaSnapshotReader(chunk_char_limit=120)
        tree_text = (
            "- main:\n"
            "  - region \"客户端\":\n"
            "    - button \"下载\" [ref=1]\n"
            "  - region \"服务端\":\n"
            "    - button \"下载\" [ref=2]\n"
        )
        chunks = reader._chunk_aria_tree(tree_text, "https://example.com", "测试网页")
        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("[ref=1]", "".join(chunks))
        self.assertIn("[ref=2]", "".join(chunks))
        self.assertIn("分页: 1/", chunks[0])

    async def test_aria_snapshot_reader_official_mode(self):
        mock_page = MagicMock()
        mock_root = AsyncMock()
        mock_root.aria_snapshot = AsyncMock(return_value='- heading "Title" [level=1]\n- button "Submit" [ref=e1]')
        mock_page.locator.return_value = mock_root
        mock_page.url = "https://example.com"
        mock_page.title = AsyncMock(return_value="示例页面")
        reader = AriaSnapshotReader()
        snapshot = await reader.extract_snapshot(mock_page, "https://example.com")
        self.assertIn("e1", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["e1"]["ref"], "e1")
        self.assertIn('button "Submit" [ref=e1]', snapshot.raw_content)
        self.assertEqual(snapshot.title, "示例页面")
        self.assertEqual(snapshot.url, "https://example.com")
        self.assertIsInstance(snapshot.timestamp, float)
        mock_root.aria_snapshot.assert_awaited_once_with(mode="ai")

    async def test_aria_snapshot_reader_fallback_page_aria_snapshot(self):
        mock_page = MagicMock()
        mock_page.locator.side_effect = Exception("Locator failed")
        mock_page.aria_snapshot = AsyncMock(return_value='- link "Home" [ref=e2]\n- button "OK" [ref=e3]')
        mock_page.url = "https://example.com/fallback"
        mock_page.title = "Fallback Title"
        reader = AriaSnapshotReader()
        snapshot = await reader.extract_snapshot(mock_page)
        self.assertIn("e2", snapshot.ref_map)
        self.assertIn("e3", snapshot.ref_map)
        self.assertEqual(snapshot.title, "Fallback Title")
        self.assertEqual(snapshot.url, "https://example.com/fallback")

    def test_aria_format_chunk(self):
        reader = AriaSnapshotReader(chunk_char_limit=150)
        snapshot = PageSnapshot(
            title="标题",
            url="https://example.com",
            raw_content="- main:\n  - text: 内容",
            ref_map={},
            total_pages=2,
            chunks=["第 1 页内容", "第 2 页内容"],
        )
        self.assertEqual(reader.format_chunk(snapshot, 1), "第 1 页内容")
        self.assertEqual(reader.format_chunk(snapshot, 2), "第 2 页内容")
        self.assertEqual(reader.format_chunk(snapshot, 999), "第 2 页内容")
        self.assertEqual(reader.format_chunk(snapshot, 0), "第 1 页内容")

    def test_aria_search_snapshot(self):
        reader = AriaSnapshotReader()
        snapshot = PageSnapshot(
            title="标题",
            url="https://example.com",
            raw_content="- main:\n  - region \"设置\":\n    - button \"重置密码\" [ref=1]",
            ref_map={"1": {"ref": "1", "name": "重置密码"}},
            total_pages=1,
            chunks=["快照全文"],
        )
        res_found = reader.search(snapshot, "重置密码")
        self.assertIn("找到 1 处匹配", res_found)
        self.assertIn("button \"重置密码\" [ref=1]", res_found)

        res_not_found = reader.search(snapshot, "无此内容")
        self.assertIn("未在页面 ARIA 语义树中找到匹配", res_not_found)

        res_empty = reader.search(snapshot, "")
        self.assertIn("检索失败", res_empty)


if __name__ == "__main__":
    unittest.main()

