import asyncio
import os
import re
import sys
import unittest
import tempfile
from pathlib import Path

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
parent_dir = os.path.dirname(repo_root)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from tests.e2e.server import LocalTestServer
from astrbot_plugin_playwright_tools.adapts.camoufox_adapter import CamoufoxAdapter
from astrbot_plugin_playwright_tools.core.context_manager import ContextManager
from astrbot_plugin_playwright_tools.core.security_manager import SecurityManager
from astrbot_plugin_playwright_tools.core.audit_logger import AuditLogger
from astrbot_plugin_playwright_tools.core.page_extractor import PageExtractor
from astrbot_plugin_playwright_tools.tools.handlers.page_handler import PageHandler
from astrbot_plugin_playwright_tools.tools.handlers.interact_handler import InteractHandler
from astrbot_plugin_playwright_tools.tools.handlers.media_handler import MediaHandler
from astrbot_plugin_playwright_tools.tools.tools import PwPageTool, PwInteractTool, PwMediaTool


class MockEvent:
    def __init__(self, session_id="e2e_session", sender_id="admin_1", sender_name="Admin"):
        self.session_id = session_id
        self.sender_id = sender_id
        self._sender_name = sender_name

    def get_sender_id(self):
        return self.sender_id

    def get_sender_name(self):
        return self._sender_name


class MockContextWrapper:
    def __init__(self, event):
        self.event = event


