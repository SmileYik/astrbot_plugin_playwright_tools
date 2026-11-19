import fnmatch
from urllib.parse import urlparse

class SecurityManager:
    """权限与白名单守卫管理器，负责鉴权、通配符域名匹配及顶层页面导航保护。"""

    def __init__(
        self,
        admin_only: bool = False,
        admin_uids: list[str] | None = None,
        whitelist_rules: list[dict] | None = None,
        admin_bypass: bool = True,
    ):
        self.admin_only = admin_only
        self.admin_uids = set(admin_uids or [])
        self.whitelist_rules = whitelist_rules or []
        self.admin_bypass = admin_bypass

    def is_admin(self, user_id: str) -> bool:
        """检查用户是否为管理员。"""
        return str(user_id) in self.admin_uids

    def _extract_hostname(self, url: str) -> str:
        """提取干净的小写 hostname（去除端口）。"""
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            return host.lower()
        except Exception:
            return ""

    def _normalize_pattern(self, pat: str) -> str:
        """标准化域名规则，去除协议头与路径部分。"""
        pat = pat.strip().lower()
        if pat.startswith("http://"):
            pat = pat[7:]
        elif pat.startswith("https://"):
            pat = pat[8:]
        elif pat.startswith("http*://"):
            pat = pat[8:]
        pat = pat.split("/")[0]
        # 去除端口通配
        if ":" in pat and not pat.endswith(":*"):
            pat = pat.split(":")[0]
        return pat

    def _is_domain_match(self, host: str, domain_pattern: str) -> bool:
        """检查域名是否命中规则，支持 *.example.com 匹配 apex 根域名 example.com。"""
        norm_pat = self._normalize_pattern(domain_pattern)
        if fnmatch.fnmatch(host, norm_pat):
            return True
        if norm_pat.startswith("*.") and host == norm_pat[2:]:
            return True
        return False

    def is_url_allowed_navigation(self, user_id: str, target_url: str) -> tuple[bool, str]:
        """校验目标 URL 是否允许作为顶层页面进行导航访问。"""
        parsed = urlparse(target_url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"拒绝导航：不支持协议 '{parsed.scheme}'，仅允许访问 http 与 https 网页"

        if self.admin_bypass and self.is_admin(user_id):
            return True, ""

        if self.admin_only:
            if not self.is_admin(user_id):
                return False, "拒绝操作：当前插件已配置为仅管理员可用"
            return True, ""

        host = self._extract_hostname(target_url)
        if not host:
            return False, "拒绝导航：无法解析有效的主机域名"

        # 匹配白名单规则
        for rule in self.whitelist_rules:
            domain_pat = rule.get("domain", "")
            if self._is_domain_match(host, domain_pat):
                return True, ""

        return False, f"拒绝导航：目标域名 '{host}' 未在白名单规则中"

    def check_permission(self, user_id: str, url: str, action: str) -> tuple[bool, str]:
        """校验发送者是否对指定 URL 具备特定操作行为的权限。"""
        if self.admin_bypass and self.is_admin(user_id):
            return True, ""

        if self.admin_only:
            if not self.is_admin(user_id):
                return False, "拒绝操作：当前插件已配置为仅管理员可用"
            return True, ""

        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"拒绝操作：不支持协议 '{parsed.scheme}'"

        host = self._extract_hostname(url)
        if not host:
            return False, "拒绝操作：无法解析目标域名"

        matched_rule = None
        for rule in self.whitelist_rules:
            domain_pat = rule.get("domain", "")
            if self._is_domain_match(host, domain_pat):
                matched_rule = rule
                break

        if not matched_rule:
            return False, f"拒绝操作：域名 '{host}' 未在白名单中"

        allowed_actions = set(matched_rule.get("allowed_actions", []))
        if action not in allowed_actions:
            return False, f"拒绝操作：域名 '{host}' 未被授予 '{action}' 操作权限"

        return True, ""
