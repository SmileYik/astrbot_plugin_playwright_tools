import unittest
import os
import sys
import subprocess
import json

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

    def test_page_extractor_normalizes_excessive_newlines(self):
        raw_md = "# 标题\n\n\n\n\n段落一\n\n\n段落二\n\n- 列表项 1\n\n- 列表项 2\n\n\n- 列表项 3\n\n\n\n段落三"
        snapshot, _ = self.extractor.extract_snapshot("测试标题", "https://example.com", [], raw_md)
        md = snapshot["markdown_text"]

        # 验证 3 个或更多连续换行被折叠为标准双换行 \n\n
        self.assertNotIn("\n\n\n", md)
        self.assertIn("# 标题\n\n段落一\n\n段落二", md)

        # 验证列表项之间紧凑排布，没有空行
        self.assertIn("- 列表项 1\n- 列表项 2\n- 列表项 3", md)
        self.assertIn("- 列表项 3\n\n段落三", md)

    def test_page_extractor_forum_div_content_extraction(self):
        script = self.extractor.get_js_extractor_script().strip()
        if script.endswith(";"):
            script = script[:-1]

        dom_mock = '''
class Node {
  constructor(tag, attrs = {}, text = '', children = []) {
    this.tagName = tag.toUpperCase();
    this.attrs = attrs;
    this.className = attrs.class || '';
    this.id = attrs.id || '';
    this.innerText = text;
    this.textContent = text;
    this.children = children;
    this.parentNode = null;
    for (const c of children) c.parentNode = this;
  }
  getAttribute(k) { return this.attrs[k] || ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getBoundingClientRect() { return { width: 100, height: 100 }; }
  closest(sel) {
    let curr = this;
    while (curr) {
      if (curr.matches(sel)) return curr;
      curr = curr.parentNode;
    }
    return null;
  }
  matches(sel) {
    const parts = sel.split(',').map(s => s.trim());
    for (const p of parts) {
      if (p.startsWith('.')) {
        const cls = p.slice(1);
        if (this.className.split(/\\s+/).includes(cls)) return true;
      } else if (p.startsWith('#')) {
        if (this.id === p.slice(1)) return true;
      } else if (p.toLowerCase() === this.tagName.toLowerCase()) {
        return true;
      }
    }
    return false;
  }
  querySelectorAll(sel) {
    let res = [];
    for (const c of this.children) {
      if (c.matches(sel)) res.push(c);
      res = res.concat(c.querySelectorAll(sel));
    }
    return res;
  }
  querySelector(sel) {
    const list = this.querySelectorAll(sel);
    return list.length > 0 ? list[0] : null;
  }
}
const sidebarH3 = new Node('h3', {}, '登录百度账号');
const sidebarLi = new Node('li', {}, '登录提示');
const sidebarUl = new Node('ul', {}, '', [sidebarLi]);
const sidebar = new Node('aside', { class: 'sidebar login-box' }, '', [sidebarH3, sidebarUl]);

const postBr = new Node('br', {}, '');
const postDiv = new Node('div', { class: 'd_post_content' }, '第一楼：楼主发表的关于GTNH的深度讨论\\n第二行内容通过换行', [postBr]);

const root = new Node('body', {}, '', [sidebar, postDiv]);
global.window = { getComputedStyle: () => ({ display: 'block', visibility: 'visible', opacity: '1' }), location: { href: 'https://tieba.baidu.com/p/123' } };
global.document = {
  title: '贴吧测试',
  body: root,
  querySelectorAll: (sel) => root.querySelectorAll(sel),
  querySelector: (sel) => root.querySelector(sel)
};
'''
        full_code = dom_mock + '\nconst extractorResult = ' + script + ';\nconsole.log(JSON.stringify(extractorResult));'
        res = subprocess.run(['node', '-e', full_code], capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)

        md_text = data.get("markdownText", "")
        # 1. 验证正文提取出贴吧楼层内容（div + br）
        self.assertIn("第一楼：楼主发表的关于GTNH的深度讨论", md_text)
        # 2. 验证侧边栏登录盒子等噪音被排除，而不是作为正文提取
        self.assertNotIn("登录百度账号", md_text)
        self.assertNotIn("登录提示", md_text)

    def test_page_extractor_deduplicates_and_cleans_elements(self):
        raw_elements = [
            {"tag": "a", "type": "", "text": "", "ref": 1},  # 空链接，应被过滤
            {"tag": "button", "type": "button", "text": "   ", "ref": 2},  # 空按钮，应被过滤
            {"tag": "button", "type": "button", "text": "", "aria-label": "提交表单", "ref": 3},  # 有 aria-label 的按钮，保留并使用 label
            {"tag": "a", "type": "", "text": "贴吧首页", "ref": 4},
            {"tag": "a", "type": "", "text": "贴吧首页", "ref": 5},  # 连续相同链接，应被去重
            {"tag": "a", "type": "", "text": "精品贴", "ref": 6},
            {"tag": "input", "type": "text", "name": "kw", "text": "", "placeholder": "搜索贴子", "ref": 7},  # 输入框虽无 text 但保留
        ]
        snapshot, ref_map = self.extractor.extract_snapshot("测试", "https://tieba.com", raw_elements, "贴子正文")

        # 验证空链接和空按钮被过滤
        self.assertNotIn('[按钮] ""', snapshot["elements_text"])
        self.assertNotIn('[链接] ""', snapshot["elements_text"])

        # 验证有 aria-label 的按钮被正常提取
        self.assertIn('[按钮] "提交表单"', snapshot["elements_text"])

        # 验证连续重复链接仅保留一项
        self.assertEqual(snapshot["elements_text"].count("贴吧首页"), 1)
        self.assertIn('[链接] "精品贴"', snapshot["elements_text"])

        # 验证输入框被保留
        self.assertIn('[输入框] (name="kw", placeholder="搜索贴子")', snapshot["elements_text"])

        # 验证 ref_id 连续无空隙
        expected_refs = list(range(1, len(ref_map) + 1))
        self.assertEqual(list(ref_map.keys()), expected_refs)

if __name__ == "__main__":
    unittest.main()
