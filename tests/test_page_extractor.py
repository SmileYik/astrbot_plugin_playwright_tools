import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.page_extractor import PageExtractor

class TestPageExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = PageExtractor(max_page_char_length=200)

    def test_extract_and_format_elements(self):
        elements = [
            {"tag": "input", "type": "text", "name": "kw", "placeholder": "search", "text": "", "value": ""},
            {"tag": "button", "type": "submit", "name": "", "placeholder": "", "text": "Search Now", "value": ""},
            {"tag": "a", "type": "", "name": "", "placeholder": "", "text": "Help Docs", "href": "https://s.com/help", "value": ""}
        ]
        text_blocks = ["Welcome to Search Engine"]
        text, ref_map = self.extractor.extract_snapshot("Search Home", "https://s.com", elements, text_blocks)
        
        self.assertIn("[1] [输入框]", text)
        self.assertIn("[2] [按钮] \"Search Now\"", text)
        self.assertIn("[3] [链接] \"Help Docs\"", text)
        self.assertEqual(len(ref_map), 3)
        self.assertEqual(ref_map[1]["tag"], "input")

    def test_pagination_when_length_exceeded(self):
        long_blocks = [f"Paragraph {i}: " + ("x" * 60) for i in range(10)]
        text, _ = self.extractor.extract_snapshot("Big Page", "https://big.com", [], long_blocks)
        formatted = self.extractor.format_page_chunk(text, page_index=1)
        self.assertIn("[分页: 1/", formatted)
        self.assertIn("read_page(page=2)", formatted)

        # Page 2 should not show read_page(page=2), but if more pages exist show read_page(page=3)
        formatted_p2 = self.extractor.format_page_chunk(text, page_index=2)
        self.assertIn("[分页: 2/", formatted_p2)

    def test_get_js_extractor_script(self):
        script = self.extractor.get_js_extractor_script()
        self.assertIsInstance(script, str)
        self.assertIn("querySelectorAll", script)

if __name__ == "__main__":
    unittest.main()
