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
            "## 标题二\n- [按钮: 点击下载][1]\n- 状态说明: 推荐选项",
            "## 标题三\n- [历史版本目录][2]",
        ]
        chunks = reader._chunk_blocks(blocks, "https://example.com", "测试网页")
        self.assertGreaterEqual(len(chunks), 2)
        # 验证每个切片内 ref 完整，且切片首尾包含分页提示
        self.assertIn("[按钮: 点击下载][1]", "".join(chunks))
        self.assertIn("[历史版本目录][2]", "".join(chunks))
        self.assertIn("[分页:", chunks[0])

    def test_chunk_blocks_table_header_repetition(self):
        reader = InlineMarkdownReader(chunk_char_limit=450)
        # 构造一个 20 行的表格
        header = "| 序号 | 名称 | 描述 |"
        separator = "| --- | --- | --- |"
        rows = [f"| {i} | [条目{i}][{i}] | 这是关于第{i}项的长文本详细说明信息 |" for i in range(1, 21)]
        table_block = "\n".join([header, separator] + rows)

        chunks = reader._chunk_blocks([table_block], url="https://example.com", title="表格测试")
        self.assertGreater(len(chunks), 1)

        # 验证每一个切片分页都包含完整的表头与分隔行
        for idx, chunk in enumerate(chunks, 1):
            self.assertIn(header, chunk, f"分页 {idx} 缺少表头行")
            self.assertIn(separator, chunk, f"分页 {idx} 缺少分隔行")
            self.assertLessEqual(len(chunk), 450, f"分页 {idx} 字符数超出预算: {len(chunk)}")

    def test_parse_markdown_table_helper(self):
        # 1. 合法表格（含对齐冒号）
        table = "| 列A | 列B | 列C |\n|:---|:---:|---:|\n| 1 | 2 | 3 |"
        is_t, headers, rows = InlineMarkdownReader._parse_markdown_table(table)
        self.assertTrue(is_t)
        self.assertEqual(headers, ["| 列A | 列B | 列C |", "|:---|:---:|---:|"])
        self.assertEqual(rows, ["| 1 | 2 | 3 |"])

        # 2. 单行不是表格
        is_t, _, _ = InlineMarkdownReader._parse_markdown_table("| 仅有一行 |")
        self.assertFalse(is_t)

        # 3. 分隔行不匹配
        not_table = "| 列A | 列B |\n| 普通文本 | 也是文本 |"
        is_t, _, _ = InlineMarkdownReader._parse_markdown_table(not_table)
        self.assertFalse(is_t)

    def test_chunk_blocks_table_with_preamble_and_trailer(self):
        reader = InlineMarkdownReader(chunk_char_limit=450)
        preamble = "# 项目表格概览\n请查阅下方数据列表。"
        header = "| 序号 | 名称 | 描述 |"
        separator = "| --- | --- | --- |"
        rows = [f"| {i} | [条目{i}][{i}] | 这是关于第{i}项的长文本详细说明信息 |" for i in range(1, 15)]
        table_block = "\n".join([header, separator] + rows)
        trailer = "## 尾注说明\n以上数据按时间排序完成。"

        chunks = reader._chunk_blocks(
            [preamble, table_block, trailer],
            url="https://example.com/overview",
            title="数据总览",
        )
        self.assertGreater(len(chunks), 1)
        self.assertIn("# 项目表格概览", chunks[0])
        self.assertIn("## 尾注说明", chunks[-1])

        # 包含表格部分的每个切片都包含完整的表头与分隔行
        for idx, chunk in enumerate(chunks, 1):
            self.assertLessEqual(len(chunk), 450, f"分页 {idx} 字符数超出预算: {len(chunk)}")
            if any(f"| {i} |" in chunk for i in range(1, 15)):
                self.assertIn(header, chunk, f"分页 {idx} 包含表格数据但缺少表头行")
                self.assertIn(separator, chunk, f"分页 {idx} 包含表格数据但缺少分隔行")

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
                    "- [按钮: 退出登录][1]",
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
        self.assertIn("[按钮: 退出登录][1]", snapshot.chunks[0])
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
                    "![图片: 架构图][1]",
                    "- [官方文档][2]",
                    "- [链接 (含图): 查看原图][3]",
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
        self.assertIn("![图片: 架构图][1]", snapshot.raw_content)
        self.assertIn("[官方文档][2]", snapshot.raw_content[2])
        self.assertIn("[链接 (含图): 查看原图][3]", snapshot.raw_content[3])

    def test_inline_markdown_reader_script_contains_img_ref(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script()
        self.assertIn("img", script)
        self.assertIn("![图片: ${desc}][${ref}]", script)
        self.assertIn("![图片][${ref}]", script)
        self.assertIn("[链接 (含图): ${desc}][${ref}]", script)
        self.assertIn("[${text}][${ref}]", script)
        self.assertIn("[按钮: ${btnText}][${ref}]", script)
        self.assertIn("[复选框:", script)
        self.assertIn("[单选框:", script)
        self.assertIn("[输入框", script)
        self.assertIn("[选择框", script)
        self.assertIn("[文本域", script)
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
                "- [下载客户端][1]",
            ],
            ref_map={"1": {"ref": "1", "text": "下载客户端"}},
            total_pages=1,
            chunks=["快照全文"],
        )
        res_found = reader.search(snapshot, "下载客户端")
        self.assertIn("找到 1 处匹配", res_found)
        self.assertIn("[下载客户端][1]", res_found)

        res_not_found = reader.search(snapshot, "不存在的关键词")
        self.assertIn("未在页面正文中找到匹配", res_not_found)

        res_empty = reader.search(snapshot, "")
        self.assertIn("检索失败", res_empty)

    def test_markdown_extractor_element_formatting_templates(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script()
        # 验证各控件引用的模板语法
        self.assertIn("![图片: ${desc}][${ref}]", script)
        self.assertIn("![图片][${ref}]", script)
        self.assertIn("[链接 (含图): ${desc}][${ref}]", script)
        self.assertIn("[链接 (含图)][${ref}]", script)
        self.assertIn("[${text}][${ref}]", script)
        self.assertIn("[链接][${ref}]", script)
        self.assertIn("[按钮: ${btnText}][${ref}]", script)
        self.assertIn("[按钮][${ref}]", script)
        self.assertIn("[复选框: ${label} (${checked})][${ref}]", script)
        self.assertIn("[单选框: ${label} (${checked})][${ref}]", script)
        self.assertIn("[输入框${detailStr}][${ref}]", script)
        self.assertIn("[选择框${detailStr}][${ref}]", script)
        self.assertIn("[文本域${detailStr}][${ref}]", script)
        self.assertIn("[控件: ${text || tag}][${ref}]", script)

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

    async def test_aria_reader_url_filtering_and_href_extraction(self):
        mock_page = MagicMock()
        mock_root = AsyncMock()
        raw_yaml = (
            '- document [ref=e1]:\n'
            '  - heading "Header" [level=1] [ref=e2]\n'
            '  - link "官方文档" [ref=e3] [cursor=pointer]:\n'
            '    - /url: https://example.com/docs\n'
            '  - link "https://example.com/page2" [ref=e4] [cursor=pointer]:\n'
            '    - /url: https://example.com/page2\n'
        )
        mock_root.aria_snapshot = AsyncMock(return_value=raw_yaml)
        mock_page.locator.return_value = mock_root
        mock_page.url = "https://example.com"
        mock_page.title = "测试页面"

        reader = AriaSnapshotReader()
        snapshot = await reader.extract_snapshot(mock_page)

        # 1. 验证正文中彻底剥离了 - /url:
        self.assertNotIn("/url:", snapshot.raw_content)
        # 2. 验证父行末尾冒号被剥离
        self.assertIn('link "官方文档" [ref=e3] [cursor=pointer]\n', snapshot.raw_content + '\n')
        self.assertNotIn('link "官方文档" [ref=e3] [cursor=pointer]:', snapshot.raw_content)
        # 3. 验证 URL 作为文本的链接被精简为不带引号的 link [ref=...]
        self.assertIn('link [ref=e4] [cursor=pointer]', snapshot.raw_content)
        self.assertNotIn('link "https://example.com/page2"', snapshot.raw_content)
        # 4. 验证 ref_map 中正确记录 href 与 url
        self.assertIn("e3", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["e3"]["href"], "https://example.com/docs")
        self.assertEqual(snapshot.ref_map["e3"]["url"], "https://example.com/docs")
        self.assertEqual(snapshot.ref_map["e3"]["tag"], "a")
        self.assertIn("e4", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["e4"]["href"], "https://example.com/page2")

    async def test_aria_reader_image_src_and_nested_link_extraction(self):
        mock_page = MagicMock()
        mock_root = AsyncMock()
        raw_yaml = (
            '- document [ref=e1]:\n'
            '  - link [ref=e2]:\n'
            '    - /url: https://example.com/item\n'
            '    - img "商品缩略图" [ref=e3]\n'
            '  - img "独立照片" [ref=e4]\n'
        )
        mock_root.aria_snapshot = AsyncMock(return_value=raw_yaml)
        mock_page.locator.return_value = mock_root
        mock_page.url = "https://example.com"
        mock_page.title = "测试页面"

        mock_loc_e3 = AsyncMock()
        mock_loc_e3.count = AsyncMock(return_value=1)
        mock_loc_e3.evaluate = AsyncMock(return_value="https://example.com/thumb.jpg")

        mock_loc_e4 = AsyncMock()
        mock_loc_e4.count = AsyncMock(return_value=1)
        mock_loc_e4.evaluate = AsyncMock(return_value="https://example.com/photo.jpg")

        def mock_locator_router(sel):
            if sel == "aria-ref=e3":
                return mock_loc_e3
            elif sel == "aria-ref=e4":
                return mock_loc_e4
            return mock_root
        mock_page.locator.side_effect = mock_locator_router

        reader = AriaSnapshotReader()
        snapshot = await reader.extract_snapshot(mock_page)

        # 1. 验证 e3 (图片) 的 src 与 alt 提取
        self.assertIn("e3", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["e3"]["src"], "https://example.com/thumb.jpg")
        self.assertEqual(snapshot.ref_map["e3"]["alt"], "商品缩略图")
        self.assertEqual(snapshot.ref_map["e3"]["tag"], "img")

        # 2. 验证 e4 (独立图片) 的 src
        self.assertIn("e4", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["e4"]["src"], "https://example.com/photo.jpg")

        # 3. 验证 e2 (父级 link) 自动关联嵌套图片的 src
        self.assertIn("e2", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["e2"]["href"], "https://example.com/item")
        self.assertEqual(snapshot.ref_map["e2"]["src"], "https://example.com/thumb.jpg")
        self.assertEqual(snapshot.ref_map["e2"]["alt"], "商品缩略图")

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

