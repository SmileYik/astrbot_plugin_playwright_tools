import { useState, useEffect, useCallback } from "react";
import "./styles/theme.css";
import { Navbar, NavTabType } from "./components/Navbar";
import { AuditView } from "./views/AuditView";
import { LifecycleView } from "./views/LifecycleView";

const TAB_STORAGE_KEY = "astrbot_plugin_playwright_tools:active_tab";

export function App() {
  const [activeTab, setActiveTab] = useState<NavTabType>(() => {
    try {
      const saved = localStorage.getItem(TAB_STORAGE_KEY);
      if (saved === "lifecycle" || saved === "audit") {
        return saved;
      }
    } catch {
      // ignore
    }
    return "audit";
  });

  const [isBridgeReady, setIsBridgeReady] = useState(false);
  const [bannerMsg, setBannerMsg] = useState<{ text: string; type: "info" | "error" } | null>(null);

  const showBanner = useCallback((text: string, type: "info" | "error" = "info") => {
    setBannerMsg({ text, type });
    setTimeout(() => setBannerMsg(null), 3000);
  }, []);

  const handleTabChange = useCallback((tab: NavTabType) => {
    setActiveTab(tab);
    try {
      localStorage.setItem(TAB_STORAGE_KEY, tab);
    } catch {
      // ignore
    }
  }, []);

  // 初始化 Bridge 连接
  useEffect(() => {
    const initBridge = async () => {
      const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
      if (bridge && typeof bridge.ready === "function") {
        try {
          const ctx = await bridge.ready();
          if (ctx?.isDark) {
            document.documentElement.setAttribute("data-theme", "dark");
          }
          setIsBridgeReady(true);
        } catch {
          setIsBridgeReady(false);
        }
      } else {
        setIsBridgeReady(false);
      }
    };
    initBridge();
  }, []);

  return (
    <div
      style={{
        maxWidth: "1140px",
        margin: "0 auto",
        padding: "24px 20px 60px 20px",
      }}
    >
      {/* 离线预览或全局通知气泡 */}
      {bannerMsg && (
        <div
          style={{
            position: "fixed",
            top: "20px",
            right: "20px",
            zIndex: 3000,
            padding: "12px 20px",
            borderRadius: "var(--radius-lg)",
            backgroundColor:
              bannerMsg.type === "error" ? "var(--color-error)" : "var(--color-primary)",
            color: "#ffffff",
            boxShadow: "var(--shadow-lg)",
            fontSize: "14px",
            fontWeight: 500,
            animation: "fadeIn 0.2s ease-in-out",
          }}
        >
          {bannerMsg.text}
        </div>
      )}

      {/* 顶部统一导航栏 */}
      <Navbar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        isBridgeReady={isBridgeReady}
      />

      {/* 根据激活 Tab 渲染对应视图 */}
      {activeTab === "audit" ? (
        <AuditView showBanner={showBanner} isBridgeReady={isBridgeReady} />
      ) : (
        <LifecycleView showBanner={showBanner} isBridgeReady={isBridgeReady} />
      )}
    </div>
  );
}

export default App;
