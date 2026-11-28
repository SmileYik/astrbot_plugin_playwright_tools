from .base import BrowserAdapterBase
from .camoufox_adapter import CamoufoxAdapter
from .playwright_adapter import PlaywrightAdapter


class AdapterFactory:
    """浏览器适配器工厂，根据配置构建对应的适配器实例。"""

    @staticmethod
    def create(config: dict | None = None) -> BrowserAdapterBase:
        config = config or {}
        browser_cfg = (
            config.get("browser", config)
            if isinstance(config.get("browser"), dict)
            else config
        )
        adapter_type = str(browser_cfg.get("browser_adapter", "camoufox")).lower()
        headless = bool(browser_cfg.get("browser_headless", True))
        user_agent = str(browser_cfg.get("browser_user_agent", "") or "")
        window_width = int(browser_cfg.get("browser_window_width", 1280))
        window_height = int(browser_cfg.get("browser_window_height", 800))
        browser_executable_path = str(
            browser_cfg.get("browser_executable_path", "") or ""
        ).strip()

        if adapter_type == "playwright":
            browser_type = str(
                browser_cfg.get("playwright_browser_type", "chromium")
            ).lower()
            if browser_type == "custom":
                if not browser_executable_path:
                    raise ValueError(
                        "Playwright 原生浏览器类型选择'其他'时，必须指定可执行文件路径 (browser_executable_path)！"
                    )
                browser_type = "chromium"
            return PlaywrightAdapter(
                browser_type=browser_type,
                headless=headless,
                user_agent=user_agent,
                window_width=window_width,
                window_height=window_height,
                executable_path=browser_executable_path,
            )
        elif adapter_type == "camoufox":
            geoip = bool(browser_cfg.get("camoufox_geoip", False))
            return CamoufoxAdapter(
                headless=headless,
                geoip=geoip,
                user_agent=user_agent,
                window_width=window_width,
                window_height=window_height,
            )
        else:
            raise ValueError(f"不支持的浏览器适配器类型: {adapter_type}")
