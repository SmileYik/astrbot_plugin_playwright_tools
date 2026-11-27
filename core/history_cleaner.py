import asyncio
from typing import Any
from astrbot.api import logger

PLUGIN_TOOLS = {"pw_page", "pw_read", "pw_interact", "pw_media"}
DELETE_PLACEHOLDER = "[该历史工具调用结果已按策略清理]"
MERGE_PLACEHOLDER = "[已并入本轮浏览摘要]"
SUMMARY_PREFIX = "[历史浏览摘要]"


class HistoryCleaner:
    """管理大模型上下文中的本插件工具历史记录，基于高低双水位线实现直接清理或副 AI 压缩。"""

    def __init__(self, context: Any, config: dict[str, Any] | None = None):
        self.context = context
        cfg = config or {}
        hc_cfg = cfg.get("history_cleanup", {}) if isinstance(cfg.get("history_cleanup"), dict) else {}

        self.enable_cleanup = bool(hc_cfg.get("enable_cleanup", cfg.get("enable_cleanup", False)))
        self.high_watermark = int(hc_cfg.get("high_watermark", cfg.get("high_watermark", 8000)))
        self.low_watermark = int(hc_cfg.get("low_watermark", cfg.get("low_watermark", 3000)))
        if self.low_watermark >= self.high_watermark:
            corrected_low = max(1, int(self.high_watermark * 0.5))
            logger.warning(
                f"[HistoryCleaner] 低水位 ({self.low_watermark}) >= 高水位 ({self.high_watermark})，自动调整为高水位的 50%: {corrected_low}"
            )
            self.low_watermark = corrected_low

        self.cleanup_strategy = str(hc_cfg.get("cleanup_strategy", cfg.get("cleanup_strategy", "delete"))).strip().lower()
        self.compress_provider_id = str(hc_cfg.get("compress_provider_id", cfg.get("compress_provider_id", ""))).strip()
        self.compress_max_input_chars = int(hc_cfg.get("compress_max_input_chars", cfg.get("compress_max_input_chars", 0)))
        self.compress_prompt = str(
            hc_cfg.get(
                "compress_prompt",
                cfg.get(
                    "compress_prompt",
                    "你是一个精炼的内容总结器。请对以下浏览器历史操作及网页正文进行结构化提炼：保留核心事实、关键结论、数据指标及必要链接，剔除冗余修饰与排版，输出不超过 300 字的紧凑摘要。",
                ),
            )
        ).strip()
        self.compress_use_persona = bool(hc_cfg.get("compress_use_persona", cfg.get("compress_use_persona", False)))
        self.compress_persona_id = str(hc_cfg.get("compress_persona_id", cfg.get("compress_persona_id", ""))).strip()

    def is_plugin_tool(self, name: str | None) -> bool:
        """判断工具名称是否属于本插件的四大核心工具。"""
        if not name:
            return False
        return str(name).strip() in PLUGIN_TOOLS

    def is_processed_tool(self, content: Any) -> bool:
        """检查工具消息内容是否已经被处理（已清理或已压缩）。"""
        if not content:
            return False
        text = str(content)
        return (
            text.startswith(DELETE_PLACEHOLDER)
            or text.startswith(MERGE_PLACEHOLDER)
            or text.startswith(SUMMARY_PREFIX)
        )

    def _get_role(self, msg: Any) -> str:
        if isinstance(msg, dict):
            return str(msg.get("role", "")).lower()
        return str(getattr(msg, "role", "")).lower()

    def _get_content(self, msg: Any) -> str:
        if isinstance(msg, dict):
            c = msg.get("content", "")
        else:
            c = getattr(msg, "content", "")
        if c is None:
            return ""
        if isinstance(c, str):
            return c
        return str(c)

    def _set_content(self, msg: Any, text: str) -> None:
        if isinstance(msg, dict):
            msg["content"] = text
        else:
            setattr(msg, "content", text)

    def _get_tool_call_id(self, msg: Any) -> str:
        if isinstance(msg, dict):
            return str(msg.get("tool_call_id", "") or "")
        return str(getattr(msg, "tool_call_id", "") or "")

    def _get_tool_name(self, msg: Any, id_to_name: dict[str, str]) -> str:
        if isinstance(msg, dict):
            name = msg.get("name")
        else:
            name = getattr(msg, "name", None)
        if name:
            return str(name)
        call_id = self._get_tool_call_id(msg)
        return id_to_name.get(call_id, "")

    def _build_call_id_map(self, contexts: list[Any]) -> dict[str, str]:
        """建立 tool_call_id 到工具函数名的映射表。"""
        id_map: dict[str, str] = {}
        for msg in contexts:
            tool_calls = None
            if isinstance(msg, dict):
                tool_calls = msg.get("tool_calls")
            else:
                tool_calls = getattr(msg, "tool_calls", None)

            if not tool_calls or not isinstance(tool_calls, list):
                continue

            for tc in tool_calls:
                call_id = ""
                fn_name = ""
                if isinstance(tc, dict):
                    call_id = str(tc.get("id", ""))
                    fn = tc.get("function")
                    if isinstance(fn, dict):
                        fn_name = str(fn.get("name", ""))
                else:
                    call_id = str(getattr(tc, "id", ""))
                    fn = getattr(tc, "function", None)
                    if fn:
                        if isinstance(fn, dict):
                            fn_name = str(fn.get("name", ""))
                        else:
                            fn_name = str(getattr(fn, "name", ""))
                if call_id and fn_name:
                    id_map[call_id] = fn_name
        return id_map

    def calculate_uncompressed_chars(self, contexts: list[Any]) -> int:
        """统计上下文中属于本插件、且尚未被清理/压缩的工具消息总字符数。"""
        if not contexts:
            return 0
        id_map = self._build_call_id_map(contexts)
        total_chars = 0
        for msg in contexts:
            if self._get_role(msg) != "tool":
                continue
            name = self._get_tool_name(msg, id_map)
            if not self.is_plugin_tool(name):
                continue
            content = self._get_content(msg)
            if self.is_processed_tool(content):
                continue
            total_chars += len(content)
        return total_chars

    def group_tool_calls(self, contexts: list[Any]) -> list[list[int]]:
        """按轮次边界将连续属于本插件的未处理/可处理工具消息聚合为调用组。"""
        if not contexts:
            return []
        id_map = self._build_call_id_map(contexts)
        groups: list[list[int]] = []
        current_group: list[int] = []

        for idx, msg in enumerate(contexts):
            role = self._get_role(msg)
            if role == "tool":
                name = self._get_tool_name(msg, id_map)
                if self.is_plugin_tool(name):
                    current_group.append(idx)
                else:
                    if current_group:
                        groups.append(current_group)
                        current_group = []
            else:
                if current_group:
                    groups.append(current_group)
                    current_group = []

        if current_group:
            groups.append(current_group)

        return groups

    async def process_contexts(self, event: Any, req: Any) -> bool:
        """执行上下文水位检测与消减。"""
        if not self.enable_cleanup:
            return False

        contexts = getattr(req, "contexts", None)
        if not contexts or not isinstance(contexts, list):
            return False

        uncompressed_chars = self.calculate_uncompressed_chars(contexts)
        if uncompressed_chars <= self.high_watermark:
            return False

        groups = self.group_tool_calls(contexts)
        if not groups:
            return False

        changed = False
        # 从旧到新 (FIFO) 逐组处理
        for group in groups:
            if uncompressed_chars <= self.low_watermark:
                break

            # 检查组内是否有未处理的内容
            group_has_unprocessed = any(
                not self.is_processed_tool(self._get_content(contexts[idx])) for idx in group
            )
            if not group_has_unprocessed:
                continue

            if self.cleanup_strategy == "compress":
                # 副 AI 压缩模式
                success = await self._compress_tool_group(group, contexts, event)
                if success:
                    changed = True
                    uncompressed_chars = self.calculate_uncompressed_chars(contexts)
                    continue
                # 压缩失败时平滑降级为直接删除模式
                logger.warning("[HistoryCleaner] 副 AI 压缩失败，自动降级为直接删除占位策略")

            # 直接删除模式
            for idx in group:
                msg = contexts[idx]
                content = self._get_content(msg)
                if not self.is_processed_tool(content):
                    uncompressed_chars -= len(content)
                    self._set_content(msg, DELETE_PLACEHOLDER)
                    changed = True

        return changed

    def _prepare_compress_input(self, tool_group_contents: list[str]) -> str:
        """拼装单轮工具组文本并根据 compress_max_input_chars 限制处理。"""
        full_text = "\n".join(tool_group_contents)
        if self.compress_max_input_chars > 0 and len(full_text) > self.compress_max_input_chars:
            full_text = full_text[: self.compress_max_input_chars] + "\n...[超出副 AI 最大输入限制，已截断]"
        return full_text

    async def _resolve_system_prompt(self) -> str:
        """组装副 AI 系统提示词（包含基础压缩指令与人设面具融合）。"""
        base_prompt = self.compress_prompt
        if not self.compress_use_persona:
            return base_prompt

        persona_prompt = ""
        persona_mgr = getattr(self.context, "persona_manager", None)
        if persona_mgr:
            pid = self.compress_persona_id
            if not pid:
                pid = getattr(persona_mgr, "default_persona", "")
            if pid and hasattr(persona_mgr, "get_persona"):
                try:
                    res = persona_mgr.get_persona(pid)
                    if hasattr(res, "__await__"):
                        p_obj = await res
                    else:
                        p_obj = res
                    if p_obj:
                        if isinstance(p_obj, dict):
                            persona_prompt = str(p_obj.get("system_prompt", ""))
                        else:
                            persona_prompt = str(getattr(p_obj, "system_prompt", ""))
                except Exception as e:
                    logger.warning(f"[HistoryCleaner] 获取人设面具 '{pid}' 失败: {e}")

        if persona_prompt:
            return f"{persona_prompt}\n\n{base_prompt}"
        return base_prompt

    async def _resolve_compress_provider(self, event: Any) -> Any:
        """获取负责执行压缩任务的 Provider 实例。"""
        prov = None
        if self.compress_provider_id and hasattr(self.context, "get_provider_by_id"):
            try:
                prov = self.context.get_provider_by_id(self.compress_provider_id)
            except Exception as e:
                logger.warning(f"[HistoryCleaner] 获取指定提供商 '{self.compress_provider_id}' 失败: {e}")

        if not prov and hasattr(self.context, "get_using_provider_async"):
            umo = getattr(event, "unified_msg_origin", None) if event else None
            try:
                prov = await self.context.get_using_provider_async(umo=umo)
            except Exception as e:
                logger.warning(f"[HistoryCleaner] 获取会话默认提供商失败: {e}")

        if not prov and hasattr(self.context, "get_using_provider"):
            try:
                umo = getattr(event, "unified_msg_origin", None) if event else None
                prov = self.context.get_using_provider(umo=umo)
            except Exception:
                pass

        return prov

    async def _compress_tool_group(self, group: list[int], contexts: list[Any], event: Any) -> bool:
        """调用副 AI 对单组工具调用进行结构化总结，并原位写回摘要与占位符。"""
        try:
            id_map = self._build_call_id_map(contexts)
            contents_to_compress: list[str] = []
            for idx in group:
                msg = contexts[idx]
                tool_name = self._get_tool_name(msg, id_map)
                c = self._get_content(msg)
                contents_to_compress.append(f"【工具: {tool_name}】\n{c}")

            prompt_text = self._prepare_compress_input(contents_to_compress)
            provider = await self._resolve_compress_provider(event)
            if not provider:
                logger.warning("[HistoryCleaner] 未找到可用的副 AI 提供商，无法执行压缩")
                return False

            sys_prompt = await self._resolve_system_prompt()
            res = provider.text_chat(prompt=prompt_text, system_prompt=sys_prompt)
            if hasattr(res, "__await__"):
                llm_resp = await res
            else:
                llm_resp = res

            summary = ""
            if hasattr(llm_resp, "completion_text"):
                summary = str(llm_resp.completion_text).strip()
            elif isinstance(llm_resp, dict):
                summary = str(llm_resp.get("completion_text", "")).strip()
            else:
                summary = str(llm_resp).strip()

            if not summary:
                logger.warning("[HistoryCleaner] 副 AI 压缩返回空文本")
                return False

            # 前 N-1 个写入合并占位符，最后一个写入最终结构化摘要
            for idx in group[:-1]:
                self._set_content(contexts[idx], MERGE_PLACEHOLDER)
            self._set_content(contexts[group[-1]], f"{SUMMARY_PREFIX}:\n{summary}")
            return True
        except Exception as e:
            logger.warning(f"[HistoryCleaner] 副 AI 压缩调用发生异常: {e}")
            return False
