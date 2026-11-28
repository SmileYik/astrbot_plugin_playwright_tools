import json
import os
import subprocess
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
        self.assertIn(r"replace(/\s+/g, ' ')", script)

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

    def test_chunk_blocks_giant_block_fallback_splitting(self):
        reader = InlineMarkdownReader(chunk_char_limit=300)
        # 构造由 60 个列表项组成的巨型非表格 block
        items = [f"- [条目 {i}][{i}] 这是第 {i} 个长列表说明条目详细描述信息" for i in range(1, 61)]
        giant_block = "\n".join(items)

        chunks = reader._chunk_blocks([giant_block], url="https://example.com/wiki", title="巨型列表")
        self.assertGreater(len(chunks), 3)

        for idx, chunk in enumerate(chunks, 1):
            self.assertLessEqual(len(chunk), 300, f"分页 {idx} 字符数超出预算: {len(chunk)}")

        all_text = "".join(chunks)
        self.assertIn("[条目 1][1]", all_text)
        self.assertIn("[条目 60][60]", all_text)

    def test_gtnh_dense_navigation_table_snapshot_limit(self):
        reader = InlineMarkdownReader(chunk_char_limit=2000)
        # 模拟 50 行、5 列矩阵、250 个链接的复杂 GTNH Wiki 导航大表
        header = "| 模块导航 | 能源动力 | 自动化物流 | 矿业勘探 | 终极科技 |"
        separator = "| :--- | :--- | :--- | :--- | :--- |"
        rows = []
        ref_id = 1
        for r in range(1, 51):
            cells = []
            for col_name in ["导航", "能源", "物流", "矿业", "科技"]:
                cells.append(f"[{col_name}发展路线R{r}: 核心科技树与多方块机器自动化合成配方详细指南][{ref_id}]")
                ref_id += 1
            rows.append(f"| {' | '.join(cells)} |")
        table_block = "\n".join([header, separator] + rows)

        chunks = reader._chunk_blocks(
            [table_block],
            url="https://gtnh.miraheze.org/wiki/Main_Page",
            title="GT New Horizons Wiki",
        )
        self.assertGreater(len(chunks), 5)

        for idx, chunk in enumerate(chunks, 1):
            self.assertLessEqual(len(chunk), 2000, f"分页 {idx} 字符数超出预算: {len(chunk)}")
            self.assertIn(header, chunk, f"分页 {idx} 缺少表头")
            self.assertIn(separator, chunk, f"分页 {idx} 缺少分隔行")

        all_text = "".join(chunks)
        self.assertIn("[导航发展路线R1: 核心科技树与多方块机器自动化合成配方详细指南][1]", all_text)
        self.assertIn("[科技发展路线R50: 核心科技树与多方块机器自动化合成配方详细指南][250]", all_text)

    def test_single_unbroken_giant_line_safety(self):
        reader = InlineMarkdownReader(chunk_char_limit=1000)
        # 构造一个单行 4,000 字符的无换行极端文本
        giant_line = "".join([f"segment_{i:04d}_data_" for i in range(250)])[:4000]
        self.assertEqual(len(giant_line), 4000)
        self.assertNotIn("\n", giant_line)

        chunks = reader._chunk_blocks([giant_line], url="https://example.com/raw", title="长文本")
        self.assertGreater(len(chunks), 1)

        # 验证每个 chunk 严格受控在 1000 字符内
        for idx, chunk in enumerate(chunks, 1):
            self.assertLessEqual(len(chunk), 1000, f"分页 {idx} 字符数超出预算: {len(chunk)}")

        # 提取各个分页的正文内容并拼接，验证内容未丢失
        extracted_body_parts = []
        for chunk in chunks:
            # chunk 结构为: header \n\n body \n\n footer
            # 去除首尾的页眉与页脚
            parts = chunk.split("\n\n")
            body_parts = parts[1:-1]
            extracted_body_parts.append("\n\n".join(body_parts))

        reconstructed = "".join(extracted_body_parts)
        self.assertEqual(reconstructed, giant_line, "长文本分片重组后内容不一致，存在信息丢失")

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
                    "- [按钮: 退出登录][@r1]",
                ],
                "elements": [
                    {"ref": "@r1", "tag": "button", "text": "退出登录"},
                ],
            }

        mock_page.evaluate = fake_eval

        snapshot = await reader.extract_snapshot(mock_page, "https://example.com/dashboard")
        self.assertIsInstance(snapshot, PageSnapshot)
        self.assertEqual(snapshot.title, "测试控制台")
        self.assertEqual(snapshot.url, "https://example.com/dashboard")
        self.assertEqual(len(snapshot.chunks), 1)
        self.assertEqual(snapshot.total_pages, 1)
        self.assertIn("@r1", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["@r1"]["text"], "退出登录")
        self.assertIn("[按钮: 退出登录][@r1]", snapshot.chunks[0])
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
                    "![图片: 架构图][@r1]",
                    "- [官方文档][@r2]",
                    "- [链接 (含图): 查看原图][@r3]",
                ],
                "elements": [
                    {"ref": "@r1", "tag": "img", "text": "架构图", "alt": "架构图", "src": "https://example.com/arch.png", "href": ""},
                    {"ref": "@r2", "tag": "a", "text": "官方文档", "alt": "", "src": "", "href": "https://example.com/docs"},
                    {"ref": "@r3", "tag": "a", "text": "查看原图", "alt": "缩略图", "src": "https://example.com/thumb.png", "href": "https://example.com/view"},
                ],
                "allocated_count": 3,
            }

        mock_page.evaluate = fake_eval
        snapshot = await reader.extract_snapshot(mock_page, "https://example.com/article")
        self.assertIn("@r1", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["@r1"]["tag"], "img")
        self.assertEqual(snapshot.ref_map["@r1"]["src"], "https://example.com/arch.png")
        self.assertEqual(snapshot.ref_map["@r1"]["url"], "https://example.com/arch.png")
        self.assertIn("@r2", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["@r2"]["href"], "https://example.com/docs")
        self.assertEqual(snapshot.ref_map["@r2"]["url"], "https://example.com/docs")
        self.assertIn("@r3", snapshot.ref_map)
        self.assertEqual(snapshot.ref_map["@r3"]["href"], "https://example.com/view")
        self.assertEqual(snapshot.ref_map["@r3"]["src"], "https://example.com/thumb.png")
        self.assertIn("![图片: 架构图][@r1]", snapshot.raw_content)
        self.assertIn("[官方文档][@r2]", snapshot.raw_content[2])
        self.assertIn("[链接 (含图): 查看原图][@r3]", snapshot.raw_content[3])

    def test_js_extractor_ref_prefix_and_spacing(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script(start_ref=1)
        harness = """
const mkText = (val) => ({ nodeType: 3, nodeValue: val });
const mkEl = (tag, attrs = {}, children = []) => {
    const attrMap = { ...attrs };
    const el = {
        nodeType: 1,
        tagName: tag.toUpperCase(),
        children: [],
        childNodes: children,
        get innerText() {
            return this.childNodes.map(c => c.nodeType === 3 ? c.nodeValue : c.innerText).join('');
        },
        get textContent() { return this.innerText; },
        hasAttribute: (k) => Object.prototype.hasOwnProperty.call(attrMap, k),
        getAttribute: (k) => attrMap[k] ?? null,
        setAttribute: (k, v) => { attrMap[k] = String(v); },
        getBoundingClientRect: () => ({ width: 10, height: 10 }),
        querySelector: () => null,
        querySelectorAll: () => [],
    };
    el.children = children.filter(c => c.nodeType === 1);
    return el;
};

const a1 = mkEl('a', { href: 'https://a.test' }, [mkText('A')]);
const a2 = mkEl('a', { href: 'https://b.test' }, [mkText('B')]);
const p1 = mkEl('p', {}, [a1, a2]);

const a3 = mkEl('a', { href: 'https://c.test' }, [mkText('C')]);
const btn1 = mkEl('button', {}, [mkText('D')]);
const p2 = mkEl('p', {}, [mkEl('strong', {}, [a3]), btn1]);

const a4 = mkEl('a', { href: 'https://d.test' }, [mkText('这里')]);
const p3 = mkEl('p', {}, [mkText('  点击 \\n\\t  '), a4, mkText('  继续  ')]);

const p4 = mkEl('p', {}, [mkEl('strong', {}, [mkText('100')]), mkText('元')]);

const existingBtn = mkEl('button', { 'data-astr-ref': '@r9' }, [mkText('旧按钮')]);
const p5 = mkEl('p', {}, [existingBtn]);

const p6 = mkEl('p', {}, [mkText('第一行   文本'), mkEl('br'), mkText('第二行   文本')]);

const body = mkEl('body', {}, [p1, p2, p3, p4, p5, p6]);
global.window = { location: { href: 'https://example.com' }, getComputedStyle: () => ({ display: 'block', visibility: 'visible', opacity: '1' }) };
global.document = { title: 'Test', body };

const res = eval(process.env.EXTRACTOR_SCRIPT);
console.log(JSON.stringify({
    blocks: res.blocks,
    refs: res.elements.map(e => e.ref),
    a1Attr: a1.getAttribute('data-astr-ref'),
    existingAttr: existingBtn.getAttribute('data-astr-ref'),
    allocated_count: res.allocated_count,
}));
"""
        proc = subprocess.run(
            ["node", "-e", harness],
            env={**os.environ, "EXTRACTOR_SCRIPT": script},
            capture_output=True,
            text=True,
            check=True,
        )
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["blocks"][0], "[A][@r1] [B][@r2]")
        self.assertEqual(out["blocks"][1], "**[C][@r3]** [按钮: D][@r4]")
        self.assertEqual(out["blocks"][2], "点击 [这里][@r5] 继续")
        self.assertEqual(out["blocks"][3], "**100**元")
        self.assertEqual(out["blocks"][4], "[按钮: 旧按钮][@r9]")
        self.assertEqual(out["blocks"][5], "第一行 文本\n第二行 文本")
        self.assertEqual(out["refs"], ["@r1", "@r2", "@r3", "@r4", "@r5", "@r9"])
        self.assertEqual(out["a1Attr"], "@r1")
        self.assertEqual(out["existingAttr"], "@r9")
        self.assertEqual(out["allocated_count"], 5)

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

    def test_inline_markdown_reader_tool_metadata_ref_example(self):
        reader = InlineMarkdownReader()
        meta = reader.get_tool_metadata()
        ref_desc = meta["parameters"]["properties"]["ref"]["description"]
        self.assertIn("@r1", ref_desc)

    def test_js_extractor_div_inline_buffer_and_nested_wrappers(self):
        reader = InlineMarkdownReader()
        script = reader.get_js_extractor_script(start_ref=1)
        harness = """
const mkText = (val) => ({ nodeType: 3, nodeValue: val });
const mkEl = (tag, attrs = {}, children = []) => {
    const attrMap = { ...attrs };
    const el = {
        nodeType: 1,
        tagName: tag.toUpperCase(),
        children: [],
        childNodes: children,
        get innerText() {
            return this.childNodes.map(c => c.nodeType === 3 ? c.nodeValue : c.innerText).join('');
        },
        get textContent() { return this.innerText; },
        hasAttribute: (k) => Object.prototype.hasOwnProperty.call(attrMap, k),
        getAttribute: (k) => attrMap[k] ?? null,
        setAttribute: (k, v) => { attrMap[k] = String(v); },
        getBoundingClientRect: () => ({ width: 10, height: 10 }),
        querySelector: () => null,
        querySelectorAll: () => [],
    };
    el.children = children.filter(c => c.nodeType === 1);
    return el;
};

const div1 = mkEl('div', {}, [
    mkEl('span', {}, [mkText('Hello')]),
    mkText(' '),
    mkEl('span', {}, [mkText('World')]),
    mkEl('p', {}, [mkText('Next')]),
]);

const a1 = mkEl('a', { href: 'https://a.test' }, [mkText('A')]);
const a2 = mkEl('a', { href: 'https://b.test' }, [mkText('B')]);
const div2 = mkEl('div', {}, [
    mkEl('strong', {}, [mkEl('em', {}, [a1])]),
    mkEl('strong', {}, [mkEl('em', {}, [a2])]),
    mkEl('p', {}, [mkText('End')]),
]);

const pBracket = mkEl('p', {}, [
    mkEl('span', {}, [mkText('点击')]),
    mkEl('a', { href: 'https://c.test' }, [mkText('[1] 查看')]),
]);

const existingBtn = mkEl('button', { 'data-astr-ref': '@r9' }, [mkText('旧')]);
const newBtn = mkEl('button', {}, [mkText('新')]);
const pReuse = mkEl('p', {}, [existingBtn, newBtn]);

const body = mkEl('body', {}, [div1, div2, pBracket, pReuse]);
global.window = { location: { href: 'https://example.com' }, getComputedStyle: () => ({ display: 'block', visibility: 'visible', opacity: '1' }) };
global.document = { title: 'Test', body };

const res = eval(process.env.EXTRACTOR_SCRIPT);
console.log(JSON.stringify({ blocks: res.blocks, refs: res.elements.map(e => e.ref) }));
"""
        proc = subprocess.run(
            ["node", "-e", harness],
            env={**os.environ, "EXTRACTOR_SCRIPT": script},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["blocks"][0], "Hello World")
        self.assertEqual(out["blocks"][1], "Next")
        self.assertEqual(out["blocks"][2], "***[A][@r1]*** ***[B][@r2]***")
        self.assertEqual(out["blocks"][3], "End")
        self.assertEqual(out["blocks"][4], "点击 [[1] 查看][@r3]")
        self.assertEqual(out["blocks"][5], "[按钮: 旧][@r9] [按钮: 新][@r4]")
        self.assertEqual(out["refs"], ["@r1", "@r2", "@r3", "@r9", "@r4"])

    def test_tool_schemas_advertise_r_prefix(self):
        from astrbot_plugin_playwright_tools.tools.schemas import (
            PW_INTERACT_SCHEMA,
            PW_MEDIA_SCHEMA,
            PW_READ_SCHEMA,
        )

        self.assertIn("@r1", PW_READ_SCHEMA["properties"]["ref"]["description"])
        self.assertIn("@r1", PW_INTERACT_SCHEMA["properties"]["ref"]["description"])
        self.assertIn("@r1", PW_INTERACT_SCHEMA["properties"]["target_ref"]["description"])
        self.assertIn("@r1", PW_MEDIA_SCHEMA["properties"]["ref"]["description"])


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

