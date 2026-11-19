import time
from dataclasses import dataclass, field
from typing import Any
from ..adapts.base import BrowserAdapterBase
from .security_manager import SecurityManager

@dataclass
class BrowserSessionContext:
    """单个浏览器上下文会话数据结构。"""
    session_id: str
    owner_id: str
    browser_context: Any
    current_page: Any
    pages: list[Any] = field(default_factory=list)
    allowed_users: set[str] = field(default_factory=set)
    last_active_time: float = field(default_factory=time.time)
    ref_map: dict[int, dict] = field(default_factory=dict)
    dialog_action: dict | None = None
    last_dialog_message: str | None = None

    def touch(self) -> None:
        """更新最后活跃时间。"""
        self.last_active_time = time.time()

class ContextManager:
    """多租户浏览器上下文管理器，负责个人/会话模式隔离、协作寻址及生命周期回收。"""

    def __init__(
        self,
        adapter: BrowserAdapterBase,
        security: SecurityManager,
        mode: str = "personal",
        idle_timeout_minutes: int = 10,
        storage_state_path: str = "",
    ):
        self.adapter = adapter
        self.security = security
        self.mode = mode.lower()  # "personal" 或 "session"
        self.idle_timeout_minutes = idle_timeout_minutes
        self.storage_state_path = storage_state_path
        self.contexts: dict[Any, BrowserSessionContext] = {}
        self.user_active_pointer: dict[tuple[str, str], str] = {}

    def _get_context_key(self, session_id: str, owner_id: str) -> Any:
        return (session_id, owner_id) if self.mode == "personal" else session_id

    async def resolve_context(
        self, session_id: str, sender_id: str, peek: bool = False
    ) -> tuple[BrowserSessionContext | None, str]:
        """为当前发送者解析目标浏览器上下文，并返回提示前缀（若非本人拥有）。

        Args:
            session_id: 会话 ID
            sender_id: 发送者 UID
            peek: 是否仅查看而不新建上下文 (用于 /browser status 等指令)
        """
        sender_id = str(sender_id)
        session_id = str(session_id)

        if self.mode == "session":
            key = session_id
            if key not in self.contexts:
                if peek:
                    return None, ""
                if self.security.admin_only and not self.security.is_admin(sender_id):
                    return None, "拒绝访问：当前插件已配置为仅管理员可用"
                ctx = await self._create_new_context(session_id, sender_id)
                self.contexts[key] = ctx
            context = self.contexts[key]
            context.touch()
            return context, ""

        # 个人模式寻址逻辑：
        # 1. 显式切换绑定的目标上下文
        pointer_owner = self.user_active_pointer.get((session_id, sender_id))
        if pointer_owner:
            target_key = (session_id, pointer_owner)
            if target_key in self.contexts:
                ctx = self.contexts[target_key]
                if sender_id in ctx.allowed_users or sender_id == ctx.owner_id:
                    ctx.touch()
                    hint = f"[当前操作上下文: 用户 {ctx.owner_id} 的浏览器]" if ctx.owner_id != sender_id else ""
                    return ctx, hint

        # 2. 自身拥有的上下文
        own_key = (session_id, sender_id)
        if own_key in self.contexts:
            ctx = self.contexts[own_key]
            ctx.touch()
            return ctx, ""

        # 3. 最近活跃的被受邀上下文
        invited_contexts = []
        for (s_id, o_id), ctx in self.contexts.items():
            if s_id == session_id and sender_id in ctx.allowed_users:
                invited_contexts.append(ctx)

        if invited_contexts:
            invited_contexts.sort(key=lambda c: c.last_active_time, reverse=True)
            chosen = invited_contexts[0]
            chosen.touch()
            return chosen, f"[当前操作上下文: 用户 {chosen.owner_id} 的浏览器]"

        # 若仅查看则不自动实例化
        if peek:
            return None, ""

        # 检查仅管理员模式
        if self.security.admin_only and not self.security.is_admin(sender_id):
            return None, "拒绝访问：当前插件已配置为仅管理员可用"

        # 4. 自身新建个人上下文
        new_ctx = await self._create_new_context(session_id, sender_id)
        self.contexts[own_key] = new_ctx
        new_ctx.touch()
        return new_ctx, ""

    async def _create_new_context(self, session_id: str, owner_id: str) -> BrowserSessionContext:
        """根据所有者权限创建底层 BrowserContext、路由守卫与首个 Page。"""
        state_to_inject = None
        if self.security.is_admin(owner_id) and self.storage_state_path:
            state_to_inject = self.storage_state_path

        browser_ctx = await self.adapter.create_context(storage_state_path=state_to_inject)

        # 挂载顶层导航路由拦截守卫 (Navigation Guard)
        async def _route_guard(route, request):
            try:
                is_nav = request.is_navigation_request() if hasattr(request, "is_navigation_request") else False
                if is_nav:
                    allowed, _ = self.security.is_url_allowed_navigation(owner_id, request.url)
                    if not allowed:
                        await route.abort()
                        return
                await route.continue_()
            except Exception:
                try:
                    await route.continue_()
                except Exception:
                    pass

        if hasattr(browser_ctx, "route"):
            try:
                res_route = browser_ctx.route("**/*", _route_guard)
                if hasattr(res_route, "__await__"):
                    await res_route
            except Exception:
                pass

        first_page = await browser_ctx.new_page()

        ctx = BrowserSessionContext(
            session_id=session_id,
            owner_id=owner_id,
            browser_context=browser_ctx,
            current_page=first_page,
            pages=[first_page],
            allowed_users={owner_id},
        )

        # 挂载新标签页 (popup) 监听器
        def _on_popup(new_page):
            if new_page not in ctx.pages:
                ctx.pages.append(new_page)
                ctx.current_page = new_page

        if hasattr(browser_ctx, "on"):
            try:
                browser_ctx.on("page", _on_popup)
            except Exception:
                pass

        return ctx

    def invite_user(self, session_id: str, owner_id: str, target_user_id: str) -> tuple[bool, str]:
        """邀请目标用户加入所有者当前的个人上下文。"""
        owner_id = str(owner_id)
        target_user_id = str(target_user_id)
        key = self._get_context_key(session_id, owner_id)

        if key not in self.contexts:
            return False, "您当前未开启活跃的浏览器上下文，无法发起邀请"

        context = self.contexts[key]
        if owner_id != context.owner_id:
            return False, "只有当前浏览器的创建者才能邀请协作者"

        context.allowed_users.add(target_user_id)
        return True, f"已成功将 @{target_user_id} 邀请加入您的浏览器操作上下文"

    def switch_user_context(self, session_id: str, sender_id: str, target_owner_id: str) -> tuple[bool, str]:
        """显式切换发送者在当前会话中操作的上下文目标。"""
        sender_id = str(sender_id)
        target_owner_id = str(target_owner_id)
        target_key = (session_id, target_owner_id)

        if target_key not in self.contexts:
            return False, f"未找到用户 @{target_owner_id} 开启的活跃浏览器"

        target_ctx = self.contexts[target_key]
        if sender_id not in target_ctx.allowed_users and sender_id != target_ctx.owner_id:
            return False, f"您未被授予操作用户 @{target_owner_id} 浏览器的权限"

        self.user_active_pointer[(session_id, sender_id)] = target_owner_id
        return True, f"已将您的操作上下文切换至用户 @{target_owner_id} 的浏览器"

    async def close_user_context(self, session_id: str, sender_id: str) -> tuple[bool, str]:
        """关闭并释放发送者所拥有的个人上下文。"""
        sender_id = str(sender_id)
        key = self._get_context_key(session_id, sender_id)

        if key not in self.contexts:
            return False, "您当前没有开启任何属于您自己的浏览器上下文"

        ctx = self.contexts.pop(key)
        try:
            await ctx.browser_context.close()
        except Exception:
            pass

        # 清除指向此上下文的指针
        to_del = [k for k, v in self.user_active_pointer.items() if k[0] == session_id and v == sender_id]
        for k in to_del:
            del self.user_active_pointer[k]

        return True, "已成功关闭并释放您的浏览器上下文"

    async def cleanup_idle_contexts(self) -> int:
        """检查并自动销毁超时的空闲上下文，返回销毁数量。"""
        if self.idle_timeout_minutes <= 0:
            return 0

        now = time.time()
        timeout_seconds = self.idle_timeout_minutes * 60
        expired_keys = [
            k for k, ctx in self.contexts.items()
            if (now - ctx.last_active_time) > timeout_seconds
        ]

        count = 0
        for k in expired_keys:
            ctx = self.contexts.pop(k, None)
            if ctx:
                try:
                    await ctx.browser_context.close()
                except Exception:
                    pass
                count += 1

        return count
