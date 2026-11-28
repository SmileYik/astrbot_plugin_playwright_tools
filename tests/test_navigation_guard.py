import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

if "astrbot" not in sys.modules:
    sys.modules["astrbot"] = MagicMock()
    sys.modules["astrbot.api"] = MagicMock()

from astrbot_plugin_playwright_tools.core.navigation_guard import NavigationGuard
from astrbot_plugin_playwright_tools.core.security_manager import SecurityManager


def _make_mock_page(url: str = "https://search.example.com/q", opener=None):
    page = MagicMock()
    page.url = url
    page._callbacks = {}
    page.on = lambda evt, cb: page._callbacks.update({evt: cb})
    page.opener = AsyncMock(return_value=opener)
    main_frame = MagicMock()
    main_frame.parent_frame = None
    main_frame.page = page
    main_frame.url = url
    page.main_frame = main_frame
    return page


def _make_mock_request(url: str, page, is_nav: bool = True, is_main_frame: bool = True, redirected_from=None):
    req = MagicMock()
    req.url = url
    req.is_navigation_request = MagicMock(return_value=is_nav)
    req.redirected_from = redirected_from
    if is_main_frame:
        req.frame = page.main_frame
    else:
        sub_frame = MagicMock()
        sub_frame.parent_frame = page.main_frame
        sub_frame.page = page
        req.frame = sub_frame
    return req


def _make_mock_route():
    route = MagicMock()
    route.continue_ = AsyncMock()
    route.abort = AsyncMock()
    return route


