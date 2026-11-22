import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from ..adapts.base import BrowserAdapterBase
from .security_manager import SecurityManager

from astrbot.api import logger

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page
else:
    try:
        from playwright.async_api import BrowserContext, Page
    except ImportError:
        BrowserContext = Any
        Page = Any

@dataclass
class BrowserSessionContext:
    """单个浏览器上下文会话数据结构。"""
    session_id: str
    owner_id: str
    browser_context: "BrowserContext"
    current_page: "Page"
    pages: list["Page"] = field(default_factory=list)
    allowed_users: set[str] = field(default_factory=set)
    created_time: float = field(default_factory=time.time)
    last_active_time: float = field(default_factory=time.time)
    idle_timeout_seconds: float = 600.0
    is_external: bool = False
    plugin_name: str = ""
    current_operator_id: str = ""
    session_name: str = ""
    owner_name: str = ""
    ref_map: dict[Any, dict] = field(default_factory=dict)
    dialog_action: dict | None = None
    last_dialog_message: str | None = None
    current_snapshot: Any = None
    is_snapshot_dirty: bool = False
    ref_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_ref_id: int = 1

    def touch(self) -> None:
        """更新最后活跃时间。"""
        self.last_active_time = time.time()

    def allocate_ref_id(self) -> str:
        """分配单调递增的 ref_id 字符串，当达到 1,000,000 时回滚为 1。"""
        current = self.next_ref_id
        if current >= 1_000_000:
            self.next_ref_id = 1
        else:
            self.next_ref_id += 1
        return str(current)

# 别名
ManagedContext = BrowserSessionContext