class TestRealBrowserE2E(unittest.IsolatedAsyncioTestCase):
    server: LocalTestServer
    adapter: CamoufoxAdapter
    context_mgr: ContextManager
    pw_page: PwPageTool
    pw_interact: PwInteractTool
    pw_media: PwMediaTool
    mock_ctx: MockContextWrapper
    temp_dir: Path

    @classmethod
    def setUpClass(cls):
        cls.server = LocalTestServer()
        cls.server.start()

        cls.temp_dir = Path(tempfile.mkdtemp(prefix="astrbot_e2e_"))
        db_path = str(cls.temp_dir / "audit.db")
        downloads_path = str(cls.temp_dir / "downloads")

        cls.adapter = CamoufoxAdapter(headless=True)
        cls.security = SecurityManager(admin_only=False, admin_uids=["admin_1"])
        cls.audit = AuditLogger(db_path)
        cls.extractor = PageExtractor(max_page_char_length=2500)
        cls.context_mgr = ContextManager(adapter=cls.adapter, security=cls.security)

        cls.page_handler = PageHandler(cls.context_mgr, cls.security, cls.audit, cls.extractor)
        cls.interact_handler = InteractHandler(cls.context_mgr, cls.security, cls.audit)
        cls.media_handler = MediaHandler(
            cls.context_mgr,
            cls.security,
            cls.audit,
            allow_screenshot_to_ai=True,
            download_dir=downloads_path,
        )

        cls.pw_page = PwPageTool(page_handler=cls.page_handler, timeout_seconds=30)
        cls.pw_interact = PwInteractTool(interact_handler=cls.interact_handler, timeout_seconds=30)
        cls.pw_media = PwMediaTool(media_handler=cls.media_handler, timeout_seconds=30)

        cls.mock_ctx = MockContextWrapper(MockEvent())

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.stop()
        except Exception:
            pass

    async def asyncTearDown(self):
        # 保证在全部测试用例结束或者清理时关闭适配器
        pass

    async def test_01_full_e2e_lifecycle(self):
        """测试从浏览器打开页面、阅读、检索、各种表单与元素交互、弹窗、多标签页、截图到关闭的完整生命周期。"""
        target_url = self.server.get_url("/test_page.html")

        # 1. 打开页面 (open)
        open_res = await self.pw_page.call(self.mock_ctx, action="open", url=target_url)
        self.assertIn("Playwright Tools E2E Test Page", open_res)
        self.assertIn("【可操作元素】", open_res)

        # 2. 读取页面分页快照 (read)
        read_res = await self.pw_page.call(self.mock_ctx, action="read", page=1)
        self.assertIn("=== 页面视图 [分页: 1/", read_res)
        self.assertIn("欢迎来到 Playwright Tools 端到端集成测试页面", read_res)

        # 3. 页面检索 (search)
        search_res = await self.pw_page.call(self.mock_ctx, action="search", keyword="点击测试")
        self.assertIn("点击测试", search_res)

        # 获取上下文并解析当前元素 Ref ID
        ctx, _ = await self.context_mgr.resolve_context("e2e_session", "admin_1")
        self.assertIsNotNone(ctx)
        ref_map = ctx.ref_map
        self.assertTrue(len(ref_map) > 0)

        # 找到各个目标元素 Ref
        input_ref = None
        btn_ref = None
        select_ref = None
        alert_btn_ref = None
        newtab_link_ref = None

        for r_id, el in ref_map.items():
            tag = el.get("tag", "").lower()
            name = el.get("name", "")
            text = el.get("text", "")
            if tag == "input" and name == "username":
                input_ref = r_id
            elif tag == "button" and "点击测试" in text:
                btn_ref = r_id
            elif tag == "select":
                select_ref = r_id
            elif tag == "button" and "触发Alert" in text:
                alert_btn_ref = r_id
            elif tag == "a" and "打开新标签页" in text:
                newtab_link_ref = r_id

        self.assertIsNotNone(input_ref, "未能找到输入框元素")
        self.assertIsNotNone(btn_ref, "未能找到测试按钮元素")
        self.assertIsNotNone(select_ref, "未能找到下拉选择框元素")
        self.assertIsNotNone(alert_btn_ref, "未能找到弹窗按钮元素")
        self.assertIsNotNone(newtab_link_ref, "未能找到新标签页链接元素")

        # 4. 表单输入交互 (fill)
        fill_res = await self.pw_interact.call(self.mock_ctx, action="fill", ref=input_ref, text="Camoufox Real Test")
        self.assertIn("已成功在输入框", fill_res)
        val_in_page = await ctx.current_page.evaluate("() => document.getElementById('test-input').value")
        self.assertEqual(val_in_page, "Camoufox Real Test")

        # 5. 按钮点击交互 (click)
        click_res = await self.pw_interact.call(self.mock_ctx, action="click", ref=btn_ref)
        self.assertIn("已成功点击", click_res)
        result_text = await ctx.current_page.evaluate("() => document.getElementById('result').innerText")
        self.assertEqual(result_text, "clicked")

        # 6. 下拉框选择 (select)
        select_res = await self.pw_interact.call(self.mock_ctx, action="select", ref=select_ref, value="opt2")
        self.assertIn("成功选取", select_res)
        select_val = await ctx.current_page.evaluate("() => document.getElementById('test-select').value")
        self.assertEqual(select_val, "opt2")

        # 7. 页面滚动 (scroll)
        scroll_res = await self.pw_interact.call(self.mock_ctx, action="scroll", direction="down", amount=500)
        self.assertIn("页面已向down滚动 500 像素", scroll_res)
        scroll_y = await ctx.current_page.evaluate("() => window.scrollY")
        self.assertGreaterEqual(scroll_y, 400)

        # 8. 原生 Alert 弹窗应答 (dialog + click)
        dialog_res = await self.pw_page.call(self.mock_ctx, action="dialog", dialog_action="accept")
        self.assertIn("已预设下一次弹窗处理策略", dialog_res)
        alert_click_res = await self.pw_interact.call(self.mock_ctx, action="click", ref=alert_btn_ref)
        self.assertIn("触发浏览器弹窗: '测试弹窗内容'，已自动处理", alert_click_res)

        # 9. 多标签页打开与切换 (target="_blank" + switch_tab)
        # 点击 target="_blank"
        newtab_click_res = await self.pw_interact.call(self.mock_ctx, action="click", ref=newtab_link_ref)
        self.assertIn("已成功点击", newtab_click_res)

        # 等待新标签页在 context 中就绪
        await asyncio.sleep(1)
        self.assertEqual(len(ctx.browser_context.pages), 2)

        # 切换到标签页 2
        switch2_res = await self.pw_page.call(self.mock_ctx, action="switch_tab", tab_index=2)
        self.assertIn("已成功切换至标签页 2", switch2_res)
        self.assertIn("newtab.html", ctx.current_page.url)

        # 切回标签页 1
        switch1_res = await self.pw_page.call(self.mock_ctx, action="switch_tab", tab_index=1)
        self.assertIn("已成功切换至标签页 1", switch1_res)
        self.assertIn("test_page.html", ctx.current_page.url)

        # 10. 视口截图与整页长截图 (screenshot_viewport & screenshot_full)
        vp_res = await self.pw_media.call(self.mock_ctx, action="screenshot_viewport", target="chat")
        self.assertIn("[IMAGE_PATH:", vp_res)
        vp_path_match = re.search(r"\[IMAGE_PATH:(.*?)\]", vp_res)
        self.assertIsNotNone(vp_path_match)
        vp_file = Path(vp_path_match.group(1))
        self.assertTrue(vp_file.exists())
        self.assertGreater(vp_file.stat().st_size, 0)

        full_res = await self.pw_media.call(self.mock_ctx, action="screenshot_full", target="chat")
        self.assertIn("[IMAGE_PATH:", full_res)
        full_path_match = re.search(r"\[IMAGE_PATH:(.*?)\]", full_res)
        self.assertIsNotNone(full_path_match)
        full_file = Path(full_path_match.group(1))
        self.assertTrue(full_file.exists())
        self.assertGreater(full_file.stat().st_size, 0)

        # 11. 释放关闭浏览器上下文 (close)
        close_res = await self.pw_page.call(self.mock_ctx, action="close")
        self.assertIn("已成功关闭并释放您的浏览器上下文", close_res)
        self.assertNotIn("e2e_session", self.context_mgr.contexts)

        # 彻底退出底层浏览器
        await self.adapter.stop()


if __name__ == "__main__":
    unittest.main()
