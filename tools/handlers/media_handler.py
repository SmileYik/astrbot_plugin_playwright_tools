import asyncio
import base64
import os
import time
import traceback
import uuid
from pathlib import Path
from ...core.context_manager import ContextManager
from ...core.security_manager import SecurityManager
from ...core.audit_logger import AuditLogger

from astrbot.api import logger

class MediaHandler:
    """媒体与截图双重熔断处理器。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
        allow_screenshot_to_ai: bool = False,
        download_dir: str = "data/plugin_data/astrbot_plugin_playwright_tools/downloads",
        audit_save_screenshots: bool = True,
        audit_screenshots_dir: str = "data/plugin_data/astrbot_plugin_playwright_tools/audit_screenshots",
        screenshot_format: str = "png",
        screenshot_quality: int = 80,
        screenshot_dir: str = "data/plugin_data/astrbot_plugin_playwright_tools/screenshots",
        file_retention_days: int = 7,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger
        self.allow_screenshot_to_ai = allow_screenshot_to_ai
        self.download_dir = download_dir
        self.audit_save_screenshots = audit_save_screenshots
        self.audit_screenshots_dir = audit_screenshots_dir
        self.screenshot_format = str(screenshot_format or "png").strip().lower()
        try:
            self.screenshot_quality = max(1, min(100, int(screenshot_quality)))
        except (ValueError, TypeError):
            self.screenshot_quality = 80
        self.screenshot_dir = screenshot_dir
        try:
            self.file_retention_days = int(file_retention_days)
        except (ValueError, TypeError):
            self.file_retention_days = 7

        try:
            Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            Path(self.audit_screenshots_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    async def _resolve_context(
        self, session_id: str, sender_id: str, session_name: str = "", sender_name: str = ""
    ):
        try:
            return await self.context_mgr.resolve_context(
                session_id, sender_id, session_name=session_name, sender_name=sender_name
            )
        except TypeError:
            return await self.context_mgr.resolve_context(session_id, sender_id)

    def _is_jpeg(self) -> bool:
        return self.screenshot_format in ("jpeg", "jpg")

    def _get_screenshot_options(self) -> dict:
        if self._is_jpeg():
            return {
                "type": "jpeg",
                "quality": self.screenshot_quality,
            }
        return {"type": "png"}

    def _save_or_encode(self, image_bytes: bytes, target: str, note: str = "") -> str:
        is_jpeg = self._is_jpeg()
        if target.lower() == "ai":
            mime = "image/jpeg" if is_jpeg else "image/png"
            b64_str = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:{mime};base64,{b64_str}"
        ext = ".jpg" if is_jpeg else ".png"
        file_name = f"screenshot_{int(time.time() * 1000)}{ext}"
        save_path = os.path.join(self.screenshot_dir, file_name)
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        res = f"[IMAGE_PATH:{save_path}]"
        if note:
            res = f"{res}\n{note}"
        return res

    async def cleanup_expired_files(self) -> int:
        """被动清理过期文件（保留天数超过 file_retention_days 的下载与截图）。"""
        if self.file_retention_days <= 0:
            return 0

        now = time.time()
        cutoff = now - float(self.file_retention_days) * 86400.0
        deleted_count = 0

        target_dirs = []
        seen_dirs = set()
        for d in (self.download_dir, self.screenshot_dir, self.audit_screenshots_dir):
            if d:
                try:
                    abs_d = os.path.abspath(d)
                except Exception:
                    abs_d = d
                if abs_d not in seen_dirs:
                    seen_dirs.add(abs_d)
                    target_dirs.append(abs_d)

        for dir_path in target_dirs:
            if not os.path.exists(dir_path):
                continue
            try:
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file():
                                if entry.stat().st_mtime < cutoff:
                                    try:
                                        os.remove(entry.path)
                                        deleted_count += 1
                                    except OSError as rem_err:
                                        logger.warning(f"[PlaywrightTool] 删除过期文件失败 {entry.path}: {rem_err}")
                        except OSError:
                            pass
            except OSError as dir_err:
                logger.warning(f"[PlaywrightTool] 扫描目录失败 {dir_path}: {dir_err}")

        return deleted_count

    async def screenshot_viewport(
        self,
        session_id: str,
        sender_id: str,
        target: str = "chat",
        session_name: str = "",
        sender_name: str = "",
    ) -> str:
        """截取当前视口屏幕。"""
        try:
            await self.cleanup_expired_files()
        except Exception as clean_err:
            logger.warning(f"[PlaywrightTool] 被动清理过期文件失败: {clean_err}")

        ctx, hint = await self._resolve_context(session_id, sender_id, session_name=session_name, sender_name=sender_name)
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
            shot_opts = self._get_screenshot_options()
            image_bytes = await page.screenshot(full_page=False, **shot_opts)
            res = self._save_or_encode(image_bytes, target)
            screenshot_path = ""
            if self.audit_save_screenshots:
                try:
                    audit_dir = Path(self.audit_screenshots_dir)
                    audit_dir.mkdir(parents=True, exist_ok=True)
                    ext = ".jpg" if self._is_jpeg() else ".png"
                    shot_name = f"shot_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{ext}"
                    shot_file = audit_dir / shot_name
                    with open(shot_file, "wb") as f:
                        f.write(image_bytes)
                    screenshot_path = str(Path(self.audit_screenshots_dir) / shot_name).replace("\\", "/")
                except Exception as shot_err:
                    logger.warning(f"[PlaywrightTool] 保存视口截图审计文件失败: {shot_err}")
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_viewport", url, {"target": target}, res, is_permitted=True,
                session_name=session_name, sender_name=sender_name,
                screenshot_path=screenshot_path
            )
            return res
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] screenshot_viewport 异常: {e}\n{tb_str}")
            err_msg = f"视口截图异常: {str(e)}"
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_viewport", url, {"target": target}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

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
        try:
            await self.cleanup_expired_files()
        except Exception as clean_err:
            logger.warning(f"[PlaywrightTool] 被动清理过期文件失败: {clean_err}")

        ctx, hint = await self._resolve_context(session_id, sender_id, session_name=session_name, sender_name=sender_name)
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

        shot_opts = self._get_screenshot_options()
        try:
            async def do_screenshot():
                if is_clipped:
                    return await page.screenshot(clip=clip_dict, full_page=False, **shot_opts)
                return await page.screenshot(full_page=True, **shot_opts)

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
                image_bytes = await page.screenshot(full_page=False, **shot_opts)
                note = f"（长截图耗时超过 {timeout_sec} 秒，已自动截断并降级为当前视口截图）"
            except Exception as fb_err:
                return f"长截图超时且降级失败: {str(fb_err)}"
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] screenshot_full 异常: {e}\n{tb_str}")
            try:
                shot_coro.close()
            except Exception:
                pass
            err_msg = f"长截图异常: {str(e)}"
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "screenshot_full", url, {"target": target, "max_height_px": max_height_px}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg

        res = self._save_or_encode(image_bytes, target, note)
        screenshot_path = ""
        if self.audit_save_screenshots:
            try:
                audit_dir = Path(self.audit_screenshots_dir)
                audit_dir.mkdir(parents=True, exist_ok=True)
                ext = ".jpg" if self._is_jpeg() else ".png"
                shot_name = f"shot_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{ext}"
                shot_file = audit_dir / shot_name
                with open(shot_file, "wb") as f:
                    f.write(image_bytes)
                screenshot_path = str(Path(self.audit_screenshots_dir) / shot_name).replace("\\", "/")
            except Exception as shot_err:
                logger.warning(f"[PlaywrightTool] 保存长截图审计文件失败: {shot_err}")
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "screenshot_full", url, {"target": target, "max_height_px": max_height_px}, res, is_permitted=True,
            session_name=session_name, sender_name=sender_name,
            screenshot_path=screenshot_path
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
        try:
            await self.cleanup_expired_files()
        except Exception as clean_err:
            logger.warning(f"[PlaywrightTool] 被动清理过期文件失败: {clean_err}")

        ctx, hint = await self._resolve_context(session_id, sender_id, session_name=session_name, sender_name=sender_name)
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
            tb_str = traceback.format_exc()
            logger.error(f"[PlaywrightTool] download_file 异常: {e}\n{tb_str}")
            err_msg = f"下载异常: {str(e)}"
            full_error = f"{type(e).__name__}: {str(e)}\n\n{tb_str}" if tb_str else str(e)
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "download_file", url, {"ref": ref}, err_msg, is_permitted=True,
                is_error=True, error_message=full_error,
                session_name=session_name, sender_name=sender_name
            )
            return err_msg