class ContextManager:
    """多租户浏览器上下文管理器，负责个人/会话模式隔离、协作寻址及生命周期回收。"""

    def __init__(
        self,
        adapter: BrowserAdapterBase,
        security: SecurityManager,
        mode: str = "personal",
        idle_timeout_minutes: int = 10,
        storage_state_path: str = "",
        audit_logger: Any = None,
    ):
        self.adapter = adapter
        self.security = security
        self.mode = mode.lower()  # "personal" 或 "session"
        self.idle_timeout_minutes = idle_timeout_minutes
        self.storage_state_path = storage_state_path
        self.audit_logger = audit_logger
        self.contexts: dict[Any, BrowserSessionContext] = {}
        self.user_active_pointer: dict[tuple[str, str], str] = {}
        self._creation_locks: dict[Any, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _get_creation_lock(self, key: Any) -> asyncio.Lock:
        """获取指定 Key 的专用创建锁，防并发竞态。"""
        if key not in self._creation_locks:
            self._creation_locks[key] = asyncio.Lock()
        return self._creation_locks[key]

    def _get_context_key(self, session_id: str, owner_id: str) -> Any:
        return (session_id, owner_id) if self.mode == "personal" else session_id

    def _format_context_key(self, key: Any) -> str:
        """格式化上下文 Key，若为 (session_id, owner_id) 则返回 'session_id:owner_id'，否则返回其字符串表示。"""
        if isinstance(key, (tuple, list)) and len(key) == 2:
            return f"{key[0]}:{key[1]}"
        return str(key)

    def _fire_lifecycle_log(
        self,
        session_id: str,
        context_key: str,
        owner_id: str,
        event_type: str,
        operator_id: str,
        session_name: str = "",
        operator_name: str = "",
        owner_name: str = "",
        details: dict | list | str | None = None,
    ) -> Any:
        """非阻塞或安全派发生命周期审计记录。"""
        if not self.audit_logger:
            return None
        try:
            res = self.audit_logger.log_lifecycle(
                session_id=session_id,
                context_key=context_key,
                owner_id=owner_id,
                event_type=event_type,
                operator_id=operator_id,
                session_name=session_name,
                operator_name=operator_name,
                owner_name=owner_name,
                details=details,
            )
            if hasattr(res, "__await__"):
                try:
                    loop = asyncio.get_running_loop()
                    return loop.create_task(res)
                except RuntimeError:
                    try:
                        res.send(None)
                    except StopIteration:
                        pass
                    except Exception as e:
                        logger.debug(f"[ContextManager] 同步驱动协程日志异常: {e}")
                        try:
                            res.close()
                        except Exception as ce:
                            logger.debug(f"[ContextManager] 关闭未完成协程异常: {ce}")
            return res
        except Exception as e:
            logger.warning(f"[ContextManager] 派发生命周期日志失败: {e}")
            return None

    async def resolve_context(
        self,
        session_id: str,
        sender_id: str,
        peek: bool = False,
        session_name: str = "",
        sender_name: str = "",
    ) -> tuple[BrowserSessionContext | None, str]:
        """为当前发送者解析目标浏览器上下文，并返回提示前缀（若非本人拥有）。

        Args:
            session_id: 会话 ID
            sender_id: 发送者 UID
            peek: 是否仅查看而不新建上下文 (用于 /browser status 等指令)
            session_name: 会话展示名称
            sender_name: 发送者用户展示名称
        """
        sender_id = str(sender_id)
        session_id = str(session_id)

        if self.mode == "session":
            key = session_id
            if key not in self.contexts:
                if peek:
                    return None, ""
                lock = self._get_creation_lock(key)
                async with lock:
                    if key not in self.contexts:
                        if self.security.admin_only and not self.security.is_admin(sender_id):
                            return None, "拒绝访问：当前插件已配置为仅管理员可用"
                        ctx = await self._create_new_context(session_id, sender_id, session_name=session_name, owner_name=sender_name)
                        self.contexts[key] = ctx
            context = self.contexts[key]
            if session_name and not getattr(context, "session_name", ""):
                context.session_name = session_name
            if sender_name and (not getattr(context, "owner_name", "") or context.owner_id == sender_id):
                context.owner_name = sender_name
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
                    if session_name and not getattr(ctx, "session_name", ""):
                        ctx.session_name = session_name
                    if sender_name and sender_id == ctx.owner_id and not getattr(ctx, "owner_name", ""):
                        ctx.owner_name = sender_name
                    ctx.touch()
                    hint = f"[当前操作上下文: 用户 {ctx.owner_id} 的浏览器]" if ctx.owner_id != sender_id else ""
                    return ctx, hint

        # 2. 自身拥有的上下文
        own_key = (session_id, sender_id)
        if own_key in self.contexts:
            ctx = self.contexts[own_key]
            if session_name and not getattr(ctx, "session_name", ""):
                ctx.session_name = session_name
            if sender_name and not getattr(ctx, "owner_name", ""):
                ctx.owner_name = sender_name
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
            if session_name and not getattr(chosen, "session_name", ""):
                chosen.session_name = session_name
            chosen.touch()
            return chosen, f"[当前操作上下文: 用户 {chosen.owner_id} 的浏览器]"

        # 若仅查看则不自动实例化
        if peek:
            return None, ""

        # 检查仅管理员模式
        if self.security.admin_only and not self.security.is_admin(sender_id):
            return None, "拒绝访问：当前插件已配置为仅管理员可用"

        # 4. 自身新建个人上下文
        lock = self._get_creation_lock(own_key)
        async with lock:
            if own_key not in self.contexts:
                new_ctx = await self._create_new_context(session_id, sender_id, session_name=session_name, owner_name=sender_name)
                self.contexts[own_key] = new_ctx
            new_ctx = self.contexts[own_key]
        new_ctx.touch()
        return new_ctx, ""

    async def _create_new_context(
        self,
        session_id: str,
        owner_id: str,
        session_name: str = "",
        owner_name: str = "",
        is_external: bool = False,
        plugin_name: str = "",
        idle_timeout_seconds: float | None = None,
    ) -> BrowserSessionContext:
        """根据所有者权限创建底层 BrowserContext、路由守卫与首个 Page。"""
        state_to_inject = None
        if self.security.is_admin(owner_id) and self.storage_state_path:
            state_to_inject = self.storage_state_path

        browser_ctx = None
        try:
            browser_ctx = await self.adapter.create_context(storage_state_path=state_to_inject)

            ctx_box: list[BrowserSessionContext | None] = [None]

            # 挂载顶层导航路由拦截守卫 (Navigation Guard，外部插件跳过)
            if not is_external and hasattr(browser_ctx, "route"):
                async def _route_guard(route, request):
                    try:
                        cur_ctx = ctx_box[0]
                        if cur_ctx and getattr(cur_ctx, "is_external", False):
                            await route.continue_()
                            return

                        is_nav = request.is_navigation_request() if hasattr(request, "is_navigation_request") else False
                        if is_nav:
                            if self.mode == "session":
                                op_id = getattr(cur_ctx, "current_operator_id", "") if cur_ctx else ""
                                allowed, _ = self.security.is_url_allowed_navigation(op_id, request.url)
                            else:
                                allowed, _ = self.security.is_url_allowed_navigation(owner_id, request.url)
                            if not allowed:
                                await route.abort()
                                return
                        await route.continue_()
                    except Exception as e:
                        logger.warning(f"[ContextManager] 路由守卫拦截处理异常: {e}")
                        try:
                            await route.continue_()
                        except Exception as ce:
                            logger.debug(f"[ContextManager] 路由放行回退异常: {ce}")

                try:
                    res_route = browser_ctx.route("**/*", _route_guard)
                    if hasattr(res_route, "__await__"):
                        await res_route
                except Exception as e:
                    logger.warning(f"[ContextManager] 挂载全局路由拦截守卫失败: {e}")

            first_page = await browser_ctx.new_page()

            if idle_timeout_seconds is not None:
                ctx_timeout = float(idle_timeout_seconds)
            elif self.idle_timeout_minutes > 0:
                ctx_timeout = float(self.idle_timeout_minutes * 60)
            else:
                ctx_timeout = 0.0

            ctx = BrowserSessionContext(
                session_id=session_id,
                owner_id=owner_id,
                browser_context=browser_ctx,
                current_page=first_page,
                pages=[first_page],
                allowed_users={owner_id},
                session_name=session_name,
                owner_name=owner_name,
                is_external=is_external,
                plugin_name=plugin_name,
                idle_timeout_seconds=ctx_timeout,
            )
            ctx_box[0] = ctx

            # 外部插件原生事件静默感知保活
            if is_external and hasattr(browser_ctx, "on"):
                def _touch(*args, **kwargs):
                    ctx.touch()
                try:
                    browser_ctx.on("page", lambda p: _touch())
                    browser_ctx.on("request", lambda req: _touch())
                    browser_ctx.on("response", lambda resp: _touch())
                except Exception as e:
                    logger.debug(f"[ContextManager] 外部上下文挂载事件保活监听异常: {e}")

            def _setup_page_listeners(page):
                def _on_frame_nav(frame):
                    try:
                        is_main = False
                        if hasattr(frame, "parent_frame") and frame.parent_frame is None:
                            is_main = True
                        elif hasattr(page, "main_frame") and frame == page.main_frame:
                            is_main = True
                        elif not hasattr(frame, "parent_frame") and not hasattr(page, "main_frame"):
                            is_main = True

                        if is_main:
                            ctx.is_snapshot_dirty = True
                            ctx.current_snapshot = None
                            ctx.ref_map = {}
                    except Exception as e:
                        logger.debug(f"[ContextManager] 页面帧导航监听异常: {e}")

                if hasattr(page, "on"):
                    try:
                        page.on("framenavigated", _on_frame_nav)
                    except Exception as e:
                        logger.debug(f"[ContextManager] 注册 framenavigated 监听失败: {e}")

            _setup_page_listeners(first_page)

            # 挂载新标签页 (popup) 监听器
            def _on_popup(new_page):
                try:
                    if new_page not in ctx.pages:
                        ctx.pages.append(new_page)
                        ctx.current_page = new_page
                        _setup_page_listeners(new_page)
                except Exception as e:
                    logger.debug(f"[ContextManager] 弹窗新页面注册监听异常: {e}")

            if hasattr(browser_ctx, "on"):
                try:
                    browser_ctx.on("page", _on_popup)
                except Exception as e:
                    logger.debug(f"[ContextManager] 注册新标签页 page 监听失败: {e}")

            if self.audit_logger:
                try:
                    key = self._get_context_key(session_id, owner_id)
                    res = self.audit_logger.log_lifecycle(
                        session_id=session_id,
                        context_key=self._format_context_key(key),
                        owner_id=owner_id,
                        event_type="create",
                        operator_id=owner_id,
                        session_name=session_name,
                        operator_name=owner_name,
                        owner_name=owner_name,
                        details={"mode": self.mode},
                    )
                    if hasattr(res, "__await__"):
                        await res
                except Exception as e:
                    logger.warning(f"[ContextManager] 记录上下文创建生命周期审计日志失败: {e}")

            return ctx
        except Exception as e:
            if browser_ctx is not None:
                try:
                    res_close = browser_ctx.close()
                    if hasattr(res_close, "__await__"):
                        await res_close
                except Exception as ce:
                    logger.warning(f"[ContextManager] 上下文创建异常时回退清理失败: {ce}")
            raise e

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
        if self.audit_logger:
            self._fire_lifecycle_log(
                session_id=session_id,
                context_key=self._format_context_key(key),
                owner_id=context.owner_id,
                event_type="join",
                operator_id=owner_id,
                session_name=getattr(context, "session_name", ""),
                operator_name=getattr(context, "owner_name", ""),
                owner_name=getattr(context, "owner_name", ""),
                details={"invited_user": target_user_id},
            )
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
        if self.audit_logger:
            self._fire_lifecycle_log(
                session_id=session_id,
                context_key=self._format_context_key(target_key),
                owner_id=target_ctx.owner_id,
                event_type="switch",
                operator_id=sender_id,
                session_name=getattr(target_ctx, "session_name", ""),
                owner_name=getattr(target_ctx, "owner_name", ""),
                details={"target_owner": target_owner_id},
            )
        return True, f"已将您的操作上下文切换至用户 @{target_owner_id} 的浏览器"

    async def close_user_context(self, session_id: str, sender_id: str) -> tuple[bool, str]:
        """关闭并释放发送者所拥有的个人上下文。"""
        sender_id = str(sender_id)
        key = self._get_context_key(session_id, sender_id)

        if key not in self.contexts:
            return False, "您当前没有开启任何属于您自己的浏览器上下文"

        ctx = self.contexts.pop(key)
        try:
            if hasattr(ctx, "browser_context") and ctx.browser_context:
                res = ctx.browser_context.close()
                if hasattr(res, "__await__"):
                    await res
        except Exception as e:
            logger.warning(f"[ContextManager] 关闭用户浏览器上下文异常: {e}")

        # 清除指向此上下文的指针
        to_del = [k for k, v in self.user_active_pointer.items() if k[0] == session_id and v == sender_id]
        for k in to_del:
            del self.user_active_pointer[k]

        if self.audit_logger:
            try:
                res = self.audit_logger.log_lifecycle(
                    session_id=session_id,
                    context_key=self._format_context_key(key),
                    owner_id=ctx.owner_id,
                    event_type="close",
                    operator_id=sender_id,
                    session_name=getattr(ctx, "session_name", ""),
                    operator_name=getattr(ctx, "owner_name", "") if sender_id == ctx.owner_id else "",
                    owner_name=getattr(ctx, "owner_name", ""),
                )
                if hasattr(res, "__await__"):
                    await res
            except Exception as e:
                logger.warning(f"[ContextManager] 记录上下文关闭生命周期审计日志失败: {e}")

        return True, "已成功关闭并释放您的浏览器上下文"

    async def cleanup_idle_contexts(self) -> int:
        """检查并自动销毁超时的空闲上下文，按每个上下文的独立超时配置精准淘汰，返回销毁数量。"""
        now = time.time()
        expired_keys = []
        for k, ctx in list(self.contexts.items()):
            ctx_timeout = getattr(ctx, "idle_timeout_seconds", 0.0)
            if ctx_timeout <= 0 and self.idle_timeout_minutes > 0:
                ctx_timeout = float(self.idle_timeout_minutes * 60)

            if ctx_timeout > 0 and (now - ctx.last_active_time) > ctx_timeout:
                expired_keys.append((k, ctx_timeout))

        count = 0
        for k, ctx_timeout in expired_keys:
            ctx = self.contexts.pop(k, None)
            if ctx:
                try:
                    if hasattr(ctx, "browser_context") and ctx.browser_context:
                        res = ctx.browser_context.close()
                        if hasattr(res, "__await__"):
                            await res
                except Exception as e:
                    logger.warning(f"[ContextManager] 超时清理关闭 BrowserContext 异常: {e}")
                count += 1
                to_del = [
                    ptr for ptr, v in self.user_active_pointer.items()
                    if ptr[0] == getattr(ctx, "session_id", "") and v == getattr(ctx, "owner_id", "")
                ]
                for ptr in to_del:
                    del self.user_active_pointer[ptr]

                if self.audit_logger:
                    try:
                        res = self.audit_logger.log_lifecycle(
                            session_id=getattr(ctx, "session_id", ""),
                            context_key=self._format_context_key(k),
                            owner_id=getattr(ctx, "owner_id", ""),
                            event_type="timeout",
                            operator_id="system",
                            session_name=getattr(ctx, "session_name", ""),
                            operator_name="system",
                            owner_name=getattr(ctx, "owner_name", ""),
                            details={"idle_minutes": int(ctx_timeout // 60) if ctx_timeout % 60 == 0 else round(ctx_timeout / 60, 2)},
                        )
                        if hasattr(res, "__await__"):
                            await res
                    except Exception as e:
                        logger.warning(f"[ContextManager] 记录超时清理生命周期日志失败: {e}")

        return count

    async def get_or_create_external_context(
        self,
        plugin_name: str,
        idle_timeout_minutes: int | None = None,
        clean: bool = False,
    ) -> BrowserSessionContext:
        """为外部插件获取或创建专用 BrowserSessionContext，支持并发防重与独立超时。"""
        plugin_name = str(plugin_name or "unknown_plugin").strip()
        key = ("external", plugin_name)
        lock = self._get_creation_lock(key)

        async with lock:
            if clean and key in self.contexts:
                old_ctx = self.contexts.pop(key, None)
                if old_ctx and hasattr(old_ctx, "browser_context") and old_ctx.browser_context:
                    try:
                        res = old_ctx.browser_context.close()
                        if hasattr(res, "__await__"):
                            await res
                    except Exception as e:
                        logger.warning(f"[ContextManager] 强制重置清理旧外部上下文异常: {e}")

            if key not in self.contexts:
                timeout_sec = None
                if idle_timeout_minutes is not None:
                    timeout_sec = float(idle_timeout_minutes * 60)
                ctx = await self._create_new_context(
                    session_id=f"ext_{plugin_name}",
                    owner_id=f"plugin_{plugin_name}",
                    session_name=f"External Context [{plugin_name}]",
                    owner_name=plugin_name,
                    is_external=True,
                    plugin_name=plugin_name,
                    idle_timeout_seconds=timeout_sec,
                )
                self.contexts[key] = ctx

            ctx = self.contexts[key]
            ctx.touch()
            return ctx

    async def release_external_context(self, plugin_name: str) -> bool:
        """释放指定外部插件的专用上下文。"""
        plugin_name = str(plugin_name or "unknown_plugin").strip()
        key = ("external", plugin_name)
        lock = self._get_creation_lock(key)

        async with lock:
            ctx = self.contexts.pop(key, None)
            if not ctx:
                return False
            try:
                if hasattr(ctx, "browser_context") and ctx.browser_context:
                    res = ctx.browser_context.close()
                    if hasattr(res, "__await__"):
                        await res
            except Exception as e:
                logger.warning(f"[ContextManager] 释放外部 BrowserContext 异常: {e}")

            if self.audit_logger:
                try:
                    res = self.audit_logger.log_lifecycle(
                        session_id=getattr(ctx, "session_id", ""),
                        context_key=self._format_context_key(key),
                        owner_id=getattr(ctx, "owner_id", ""),
                        event_type="release",
                        operator_id=f"plugin_{plugin_name}",
                        session_name=getattr(ctx, "session_name", ""),
                        operator_name=plugin_name,
                        owner_name=getattr(ctx, "owner_name", ""),
                    )
                    if hasattr(res, "__await__"):
                        await res
                except Exception as e:
                    logger.warning(f"[ContextManager] 记录外部上下文释放生命周期日志失败: {e}")
            return True

    async def force_kill_context(self, context_key: str, operator_id: str) -> tuple[bool, str]:
        """强制终止指定上下文并释放底层资源。"""
        context_key = str(context_key)
        target_k = None
        target_ctx = None
        for k, ctx in list(self.contexts.items()):
            if k == context_key or self._format_context_key(k) == context_key:
                target_k = k
                target_ctx = ctx
                break

        if not target_ctx or target_k is None:
            return False, f"未找到上下文: {context_key}"

        self.contexts.pop(target_k, None)
        try:
            if hasattr(target_ctx, "browser_context") and target_ctx.browser_context:
                res = target_ctx.browser_context.close()
                if hasattr(res, "__await__"):
                    await res
        except Exception as e:
            logger.warning(f"[ContextManager] 强制终止 BrowserContext 异常: {e}")

        session_id = getattr(target_ctx, "session_id", "")
        owner_id = getattr(target_ctx, "owner_id", "")
        to_del = [
            k for k, v in self.user_active_pointer.items()
            if (k[0] == session_id and v == owner_id)
        ]
        for k in to_del:
            del self.user_active_pointer[k]

        if self.audit_logger:
            try:
                res = self.audit_logger.log_lifecycle(
                    session_id=session_id,
                    context_key=self._format_context_key(target_k),
                    owner_id=owner_id,
                    event_type="force_kill",
                    operator_id=operator_id,
                    session_name=getattr(target_ctx, "session_name", ""),
                    operator_name=operator_id,
                    owner_name=getattr(target_ctx, "owner_name", ""),
                    details={"operator": operator_id},
                )
                if hasattr(res, "__await__"):
                    await res
            except Exception as e:
                logger.warning(f"[ContextManager] 记录强制终止生命周期日志失败: {e}")

        return True, "上下文已成功强制关闭并释放资源"

    async def get_active_contexts_detail(self) -> list[dict]:
        """获取所有当前活跃的会话及其标签页明细。"""
        result = []
        for key, ctx in list(self.contexts.items()):
            key_str = self._format_context_key(key)
            pages = []
            if hasattr(ctx, "browser_context") and getattr(ctx.browser_context, "pages", None) is not None:
                bc_pages = ctx.browser_context.pages
                if isinstance(bc_pages, list):
                    pages = bc_pages
            if not pages and hasattr(ctx, "pages") and isinstance(ctx.pages, list):
                pages = ctx.pages

            cur_p = getattr(ctx, "current_page", None)
            active_url = ""
            if cur_p:
                u = getattr(cur_p, "url", "")
                active_url = str(u() if callable(u) else u) if u else ""

            tabs = []
            for idx, p in enumerate(pages):
                url_val = getattr(p, "url", "")
                url_str = str(url_val() if callable(url_val) else url_val) if url_val else ""

                title_str = ""
                try:
                    if hasattr(p, "title"):
                        if callable(p.title):
                            t_res = p.title()
                            if hasattr(t_res, "__await__"):
                                try:
                                    t_val = await asyncio.wait_for(t_res, timeout=2.0)
                                except (RuntimeError, NotImplementedError):
                                    t_val = await t_res
                                if isinstance(t_val, (str, int, float, bool)):
                                    title_str = str(t_val)
                                elif hasattr(t_val, "_mock_name") or type(t_val).__name__.endswith("Mock"):
                                    title_str = ""
                                else:
                                    title_str = str(t_val)
                            else:
                                if isinstance(t_res, (str, int, float, bool)):
                                    title_str = str(t_res)
                                elif hasattr(t_res, "_mock_name") or type(t_res).__name__.endswith("Mock"):
                                    title_str = ""
                                else:
                                    title_str = str(t_res)
                        else:
                            if isinstance(p.title, (str, int, float, bool)):
                                title_str = str(p.title)
                            elif hasattr(p.title, "_mock_name") or type(p.title).__name__.endswith("Mock"):
                                title_str = ""
                            else:
                                title_str = str(p.title)
                except Exception as e:
                    logger.debug(f"[ContextManager] 获取标签页标题失败降级: {e}")
                    title_str = ""

                tabs.append({
                    "index": idx,
                    "url": url_str,
                    "title": title_str,
                    "is_active": (p == cur_p),
                })

            item = {
                "context_key": key_str,
                "session_id": getattr(ctx, "session_id", ""),
                "session_name": getattr(ctx, "session_name", ""),
                "owner_id": getattr(ctx, "owner_id", ""),
                "owner_name": getattr(ctx, "owner_name", ""),
                "allowed_users": list(getattr(ctx, "allowed_users", set())),
                "created_time": getattr(ctx, "created_time", getattr(ctx, "last_active_time", 0.0)),
                "last_active_time": getattr(ctx, "last_active_time", 0.0),
                "tab_count": len(pages),
                "active_tab_url": active_url,
                "tabs": tabs,
            }
            result.append(item)
        return result
