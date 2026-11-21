import React from "react";
import styles from "./Navbar.module.css";

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
    <nav className={styles.nav}>
      {/* 品牌与标题 */}
      <div className={styles.brand}>
        <span className={styles.brandIcon}>🎭</span>
        <div>
          <div className={styles.titleRow}>
            <span className={styles.title}>Playwright 浏览器工具箱</span>
            <span
              className={`${styles.bridgeBadge} ${
                isBridgeReady ? styles.bridgeOnline : styles.bridgeOffline
              }`}
            >
              {isBridgeReady ? "● 已连接" : "○ 离线"}
            </span>
          </div>
          <p className={styles.subtitle}>
            多租户隔离 · 安全拦截 · 实时会话管理
          </p>
        </div>
      </div>

      {/* 标签切换按钮组 */}
      <div className={styles.tabGroup}>
        <button
          onClick={() => onTabChange("audit")}
          className={`${styles.tabBtn} ${
            activeTab === "audit" ? styles.tabActive : ""
          }`}
        >
          <span>📋</span>
          <span>网页工具审计</span>
        </button>

        <button
          onClick={() => onTabChange("lifecycle")}
          className={`${styles.tabBtn} ${
            activeTab === "lifecycle" ? styles.tabActive : ""
          }`}
        >
          <span>🌐</span>
          <span>会话生命周期管理</span>
        </button>
      </div>
    </nav>
  );
};
