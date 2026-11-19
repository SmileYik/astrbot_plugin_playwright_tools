import base64
import os
import time
from pathlib import Path
from core.context_manager import ContextManager
from core.security_manager import SecurityManager
from core.audit_logger import AuditLogger

class MediaTools:
    """媒体与文件处理工具集 (截图、下载)。"""

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

    async def take_screenshot(
        self, session_id: str, sender_id: str, target: str = "chat"
    ) -> str:
        """截取当前网页屏幕。

        Args:
            target(string): 截图交付目标 ('chat' 发送至聊天会话，'ai' 返回 base64 给大模型视觉分析)
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "截图失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "screenshot")
        if not allowed:
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "take_screenshot", url, {"target": target}, reason, is_permitted=False, deny_reason=reason
            )
            return f"截图失败: {reason}"

        if target.lower() == "ai" and not self.allow_screenshot_to_ai:
            deny_msg = "拒绝操作：管理员配置中未开启将截图发送给大模型（allow_screenshot_to_ai=False）。如需向用户展示，请使用 target='chat'。"
            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "take_screenshot", url, {"target": target}, deny_msg, is_permitted=False, deny_reason=deny_msg
            )
            return deny_msg

        try:
            image_bytes = await page.screenshot(full_page=False)
            if target.lower() == "ai":
                b64_str = base64.b64encode(image_bytes).decode("utf-8")
                res = f"data:image/png;base64,{b64_str}"
            else:
                # 保存至本地供聊天发送
                file_name = f"screenshot_{int(time.time() * 1000)}.png"
                save_path = os.path.join(self.download_dir, file_name)
                with open(save_path, "wb") as f:
                    f.write(image_bytes)
                res = f"[IMAGE_PATH:{save_path}]"

            await self.audit_logger.log_action(
                session_id, f"{session_id}:{ctx.owner_id}", sender_id,
                "take_screenshot", url, {"target": target}, "截图生成成功", is_permitted=True
            )
            return res
        except Exception as e:
            err_msg = f"截图异常: {str(e)}"
            return err_msg

    async def download_file(self, session_id: str, sender_id: str, ref: int) -> str:
        """点击指定链接/按钮触发文件下载。

        Args:
            ref(number): 下载链接或按钮的 Ref ID
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "下载失败: 无法获取浏览器上下文"

        page = ctx.current_page
        url = getattr(page, "url", "")
        allowed, reason = self.security_mgr.check_permission(ctx.owner_id, url, "download")
        if not allowed:
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
                "download_file", url, {"ref": ref}, res, is_permitted=True
            )
            return res
        except Exception as e:
            return f"下载异常: {str(e)}"
