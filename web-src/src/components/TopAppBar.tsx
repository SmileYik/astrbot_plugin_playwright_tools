import React, { useState, useEffect } from "react";
import styles from "./TopAppBar.module.css";

interface TopAppBarProps {
  keyword: string;
  onKeywordChange: (val: string) => void;
  status: "all" | "allowed" | "denied" | "error";
  onStatusChange: (val: "all" | "allowed" | "denied" | "error") => void;
  toolName: string;
  onToolNameChange: (val: string) => void;
  onExport: (format: "json" | "csv") => void;
  onClearClick: () => void;
  onRefresh: () => void;
  isLoading: boolean;
  isBridgeReady?: boolean;
  autoRefresh?: boolean;
  onAutoRefreshChange?: (val: boolean) => void;
}

export const TopAppBar: React.FC<TopAppBarProps> = ({
  keyword,
  onKeywordChange,
  status,
  onStatusChange,
  toolName,
  onToolNameChange,
  onExport,
  onClearClick,
  onRefresh,
  isLoading,
  isBridgeReady = false,
  autoRefresh = false,
  onAutoRefreshChange,
}) => {
  const [searchInput, setSearchInput] = useState(keyword);
  const [showExportMenu, setShowExportMenu] = useState(false);

  useEffect(() => {
    setSearchInput(keyword);
  }, [keyword]);

  useEffect(() => {
    if (searchInput !== keyword) {
      const timer = setTimeout(() => {
        onKeywordChange(searchInput);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [searchInput, keyword, onKeywordChange]);

  return (
    <header className={styles.header}>
      {/* 顶部标题与主要操作 */}
      <div className={styles.topRow}>
        <div className={styles.brand}>
          <span className={styles.brandIcon}>🎭</span>
          <div>
            <div className={styles.titleRow}>
              <h1 className={styles.title}>网页工具审计</h1>
              <span
                className={`${styles.bridgeBadge} ${
                  isBridgeReady ? styles.bridgeOnline : styles.bridgeOffline
                }`}
              >
                {isBridgeReady ? "● 已连接 Bridge" : "○ 离线模式"}
              </span>
            </div>
            <p className={styles.subtitle}>
              Playwright 自动化网页工具执行明细、DOM快照与拦截审计
            </p>
          </div>
        </div>

        {/* 运维按钮组 */}
        <div className={styles.buttonGroup}>
          {/* 自动更新流式开关 */}
          {onAutoRefreshChange && (
            <label className={styles.autoRefreshLabel} title="以流的形式自动将最新的记录显示到页面中">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => onAutoRefreshChange(e.target.checked)}
                className={styles.autoRefreshCheckbox}
              />
              <span
                className={`${styles.streamDot} ${
                  autoRefresh ? styles.streamDotActive : ""
                }`}
              />
              <span className={styles.autoRefreshText}>自动更新</span>
            </label>
          )}

          <button
            onClick={onRefresh}
            disabled={isLoading}
            className={styles.refreshBtn}
            title="刷新数据"
          >
            <span
              className={`${styles.refreshIcon} ${
                isLoading ? styles.refreshRotating : ""
              }`}
            >
              🔄
            </span>
            刷新
          </button>

          {/* 导出下拉 */}
          <div className={styles.exportContainer}>
            <button
              onClick={() => setShowExportMenu(!showExportMenu)}
              className={styles.exportBtn}
            >
              📥 导出日志 ▼
            </button>
            {showExportMenu && (
              <div className={styles.exportMenu}>
                <div
                  onClick={() => {
                    setShowExportMenu(false);
                    onExport("json");
                  }}
                  className={`${styles.exportMenuItem} ${styles.exportMenuDivider}`}
                >
                  📄 导出为 JSON
                </div>
                <div
                  onClick={() => {
                    setShowExportMenu(false);
                    onExport("csv");
                  }}
                  className={styles.exportMenuItem}
                >
                  📊 导出为 CSV
                </div>
              </div>
            )}
          </div>

          {/* 清空按钮 */}
          <button
            onClick={onClearClick}
            className={styles.clearBtn}
            title="清空所有审计记录"
          >
            🗑️ 清空记录
          </button>
        </div>
      </div>

      {/* 搜索与多维过滤筛选栏 */}
      <div className={styles.filterRow}>
        {/* 关键词搜索输入框 */}
        <div className={styles.searchBox}>
          <span className={styles.searchIcon}>🔍</span>
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索 URL、参数、结果、报错、群名或发送者..."
            className={styles.searchInput}
          />
          {searchInput && (
            <button
              onClick={() => setSearchInput("")}
              className={styles.clearSearchBtn}
            >
              ✕
            </button>
          )}
        </div>

        {/* 状态筛选下拉框 */}
        <select
          value={status}
          onChange={(e) => onStatusChange(e.target.value as any)}
          className={styles.selectInput}
        >
          <option value="all">所有状态</option>
          <option value="allowed">已允许 (ALLOWED)</option>
          <option value="denied">已拦截 (DENIED)</option>
          <option value="error">执行异常 (ERROR)</option>
        </select>

        {/* 工具类型筛选下拉框 */}
        <select
          value={toolName}
          onChange={(e) => onToolNameChange(e.target.value)}
          className={styles.selectInput}
        >
          <option value="">所有工具</option>
          <option value="pw_page">pw_page (页面管理)</option>
          <option value="pw_interact">pw_interact (交互操作)</option>
          <option value="pw_media">pw_media (截图与下载)</option>
        </select>
      </div>
    </header>
  );
};
