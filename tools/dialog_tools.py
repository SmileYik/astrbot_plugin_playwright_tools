from core.context_manager import ContextManager
from core.security_manager import SecurityManager
from core.audit_logger import AuditLogger

class DialogTools:
    """浏览器弹窗控制工具。"""

    def __init__(
        self,
        context_mgr: ContextManager,
        security_mgr: SecurityManager,
        audit_logger: AuditLogger,
    ):
        self.context_mgr = context_mgr
        self.security_mgr = security_mgr
        self.audit_logger = audit_logger

    async def handle_dialog(
        self,
        session_id: str,
        sender_id: str,
        action: str = "accept",
        prompt_text: str | None = None,
    ) -> str:
        """预先配置下一次触发的浏览器原生弹窗 (alert/confirm/prompt) 响应策略。

        Args:
            action(string): 响应动作 ('accept' 确认, 'dismiss' 取消/关闭)
            prompt_text(string): 若为 prompt 弹窗，需要输入的文本值
        """
        ctx, hint = await self.context_mgr.resolve_context(session_id, sender_id)
        if ctx is None:
            return "配置失败: 无法获取浏览器上下文"

        ctx.dialog_action = {
            "action": action.lower(),
            "prompt_text": prompt_text,
        }
        res = f"{hint}\n已预设下一次弹窗处理策略: 动作={action}" + (f", 输入='{prompt_text}'" if prompt_text else "")
        await self.audit_logger.log_action(
            session_id, f"{session_id}:{ctx.owner_id}", sender_id,
            "handle_dialog", "", {"action": action, "prompt_text": prompt_text},
            res, is_permitted=True
        )
        return res.strip()
