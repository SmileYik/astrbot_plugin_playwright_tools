from .base import BrowserAdapterBase
from .camoufox_adapter import CamoufoxAdapter
from .playwright_adapter import PlaywrightAdapter


class AdapterFactory:
    """浏览器适配器工厂，根据配置构建对应的适配器实例。"""

    @staticmethod
    def create(config: dict | None = None) -> BrowserAdapterBase:
        config = config or {}
        adapter_type = str(config.get("browser_adapter", "camoufox")).lower()
        headless = bool(config.get("browser_headless", True))
        user_agent = str(config.get("browser_user_agent", "") or "")
        window_width = int(config.get("browser_window_width", 1280))
        window_height = int(config.get("browser_window_height", 720))
        browser_executable_path = str(config.get("browser_executable_path", "") or "").strip()

        if adapter_type == "playwright":
            browser_type = str(config.get("playwright_browser_type", "chromium")).lower()
            return PlaywrightAdapter(
                browser_type=browser_type,
                headless=headless,
                user_agent=user_agent,
                window_width=window_width,
                window_height=window_height,
                executable_path=browser_executable_path,
            )
        elif adapter_type == "camoufox":
            geoip = bool(config.get("camoufox_geoip", False))
            return CamoufoxAdapter(
                headless=headless,
                geoip=geoip,
                user_agent=user_agent,
                window_width=window_width,
                window_height=window_height,
            )
        else:
            raise ValueError(f"不支持的浏览器适配器类型: {adapter_type}")
