import unittest
import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from astrbot_plugin_playwright_tools.core.page_extractor import PageExtractor

class TestPageExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = PageExtractor(max_page_char_length=200, multiline_separator=" | ")

    def test_markdown_and_multiline_element_extraction(self):
        extractor = PageExtractor(max_page_char_length=300, multiline_separator=" | ")
        raw_elements = [
            {"tag": "button", "type": "button", "text": "搜索GTNH中文维基\nCtrl K", "ref": 1},
            {"tag": "a", "type": "", "text": "发电线路\n教程指南", "ref": 2}
        ]
        markdown_text = "# GTNH 维基\n\n这是关于蒸汽时代的指南介绍。\n\n## 锅炉\n高压锅炉效率更高。"
        snapshot, ref_map = extractor.extract_snapshot("GTNH", "https://gtnh.com", raw_elements, markdown_text)

        self.assertIsInstance(snapshot, dict)
        self.assertIn("markdown_text", snapshot)
        self.assertIn("elements_text", snapshot)
        self.assertIn("full_text", snapshot)

        # 1. 验证元素换行被正确替换为 ' | '
        self.assertIn('[1] [按钮] "搜索GTNH中文维基 | Ctrl K"', snapshot["elements_text"])
        self.assertIn('[2] [链接] "发电线路 | 教程指南"', snapshot["elements_text"])

        # 2. 验证 target='text' 仅返回正文 Markdown，且页脚包含正确引导
        text_view = extractor.format_page_chunk(snapshot, target="text", page_index=1)
        self.assertIn("# GTNH 维基", text_view)
        self.assertNotIn("【可操作元素】", text_view)

        # 3. 验证 target='elements' 仅返回操作元素
        el_view = extractor.format_page_chunk(snapshot, target="elements", page_index=1)
        self.assertIn("【可操作元素】", el_view)
        self.assertNotIn("# GTNH 维基", el_view)

        # 4. 验证 target='all' 同时包含正文与操作元素
        all_view = extractor.format_page_chunk(snapshot, target="all", page_index=1)
        self.assertIn("# GTNH 维基", all_view)
        self.assertIn("【可操作元素】", all_view)

        # 5. 验证 target='text' 的目标域精准检索
        search_text = extractor.search_snapshot(snapshot, keyword="锅炉", target="text")
        self.assertIn("高压锅炉效率更高", search_text)
        self.assertNotIn("[按钮]", search_text)

    def test_pagination_independent_targets(self):
        extractor = PageExtractor(max_page_char_length=150, multiline_separator=" | ")
        long_md = "\n\n".join([f"第 {i} 段落: 这是详细的发电产线教程内容文本信息" for i in range(10)])
        raw_elements = [
            {"tag": "button", "type": "button", "text": f"按钮 {i}", "ref": i} for i in range(1, 15)
        ]
        snapshot, _ = extractor.extract_snapshot("测试大页面", "https://test.com", raw_elements, long_md)

        # 正文分页独立于元素
        text_p1 = extractor.format_page_chunk(snapshot, target="text", page_index=1)
        self.assertIn("target='text', page=2", text_p1)
        self.assertNotIn("按钮", text_p1)

        # 元素分页独立于正文
        el_p1 = extractor.format_page_chunk(snapshot, target="elements", page_index=1)
        self.assertIn("target='elements', page=2", el_p1)
        self.assertNotIn("第 1 段落", el_p1)

    def test_custom_multiline_separator_and_empty_separator(self):
        # 验证特殊分隔符与空串分隔符容错
        ext_slash = PageExtractor(multiline_separator=" // ")
        ext_empty = PageExtractor(multiline_separator="")

        raw_el = [{"tag": "button", "text": "第一行\n\n第二行\t\n第三行"}]
        snap_slash, _ = ext_slash.extract_snapshot("T1", "https://t.com", raw_el, "")
        snap_empty, _ = ext_empty.extract_snapshot("T2", "https://t.com", raw_el, "")

        self.assertIn("第一行 // 第二行 // 第三行", snap_slash["elements_text"])
        self.assertIn("第一行 第二行 第三行", snap_empty["elements_text"])  # 空串时安全折叠为单空格

    def test_get_js_extractor_script(self):
        script = self.extractor.get_js_extractor_script()
        self.assertIsInstance(script, str)
        self.assertIn("markdownText", script)
        self.assertIn("querySelectorAll", script)

if __name__ == "__main__":
    unittest.main()