class TestNavigationGuard(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rules = [
            {
                "domains": ["search.example.com"],
                "allowed_actions": ["read", "click"],
                "allow_single_hop": True,
                "single_hop_allowed_actions": ["read", "screenshot"],
                "single_hop_follow_redirects": True,
            },
            {
                "domains": ["docs.example.com"],
                "allowed_actions": ["read", "click"],
                "allow_single_hop": False,
            },
            {
                "domains": ["strict.example.com"],
                "allowed_actions": ["read", "click"],
                "allow_single_hop": True,
                "single_hop_allowed_actions": ["read"],
                "single_hop_follow_redirects": False,
            },
        ]
        self.sec = SecurityManager(admin_only=False, whitelist_rules=self.rules)

    async def _attach_guard(self, initial_page):
        browser_ctx = MagicMock()
        ctx_callbacks = {}
        route_handlers = []

        async def _route(pattern, handler):
            route_handlers.append(handler)

        browser_ctx.route = _route
        browser_ctx.on = lambda evt, cb: ctx_callbacks.update({evt: cb})
        guard = NavigationGuard(security=self.sec, get_user_id=lambda: "user_1")
        await guard.attach(browser_ctx, initial_page)
        return guard, route_handlers[0], ctx_callbacks

    async def test_single_hop_allowed_and_second_hop_blocked(self):
        page = _make_mock_page("https://search.example.com/q")
        _, route_guard, _ = await self._attach_guard(page)

        # 1st hop to non-whitelisted target.com -> allowed
        r1 = _make_mock_route()
        await route_guard(r1, _make_mock_request("https://target.com/article", page))
        r1.continue_.assert_awaited_once()
        r1.abort.assert_not_awaited()

        # Simulate landing on target.com
        page.url = "https://target.com/article"

        # 2nd hop from target.com to other.com -> blocked
        r2 = _make_mock_route()
        await route_guard(r2, _make_mock_request("https://other.com/", page))
        r2.abort.assert_awaited_once()
        r2.continue_.assert_not_awaited()

    async def test_single_hop_disabled_rule_blocks_jump(self):
        page = _make_mock_page("https://docs.example.com/guide")
        _, route_guard, _ = await self._attach_guard(page)

        route = _make_mock_route()
        await route_guard(route, _make_mock_request("https://target.com/", page))
        route.abort.assert_awaited_once()
        route.continue_.assert_not_awaited()

    async def test_single_hop_follow_redirects_true_and_false(self):
        # Case 1: follow_redirects = True
        page1 = _make_mock_page("https://search.example.com/q")
        guard1, rg1, _ = await self._attach_guard(page1)

        req_hop = _make_mock_request("https://jump.example.net/go", page1)
        r_hop = _make_mock_route()
        await rg1(r_hop, req_hop)
        r_hop.continue_.assert_awaited_once()

        req_redir = _make_mock_request("https://final.org/page", page1, redirected_from=req_hop)
        r_redir = _make_mock_route()
        await rg1(r_redir, req_redir)
        r_redir.continue_.assert_awaited_once()
        r_redir.abort.assert_not_awaited()
        ok, _ = guard1.check_single_hop_permission(page1, "https://final.org/page", "read")
        self.assertTrue(ok)

        # Case 2: follow_redirects = False
        page2 = _make_mock_page("https://strict.example.com/q")
        _, rg2, _ = await self._attach_guard(page2)

        req_hop2 = _make_mock_request("https://jump.example.net/go", page2)
        r_hop2 = _make_mock_route()
        await rg2(r_hop2, req_hop2)
        r_hop2.continue_.assert_awaited_once()

        req_redir2 = _make_mock_request("https://final.org/page", page2, redirected_from=req_hop2)
        r_redir2 = _make_mock_route()
        await rg2(r_redir2, req_redir2)
        r_redir2.abort.assert_awaited_once()
        r_redir2.continue_.assert_not_awaited()

    async def test_popup_new_tab_single_hop(self):
        source_page = _make_mock_page("https://search.example.com/q")
        guard, route_guard, ctx_callbacks = await self._attach_guard(source_page)

        popup_page = _make_mock_page("about:blank", opener=source_page)
        ctx_callbacks["page"](popup_page)

        # Popup first navigation to non-whitelisted URL -> allowed via opener
        r_pop = _make_mock_route()
        await route_guard(r_pop, _make_mock_request("https://target.com/detail", popup_page))
        r_pop.continue_.assert_awaited_once()
        r_pop.abort.assert_not_awaited()

        popup_page.url = "https://target.com/detail"
        ok_read, _ = guard.check_single_hop_permission(popup_page, "https://target.com/detail", "read")
        self.assertTrue(ok_read)

        # Popup 2nd hop -> blocked
        r_pop2 = _make_mock_route()
        await route_guard(r_pop2, _make_mock_request("https://evil.com/", popup_page))
        r_pop2.abort.assert_awaited_once()

    async def test_single_hop_grant_action_permissions_and_url_update(self):
        page = _make_mock_page("https://search.example.com/q")
        guard, route_guard, _ = await self._attach_guard(page)

        r1 = _make_mock_route()
        await route_guard(r1, _make_mock_request("https://target.com/post?id=1", page))
        r1.continue_.assert_awaited_once()

        # framenavigated updates URL (e.g. hash/query change on same host)
        page.url = "https://target.com/post?id=1#section2"
        page.main_frame.url = page.url
        page._callbacks["framenavigated"](page.main_frame)

        ok_read, _ = guard.check_single_hop_permission(page, page.url, "read")
        self.assertTrue(ok_read)
        ok_ss, _ = guard.check_single_hop_permission(page, page.url, "screenshot")
        self.assertTrue(ok_ss)
        deny_click, reason = guard.check_single_hop_permission(page, page.url, "click")
        self.assertFalse(deny_click)
        self.assertIn("click", reason)

    async def test_navigate_back_to_whitelist_clears_grant(self):
        page = _make_mock_page("https://search.example.com/q")
        guard, route_guard, _ = await self._attach_guard(page)

        # Hop out to target.com
        r1 = _make_mock_route()
        await route_guard(r1, _make_mock_request("https://target.com/", page))
        page.url = "https://target.com/"

        ok_before, _ = guard.check_single_hop_permission(page, "https://target.com/", "read")
        self.assertTrue(ok_before)

        # Navigate back to whitelisted docs.example.com -> clears grant
        r2 = _make_mock_route()
        await route_guard(r2, _make_mock_request("https://docs.example.com/", page))
        r2.continue_.assert_awaited_once()
        page.url = "https://docs.example.com/"

        ok_after, _ = guard.check_single_hop_permission(page, "https://target.com/", "read")
        self.assertFalse(ok_after)

    async def test_subresource_requests_bypass_guard(self):
        page = _make_mock_page("https://docs.example.com/")
        _, route_guard, _ = await self._attach_guard(page)

        # Non-navigation request (e.g., image/xhr) to non-whitelisted CDN
        r_img = _make_mock_route()
        await route_guard(r_img, _make_mock_request("https://cdn.other.com/a.png", page, is_nav=False))
        r_img.continue_.assert_awaited_once()
        r_img.abort.assert_not_awaited()

        # Subframe navigation request (iframe)
        r_iframe = _make_mock_route()
        await route_guard(
            r_iframe,
            _make_mock_request("https://widget.other.com/embed", page, is_nav=True, is_main_frame=False),
        )
        r_iframe.continue_.assert_awaited_once()
        r_iframe.abort.assert_not_awaited()

    async def test_non_http_scheme_blocked_in_single_hop_and_permission_check(self):
        page = _make_mock_page("https://search.example.com/q")
        guard, route_guard, _ = await self._attach_guard(page)

        for bad_url in ("file:///etc/passwd", "data:text/html,<script>alert(1)</script>"):
            r = _make_mock_route()
            await route_guard(r, _make_mock_request(bad_url, page))
            r.abort.assert_awaited_once()
            r.continue_.assert_not_awaited()
            ok, _ = guard.check_single_hop_permission(page, bad_url, "read")
            self.assertFalse(ok)

    async def test_whitelisted_outbound_redirector_302_to_external_allowed(self):
        page = _make_mock_page("https://search.example.com/q")
        guard, route_guard, _ = await self._attach_guard(page)

        # Request 1: whitelisted search.example.com/link?url=...
        req1 = _make_mock_request("https://search.example.com/link?url=target", page)
        r1 = _make_mock_route()
        await route_guard(r1, req1)
        r1.continue_.assert_awaited_once()

        # Request 2: 302 redirect to non-whitelisted target.com
        req2 = _make_mock_request("https://target.com/article", page, redirected_from=req1)
        r2 = _make_mock_route()
        await route_guard(r2, req2)
        r2.continue_.assert_awaited_once()
        r2.abort.assert_not_awaited()

        page.url = "https://target.com/article"
        ok, _ = guard.check_single_hop_permission(page, "https://target.com/article", "read")
        self.assertTrue(ok)

        # 2nd hop from target.com -> blocked
        r3 = _make_mock_route()
        await route_guard(r3, _make_mock_request("https://other.com/", page))
        r3.abort.assert_awaited_once()

    async def test_aborted_redirect_does_not_poison_whitelisted_tab(self):
        page = _make_mock_page("https://strict.example.com/q")
        _, route_guard, _ = await self._attach_guard(page)

        req_hop = _make_mock_request("https://jump.example.net/go", page)
        r_hop = _make_mock_route()
        await route_guard(r_hop, req_hop)
        r_hop.continue_.assert_awaited_once()

        # Redirect is aborted because follow_redirects=False
        req_redir = _make_mock_request("https://final.org/page", page, redirected_from=req_hop)
        r_redir = _make_mock_route()
        await route_guard(r_redir, req_redir)
        r_redir.abort.assert_awaited_once()

        # Tab is still on strict.example.com; another direct single-hop click should still work
        r_next = _make_mock_route()
        await route_guard(r_next, _make_mock_request("https://direct.org/page", page))
        r_next.continue_.assert_awaited_once()
        r_next.abort.assert_not_awaited()

    async def test_popup_about_blank_blocked_and_double_hop_race(self):
        source_page = _make_mock_page("https://search.example.com/q")
        guard, route_guard, ctx_callbacks = await self._attach_guard(source_page)

        popup_page = _make_mock_page("about:blank#blocked", opener=source_page)
        ctx_callbacks["page"](popup_page)

        # 1st navigation on about:blank#blocked popup -> allowed via opener
        r1 = _make_mock_route()
        await route_guard(r1, _make_mock_request("https://target.com/detail", popup_page))
        r1.continue_.assert_awaited_once()
        r1.abort.assert_not_awaited()

        # Even if popup.url is still about:blank#blocked before commit, a 2nd non-redirect hop on it is blocked
        r2 = _make_mock_route()
        await route_guard(r2, _make_mock_request("https://other.com/", popup_page))
        r2.abort.assert_awaited_once()
        r2.continue_.assert_not_awaited()

    async def test_popup_request_frame_not_ready_binds_pending_grant(self):
        source_page = _make_mock_page("https://search.example.com/q")
        browser_ctx = MagicMock()
        ctx_callbacks = {}
        route_handlers = []

        async def _route(pattern, handler):
            route_handlers.append(handler)

        browser_ctx.route = _route
        browser_ctx.on = lambda evt, cb: ctx_callbacks.update({evt: cb})
        guard = NavigationGuard(
            security=self.sec,
            get_user_id=lambda: "user_1",
            get_fallback_source_page=lambda: source_page,
        )
        await guard.attach(browser_ctx, source_page)
        route_guard = route_handlers[0]

        # Simulate Playwright raising Error on request.frame before popup's frame._page is created
        def _make_unattached_req(url: str, redirected_from=None):
            req = MagicMock()
            req.url = url
            req.is_navigation_request = MagicMock(return_value=True)
            req.redirected_from = redirected_from
            type(req).frame = property(
                lambda _self: (_ for _ in ()).throw(
                    RuntimeError("Frame for this navigation request is not available, because the request was issued before the frame is created.")
                )
            )
            return req

        req1 = _make_unattached_req("https://movie.douban.com/subject/1/")
        r1 = _make_mock_route()
        await route_guard(r1, req1)
        r1.continue_.assert_awaited_once()

        req2 = _make_unattached_req("https://sec.douban.com/c?r=1", redirected_from=req1)
        r2 = _make_mock_route()
        await route_guard(r2, req2)
        r2.continue_.assert_awaited_once()

        # Now popup page attaches and lands on sec.douban.com
        popup_page = _make_mock_page("https://sec.douban.com/c?r=1", opener=source_page)
        ctx_callbacks["page"](popup_page)
        popup_page._callbacks["framenavigated"](popup_page.main_frame)

        ok_read, _ = guard.check_single_hop_permission(popup_page, "https://sec.douban.com/c?r=1", "read")
        self.assertTrue(ok_read)

        # 2nd hop on popup_page must still be blocked
        r3 = _make_mock_route()
        await route_guard(r3, _make_mock_request("https://other.com/", popup_page))
        r3.abort.assert_awaited_once()

    async def test_on_page_closed_callback_invoked(self):
        page = _make_mock_page("https://example.com")
        browser_ctx = MagicMock()
        browser_ctx.route = AsyncMock()
        browser_ctx.on = MagicMock()
        closed_pages = []

        guard = NavigationGuard(security=self.sec, get_user_id=lambda: "user_1")
        await guard.attach(browser_ctx, page, on_page_closed=lambda p: closed_pages.append(p))
        page._callbacks["close"]()
        self.assertEqual(closed_pages, [page])


if __name__ == "__main__":
    unittest.main()
