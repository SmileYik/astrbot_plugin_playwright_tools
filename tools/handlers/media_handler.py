import asyncio
import base64
import os
import time
import logging
import traceback
from pathlib import Path
from ...core.context_manager import ContextManager
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

class MediaHandler:
    """媒体与截图双重熔断处理器。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        allow_screenshot_to_ai: bool = False,
        download_dir: str = "data/downloads",
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger
        self.allow_screenshot_to_ai = allow_screenshot_to_ai
        self.download_dir = download_dir
        try:
            Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _save_or_encode(self, image_bytes: bytes, target: str, note: str = "") -> str:
        if target.lower() == "ai":
            b64_str = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64_str}"
        file_name = f"screenshot_{int(time.time() * 1000)}.png"
        save_path = os.path.join(self.download_dir, file_name)
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        res = f"[IMAGE_PATH:{save_path}]"
        if note:
            res = f"{res}\n{note}"
        return res

    async def screenshot_viewport(
        self,
        session_id: str,
        sender_id: str,
        target: str = "chat",
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """截取当前视口屏幕。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "截图失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "screenshot")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_viewport", url, {"target": target}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"截图失败: {reason}"

        if target.lower() == "ai" and not self.allow_screenshot_to_ai:
            deny_msg = "拒绝操作：管理员配置中未开启将截图发送给大模型（allow_screenshot_to_ai=False）。如需向用户展示，请使用 target='chat'。"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_viewport", url, {"target": target}, deny_msg, is_permitted=False, deny_reason=deny_msg,
                session_name=session_name, sender_name=sender_name
            )
            return deny_msg

        try:
            image_bytes = await page.screenshot(full_page=False)
            res = self._save_or_encode(image_bytes, target)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_viewport", url, {"target": target}, "视口截图生成成功", is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            logger.error(f"[PlaywrightTool] screenshot_viewport 异常: {e}\n{traceback.format_exc()}")
            return f"视口截图异常: {str(e)}"

    async def screenshot_full(
        self,
        session_id: str,
        sender_id: str,
        target: str = "chat",
        max_height_px: int = 8000,
        timeout_sec: int = 15,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """截取长截图，支持最大像素与超时双重熔断截断。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "长截图失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "screenshot")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_full", url, {"target": target}, reason, is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"长截图失败: {reason}"

        if target.lower() == "ai" and not self.allow_screenshot_to_ai:
            deny_msg = "拒绝操作：管理员配置中未开启将截图发送给大模型（allow_screenshot_to_ai=False）。"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_full", url, {"target": target}, deny_msg, is_permitted=False, deny_reason=deny_msg,
                session_name=session_name, sender_name=sender_name
            )
            return deny_msg

        # 检查高度熔断
        try:
            scroll_height = await page.evaluate(
                "Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement ? document.documentElement.scrollHeight : 0, 0)"
            )
        except Exception:
            scroll_height = 0

        is_clipped = False
        clip_dict = None
        note = ""
        if scroll_height and scroll_height > max_height_px:
            is_clipped = True
            viewport_width = 1280
            if hasattr(page, "viewport_size") and isinstance(page.viewport_size, dict):
                viewport_width = page.viewport_size.get("width", 1280)
            clip_dict = {"x": 0, "y": 0, "width": viewport_width, "height": max_height_px}
            note = f"（页面高度 {scroll_height}px 超过最大限制 {max_height_px}px，已自动截断）"

        try:
            async def do_screenshot():
                if is_clipped:
                    return await page.screenshot(clip=clip_dict, full_page=False)
                return await page.screenshot(full_page=True)

            shot_coro = do_screenshot()
            if timeout_sec and timeout_sec > 0:
                image_bytes = await asyncio.wait_for(shot_coro, timeout=float(timeout_sec))
            else:
                image_bytes = await shot_coro
        except asyncio.TimeoutError:
            try:
                shot_coro.close()
            except Exception:
                pass
            try:
                image_bytes = await page.screenshot(full_page=False)
                note = f"（长截图耗时超过 {timeout_sec} 秒，已自动截断并降级为当前视口截图）"
            except Exception as fb_err:
                return f"长截图超时且降级失败: {str(fb_err)}"
        except Exception as e:
            logger.error(f"[PlaywrightTool] screenshot_full 异常: {e}\n{traceback.format_exc()}")
            try:
                shot_coro.close()
            except Exception:
                pass
            return f"长截图异常: {str(e)}"

        res = self._save_or_encode(image_bytes, target, note)
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "screenshot_full", url, {"target": target, "max_height_px": max_height_px}, "长截图生成成功", is_permitted=True,
            session_name=session_name, sender_name=sender_name
        )
        return res

    async def download_file(
        self,
        session_id: str,
        sender_id: str,
        ref: int,
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """点击指定链接/按钮触发文件下载。"""
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "下载失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "download")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "download_file", url, {"ref": ref}, reason,
                is_permitted=False, deny_reason=reason,
                session_name=session_name, sender_name=sender_name
            )
            return f"下载失败: {reason}"

        if ref not in ctx.ref_map:
            return f"下载失败: 无效的元素引用 [{ref}]"

        try:
            async with page.expect_download(timeout=30000) as download_info:
                script = f"""
                (() => {{
                    const target = document.querySelector('[data-astr-ref="{ref}"]');
                    if (target) {{ target.click(); return true; }}
                    return false;
                }})()
                """
                await page.evaluate(script)

            download = await download_info.value
            target_file_path = os.path.join(self.download_dir, download.suggested_filename)
            await download.save_as(target_file_path)

            res = f"[FILE_PATH:{target_file_path}]\n已成功下载文件: {download.suggested_filename}"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "download_file", url, {"ref": ref}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name
            )
            return res
        except Exception as e:
            logger.error(f"[PlaywrightTool] download_file 异常: {e}\n{traceback.format_exc()}")
            return f"下载异常: {str(e)}"
