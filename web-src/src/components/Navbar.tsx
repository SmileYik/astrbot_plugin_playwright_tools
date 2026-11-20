import React from "react";

export type NavTabType = "audit" | "lifecycle";

interface NavbarProps {
  activeTab: NavTabType;
  onTabChange: (tab: NavTabType) => void;
  isBridgeReady?: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  onTabChange,
  isBridgeReady = false,
}) => {
  return (
    <nav
      style={{
        backgroundColor: "var(--color-surface)",
        borderRadius: "var(--radius-xl)",
        padding: "12px 20px",
        boxShadow: "var(--shadow-sm)",
        border: "1px solid var(--color-border)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: "12px",
        marginBottom: "20px",
      }}
    >
      {/* 品牌与标题 */}
      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <span style={{ fontSize: "24px" }}>🎭</span>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                fontSize: "16px",
                fontWeight: 700,
                color: "var(--color-text)",
                letterSpacing: "-0.2px",
              }}
            >
              Playwright 浏览器工具箱
            </span>
            <span
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "var(--radius-full)",
                backgroundColor: isBridgeReady
                  ? "var(--color-success-bg)"
                  : "var(--color-surface-container-high)",
                color: isBridgeReady
                  ? "var(--color-success)"
                  : "var(--color-text-secondary)",
                fontWeight: 600,
              }}
            >
              {isBridgeReady ? "● 已连接" : "○ 离线"}
            </span>
          </div>
          <p style={{ fontSize: "12px", color: "var(--color-text-secondary)", margin: 0 }}>
            多租户隔离 · 安全拦截 · 实时会话管理
          </p>
        </div>
      </div>

      {/* 标签切换按钮组 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          backgroundColor: "var(--color-surface-container)",
          borderRadius: "var(--radius-full)",
          padding: "4px",
          gap: "4px",
        }}
      >
        <button
          onClick={() => onTabChange("audit")}
          style={{
            padding: "8px 18px",
            borderRadius: "var(--radius-full)",
            fontSize: "13px",
            fontWeight: activeTab === "audit" ? 700 : 500,
            backgroundColor:
              activeTab === "audit"
                ? "var(--color-primary)"
                : "transparent",
            color:
              activeTab === "audit"
                ? "var(--color-on-primary)"
                : "var(--color-text-secondary)",
            boxShadow:
              activeTab === "audit"
                ? "var(--shadow-sm)"
                : "none",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            transition: "all var(--transition-fast)",
            cursor: "pointer",
          }}
        >
          <span>📋</span>
          <span>网页工具审计</span>
        </button>

        <button
          onClick={() => onTabChange("lifecycle")}
          style={{
            padding: "8px 18px",
            borderRadius: "var(--radius-full)",
            fontSize: "13px",
            fontWeight: activeTab === "lifecycle" ? 700 : 500,
            backgroundColor:
              activeTab === "lifecycle"
                ? "var(--color-primary)"
                : "transparent",
            color:
              activeTab === "lifecycle"
                ? "var(--color-on-primary)"
                : "var(--color-text-secondary)",
            boxShadow:
              activeTab === "lifecycle"
                ? "var(--shadow-sm)"
                : "none",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            transition: "all var(--transition-fast)",
            cursor: "pointer",
          }}
        >
          <span>🌐</span>
          <span>会话生命周期管理</span>
        </button>
      </div>
    </nav>
  );
};
