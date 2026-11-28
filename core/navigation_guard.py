import inspect
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from astrbot.api import logger

from .security_manager import SecurityManager


@dataclass
class SingleHopGrant:
    """单个标签页的单跳放行授权状态。"""

    allowed_actions: set[str]
    follow_redirects: bool
    granted_url: str


class NavigationGuard:
    """顶层导航路由守卫与单跳授权状态管理器。"""

    def __init__(
        self,
        security: SecurityManager,
        get_user_id: Callable[[], str],
        get_fallback_source_page: Callable[[], Any] | None = None,
    ):
        self.security = security
        self.get_user_id = get_user_id
        self.get_fallback_source_page = get_fallback_source_page
        self._page_grants: dict[int, SingleHopGrant] = {}
        self._page_openers: dict[int, Any] = {}
        self._pending_url_grants: dict[str, SingleHopGrant] = {}

    @staticmethod
    def _is_main_frame(frame: Any, page: Any) -> bool:
        """判断给定 frame 是否为页面主帧。"""
        if frame is None:
            return True
        if hasattr(frame, "parent_frame"):
            return frame.parent_frame is None
        if page is not None and hasattr(page, "main_frame"):
            return frame == page.main_frame
        return True

    def _is_main_frame_nav(self, request: Any) -> tuple[bool, Any]:
        """判断请求是否为顶层主帧导航请求，并返回关联的 page（兼容新弹窗 frame 尚未挂载时）。"""
        is_nav = request.is_navigation_request() if hasattr(request, "is_navigation_request") else False
        if not is_nav:
            return False, None
        try:
            frame = getattr(request, "frame", None)
        except Exception as e:
            # Playwright 在新标签页弹窗初始导航时，request.frame 可能因 frame._page 尚未创建而抛错
            logger.debug(f"[NavigationGuard] 导航请求读取 frame 失败（视为未挂载新弹窗首跳）: {e}")
            return True, None
        page = getattr(frame, "page", None) if frame is not None else None
        if not self._is_main_frame(frame, page):
            return False, page
        return True, page

    async def _resolve_source_page(self, page: Any) -> Any:
        """解析发起本次导航的源页面（新弹窗首跳时追溯 opener）。"""
        if page is None:
            return None
        current_url = getattr(page, "url", "") or ""
        if current_url == "" or current_url.startswith("about:blank"):
            opener = self._page_openers.get(id(page))
            if opener is not None:
                return opener
            if hasattr(page, "opener") and callable(page.opener):
                try:
                    res = page.opener()
                    return await res if inspect.isawaitable(res) else res
                except Exception as e:
                    logger.debug(f"[NavigationGuard] 获取页面 opener 失败: {e}")
                    return None
        return page

    def _setup_page_listeners(
        self,
        page: Any,
        on_main_frame_navigated: Callable[[Any], None] | None = None,
        on_page_closed: Callable[[Any], None] | None = None,
    ) -> None:
        """为页面挂载主帧导航、弹窗来源记录与关闭清理监听器。"""
        if not hasattr(page, "on"):
            return

        def _on_frame_nav(frame: Any) -> None:
            try:
                if not self._is_main_frame(frame, page):
                    return
                if on_main_frame_navigated is not None:
                    on_main_frame_navigated(page)
                frame_url = getattr(frame, "url", "") or getattr(page, "url", "") or ""
                if frame_url:
                    user_id = self.get_user_id()
                    allowed, _ = self.security.is_url_allowed_navigation(user_id, frame_url)
                    if allowed:
                        self._page_grants.pop(id(page), None)
                        self._pending_url_grants.pop(frame_url, None)
                    else:
                        if id(page) not in self._page_grants:
                            pending = self._bind_pending_grant(page, frame_url)
                            if pending is not None:
                                return
                        if id(page) in self._page_grants:
                            self._page_grants[id(page)].granted_url = frame_url
            except Exception as e:
                logger.debug(f"[NavigationGuard] 页面帧导航监听异常: {e}")

        def _on_child_popup(popup_page: Any) -> None:
            if popup_page is not None:
                self._page_openers[id(popup_page)] = page

        def _on_close(*_args: Any, **_kwargs: Any) -> None:
            self._page_grants.pop(id(page), None)
            self._page_openers.pop(id(page), None)
            if on_page_closed is not None:
                try:
                    on_page_closed(page)
                except Exception as e:
                    logger.debug(f"[NavigationGuard] 页面关闭回调异常: {e}")

        try:
            page.on("framenavigated", _on_frame_nav)
            page.on("popup", _on_child_popup)
            page.on("close", _on_close)
        except Exception as e:
            logger.debug(f"[NavigationGuard] 注册页面事件监听失败: {e}")

    @staticmethod
    def _get_root_request(request: Any) -> Any:
        """沿 redirected_from 链回溯初始导航请求。"""
        cur = request
        seen: set[int] = set()
        while getattr(cur, "redirected_from", None) is not None:
            prev = cur.redirected_from
            if id(prev) in seen:
                break
            seen.add(id(prev))
            cur = prev
        return cur

    def _bind_pending_grant(self, page: Any, url: str) -> SingleHopGrant | None:
        """将未挂载新弹窗阶段暂存的单跳授权绑定到已就绪的 Page 实例。"""
        if page is None or not url:
            return None
        grant = self._pending_url_grants.pop(url, None)
        if grant is None:
            cur_parsed = urlparse(url)
            cur_host = (cur_parsed.hostname or "").lower()
            cur_scheme = cur_parsed.scheme.lower()
            if cur_host and cur_scheme in ("http", "https"):
                for pending_url in list(self._pending_url_grants.keys()):
                    p_parsed = urlparse(pending_url)
                    if (
                        p_parsed.scheme.lower() == cur_scheme
                        and (p_parsed.hostname or "").lower() == cur_host
                    ):
                        grant = self._pending_url_grants.pop(pending_url)
                        grant.granted_url = url
                        break
        if grant is not None:
            self._page_grants[id(page)] = grant
        return grant

    def _store_grant(self, page: Any, target_url: str, grant: SingleHopGrant) -> None:
        """保存单跳授权：page 已就绪则绑定到 page，否则按 URL 暂存待绑定。"""
        if page is not None:
            self._page_grants[id(page)] = grant
        elif target_url:
            self._pending_url_grants[target_url] = grant

    async def _route_guard(self, route: Any, request: Any) -> None:
        """拦截并判定顶层导航请求是否允许通过。"""
        try:
            is_main_nav, page = self._is_main_frame_nav(request)
            if not is_main_nav:
                await route.continue_()
                return

            user_id = self.get_user_id()
            target_url = getattr(request, "url", "") or ""
            allowed, _ = self.security.is_url_allowed_navigation(user_id, target_url)
            if allowed:
                if page is not None:
                    self._page_grants.pop(id(page), None)
                self._pending_url_grants.pop(target_url, None)
                await route.continue_()
                return

            parsed_target = urlparse(target_url)
            if parsed_target.scheme.lower() not in ("http", "https") or not parsed_target.hostname:
                await route.abort()
                return

            page_key = id(page) if page is not None else None
            prev_req = getattr(request, "redirected_from", None)
            if prev_req is not None:
                grant = self._page_grants.get(page_key) if page_key is not None else None
                if grant is None:
                    prev_url = getattr(prev_req, "url", "") or ""
                    if prev_url in self._pending_url_grants:
                        grant = self._pending_url_grants.pop(prev_url)
                if grant is not None:
                    if grant.follow_redirects:
                        grant.granted_url = target_url
                        self._store_grant(page, target_url, grant)
                        await route.continue_()
                        return
                    if page_key is not None:
                        self._page_grants.pop(page_key, None)
                    await route.abort()
                    return

                # 白名单站点自身出站重定向链（如搜索引擎跳转链接 302 到外部站）
                root_req = self._get_root_request(request)
                root_url = getattr(root_req, "url", "") or ""
                if root_url:
                    allow_hop, hop_actions, follow_redirects = self.security.get_single_hop_policy(root_url)
                    if allow_hop and follow_redirects:
                        self._store_grant(
                            page,
                            target_url,
                            SingleHopGrant(
                                allowed_actions=set(hop_actions),
                                follow_redirects=True,
                                granted_url=target_url,
                            ),
                        )
                        await route.continue_()
                        return

                await route.abort()
                return

            if page_key is not None and page_key in self._page_grants:
                await route.abort()
                return

            if page is not None:
                source_page = await self._resolve_source_page(page)
            elif self.get_fallback_source_page is not None:
                source_page = self.get_fallback_source_page()
            else:
                source_page = None

            if source_page is None or id(source_page) in self._page_grants:
                await route.abort()
                return

            source_url = getattr(source_page, "url", "") or ""
            allow_hop, hop_actions, follow_redirects = self.security.get_single_hop_policy(source_url)
            if allow_hop:
                self._store_grant(
                    page,
                    target_url,
                    SingleHopGrant(
                        allowed_actions=set(hop_actions),
                        follow_redirects=follow_redirects,
                        granted_url=target_url,
                    ),
                )
                await route.continue_()
                return

            await route.abort()
        except Exception as e:
            logger.warning(f"[NavigationGuard] 路由守卫拦截处理异常: {e}")
            try:
                await route.continue_()
            except Exception as ce:
                logger.debug(f"[NavigationGuard] 路由放行回退异常: {ce}")

    async def attach(
        self,
        browser_ctx: Any,
        initial_page: Any,
        on_new_page: Callable[[Any], None] | None = None,
        on_main_frame_navigated: Callable[[Any], None] | None = None,
        on_page_closed: Callable[[Any], None] | None = None,
    ) -> None:
        """为 BrowserContext 挂载路由守卫与页面/弹窗生命周期监听。"""
        if hasattr(browser_ctx, "route"):
            try:
                res_route = browser_ctx.route("**/*", self._route_guard)
                if inspect.isawaitable(res_route):
                    await res_route
            except Exception as e:
                logger.warning(f"[NavigationGuard] 挂载全局路由拦截守卫失败: {e}")

        self._setup_page_listeners(initial_page, on_main_frame_navigated, on_page_closed)

        if hasattr(browser_ctx, "on"):
            def _on_popup(new_page: Any) -> None:
                try:
                    # 尽量在弹窗创建时记录 opener，避免首跳时异步获取开销
                    opener_attr = getattr(new_page, "opener", None)
                    if opener_attr is not None and not callable(opener_attr):
                        self._page_openers[id(new_page)] = opener_attr
                    if on_new_page is not None:
                        on_new_page(new_page)
                    self._setup_page_listeners(new_page, on_main_frame_navigated, on_page_closed)
                except Exception as e:
                    logger.debug(f"[NavigationGuard] 弹窗新页面注册监听异常: {e}")

            try:
                browser_ctx.on("page", _on_popup)
            except Exception as e:
                logger.debug(f"[NavigationGuard] 注册新标签页 page 监听失败: {e}")

    def check_single_hop_permission(self, page: Any, current_url: str, action: str) -> tuple[bool, str]:
        """校验当前页面是否持有有效单跳授权且允许执行指定操作。"""
        if page is None:
            return False, "拒绝操作：当前页面未获得单跳授权"
        grant = self._page_grants.get(id(page))
        if grant is None:
            grant = self._bind_pending_grant(page, current_url)
        if grant is None:
            return False, "拒绝操作：当前页面未在白名单中且未获得单跳授权"

        cur_parsed = urlparse(current_url)
        grant_parsed = urlparse(grant.granted_url)
        if (
            cur_parsed.scheme.lower() not in ("http", "https")
            or not cur_parsed.hostname
            or not grant_parsed.hostname
            or cur_parsed.scheme.lower() != grant_parsed.scheme.lower()
            or cur_parsed.hostname.lower() != grant_parsed.hostname.lower()
        ):
            return False, "拒绝操作：当前页面与单跳授权目标域名不一致"

        if action not in grant.allowed_actions:
            return False, f"拒绝操作：单跳落地页未被授予 '{action}' 操作权限"

        return True, ""
