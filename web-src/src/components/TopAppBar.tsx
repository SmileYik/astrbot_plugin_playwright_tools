import React, { useState, useEffect } from "react";

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
}) => {
  const [searchInput, setSearchInput] = useState(keyword);
  const [showExportMenu, setShowExportMenu] = useState(false);

  // 防抖 300ms 触发搜索
  useEffect(() => {
    const timer = setTimeout(() => {
      onKeywordChange(searchInput);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, onKeywordChange]);

  return (
    <header
      style={{
        backgroundColor: "var(--color-surface)",
        borderRadius: "var(--radius-xl)",
        padding: "16px 20px",
        boxShadow: "var(--shadow-sm)",
        border: "1px solid var(--color-border)",
        display: "flex",
        flexDirection: "column",
        gap: "14px",
      }}
    >
      {/* 顶部标题与主要操作 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "24px" }}>🎭</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h1 style={{ fontSize: "18px", fontWeight: 700, color: "var(--color-text)" }}>
                网页工具审计
              </h1>
              <span
                style={{
                  fontSize: "11px",
                  padding: "1px 6px",
                  borderRadius: "var(--radius-full)",
                  backgroundColor: isBridgeReady ? "var(--color-success-bg)" : "var(--color-surface-container-high)",
                  color: isBridgeReady ? "var(--color-success)" : "var(--color-text-secondary)",
                  fontWeight: 600,
                }}
              >
                {isBridgeReady ? "● 已连接 Bridge" : "○ 离线模式"}
              </span>
            </div>
            <p style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
              Playwright 自动化网页工具执行明细、DOM快照与拦截审计
            </p>
          </div>
        </div>

        {/* 运维按钮组 */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            onClick={onRefresh}
            disabled={isLoading}
            style={{
              padding: "8px 14px",
              borderRadius: "var(--radius-full)",
              fontSize: "13px",
              fontWeight: 500,
              backgroundColor: "var(--color-surface-container)",
              color: "var(--color-text)",
              border: "1px solid var(--color-border)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
            title="刷新数据"
          >
            <span style={{ display: "inline-block", transform: isLoading ? "rotate(180deg)" : "none", transition: "transform 0.4s" }}>
              🔄
            </span>
            刷新
          </button>

          {/* 导出下拉 */}
          <div style={{ position: "relative" }}>
            <button
              onClick={() => setShowExportMenu(!showExportMenu)}
              style={{
                padding: "8px 16px",
                borderRadius: "var(--radius-full)",
                fontSize: "13px",
                fontWeight: 600,
                backgroundColor: "var(--color-primary-container)",
                color: "var(--color-on-primary-container)",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              📥 导出日志 ▼
            </button>
            {showExportMenu && (
              <div
                style={{
                  position: "absolute",
                  top: "110%",
                  right: 0,
                  backgroundColor: "var(--color-surface)",
                  borderRadius: "var(--radius-md)",
                  boxShadow: "var(--shadow-lg)",
                  border: "1px solid var(--color-border)",
                  zIndex: 50,
                  minWidth: "140px",
                  overflow: "hidden",
                }}
              >
                <div
                  onClick={() => {
                    setShowExportMenu(false);
                    onExport("json");
                  }}
                  style={{
                    padding: "10px 14px",
                    fontSize: "13px",
                    cursor: "pointer",
                    color: "var(--color-text)",
                    borderBottom: "1px solid var(--color-border)",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-surface-container)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  📄 导出为 JSON
                </div>
                <div
                  onClick={() => {
                    setShowExportMenu(false);
                    onExport("csv");
                  }}
                  style={{
                    padding: "10px 14px",
                    fontSize: "13px",
                    cursor: "pointer",
                    color: "var(--color-text)",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-surface-container)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  📊 导出为 CSV
                </div>
              </div>
            )}
          </div>

          {/* 清空按钮 */}
          <button
            onClick={onClearClick}
            style={{
              padding: "8px 14px",
              borderRadius: "var(--radius-full)",
              fontSize: "13px",
              fontWeight: 500,
              backgroundColor: "var(--color-error-bg)",
              color: "var(--color-error)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
            title="清空所有审计记录"
          >
            🗑️ 清空记录
          </button>
        </div>
      </div>

      {/* 搜索与多维过滤筛选栏 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
        }}
      >
        {/* 关键词搜索输入框 */}
        <div
          style={{
            flex: "1 1 240px",
            position: "relative",
            display: "flex",
            alignItems: "center",
          }}
        >
          <span
            style={{
              position: "absolute",
              left: "12px",
              color: "var(--color-text-secondary)",
              fontSize: "14px",
              pointerEvents: "none",
            }}
          >
            🔍
          </span>
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索 URL、参数、结果、报错、群名或发送者..."
            style={{
              width: "100%",
              padding: "8px 32px 8px 34px",
              borderRadius: "var(--radius-full)",
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-container)",
              color: "var(--color-text)",
              fontSize: "13px",
            }}
          />
          {searchInput && (
            <button
              onClick={() => setSearchInput("")}
              style={{
                position: "absolute",
                right: "10px",
                fontSize: "12px",
                color: "var(--color-text-secondary)",
                borderRadius: "var(--radius-full)",
                padding: "2px 6px",
              }}
            >
              ✕
            </button>
          )}
        </div>

        {/* 状态筛选下拉框 */}
        <select
          value={status}
          onChange={(e) => onStatusChange(e.target.value as any)}
          style={{
            padding: "8px 14px",
            borderRadius: "var(--radius-full)",
            border: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface-container)",
            color: "var(--color-text)",
            fontSize: "13px",
            cursor: "pointer",
          }}
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
          style={{
            padding: "8px 14px",
            borderRadius: "var(--radius-full)",
            border: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface-container)",
            color: "var(--color-text)",
            fontSize: "13px",
            cursor: "pointer",
          }}
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
