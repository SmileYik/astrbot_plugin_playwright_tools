import React from "react";
import { AuditLogItem } from "../types";

interface AuditCardProps {
  item: AuditLogItem;
  onClick: (item: AuditLogItem) => void;
  isSelected?: boolean;
}

export const AuditCard: React.FC<AuditCardProps> = ({ item, onClick, isSelected }) => {
  const getStatusBadge = () => {
    if (!item.is_permitted) {
      return (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "3px 10px",
            borderRadius: "var(--radius-full)",
            fontSize: "12px",
            fontWeight: 600,
            color: "var(--color-error)",
            backgroundColor: "var(--color-error-bg)",
          }}
        >
          ● 已拦截
        </span>
      );
    }
    if (item.is_error) {
      return (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "3px 10px",
            borderRadius: "var(--radius-full)",
            fontSize: "12px",
            fontWeight: 600,
            color: "var(--color-warning)",
            backgroundColor: "var(--color-warning-bg)",
          }}
        >
          ▲ 异常
        </span>
      );
    }
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          padding: "3px 10px",
          borderRadius: "var(--radius-full)",
          fontSize: "12px",
          fontWeight: 600,
          color: "var(--color-success)",
          backgroundColor: "var(--color-success-bg)",
        }}
      >
        ✓ 已允许
      </span>
    );
  };

  // 格式化输出前 2 行预览与剩余字数计算
  const getOutputPreview = () => {
    const raw = item.output_result || item.error_message || item.deny_reason || "(无输出内容)";
    const lines = raw.split("\n");
    const previewLines = lines.slice(0, 2).join("\n");
    const isTruncated = lines.length > 2 || raw.length > 120;
    const truncatedText = previewLines.length > 120 ? previewLines.slice(0, 120) + "..." : previewLines;
    const remainingChars = raw.length - truncatedText.length;

    return {
      text: truncatedText,
      isTruncated,
      remainingChars: remainingChars > 0 ? remainingChars : 0,
    };
  };

  const preview = getOutputPreview();
  const sessionDisplayName = item.session_name || item.session_id || "未知会话";
  const senderDisplayName = item.sender_name || item.sender_id || "未知用户";

  return (
    <div
      onClick={() => onClick(item)}
      style={{
        backgroundColor: "var(--color-surface)",
        borderRadius: "var(--radius-xl)",
        padding: "16px 20px",
        marginBottom: "12px",
        border: isSelected ? "2px solid var(--color-primary)" : "1px solid var(--color-border)",
        boxShadow: isSelected ? "var(--shadow-md)" : "var(--shadow-sm)",
        cursor: "pointer",
        transition: "all var(--transition-fast)",
      }}
      onMouseEnter={(e) => {
        if (!isSelected) {
          e.currentTarget.style.borderColor = "var(--color-primary)";
          e.currentTarget.style.boxShadow = "var(--shadow-md)";
          e.currentTarget.style.transform = "translateY(-1px)";
        }
      }}
      onMouseLeave={(e) => {
        if (!isSelected) {
          e.currentTarget.style.borderColor = "var(--color-border)";
          e.currentTarget.style.boxShadow = "var(--shadow-sm)";
          e.currentTarget.style.transform = "none";
        }
      }}
    >
      {/* 头部元数据栏 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "8px",
          marginBottom: "10px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          {getStatusBadge()}
          <span
            style={{
              padding: "2px 8px",
              borderRadius: "var(--radius-sm)",
              fontSize: "12px",
              fontFamily: "var(--font-mono)",
              fontWeight: 500,
              backgroundColor: "var(--color-primary-container)",
              color: "var(--color-on-primary-container)",
            }}
          >
            {item.tool_name}
          </span>
          {item.screenshot_path && (
            <span
              style={{
                padding: "2px 8px",
                borderRadius: "var(--radius-sm)",
                fontSize: "12px",
                fontWeight: 600,
                backgroundColor: "var(--color-secondary-container, #e8def8)",
                color: "var(--color-on-secondary-container, #1d192b)",
              }}
              title={`截图存档: ${item.screenshot_path}`}
            >
              📸 截图
            </span>
          )}
          <span style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
            {item.timestamp}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "12px", color: "var(--color-text-secondary)" }}>
          <span title={`会话: ${sessionDisplayName}`}>
            💬 {sessionDisplayName}
          </span>
          <span title={`发送者: ${senderDisplayName}`}>
            👤 {senderDisplayName}
          </span>
        </div>
      </div>

      {/* URL 目标展示 */}
      {item.url && (
        <div
          style={{
            fontSize: "13px",
            color: "var(--color-primary)",
            marginBottom: "8px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={item.url}
        >
          🌐 {item.url}
        </div>
      )}

      {/* 入参单行预览 */}
      {item.input_args && item.input_args !== "{}" && (
        <div
          style={{
            backgroundColor: "var(--color-surface-container)",
            padding: "6px 10px",
            borderRadius: "var(--radius-sm)",
            fontSize: "12px",
            fontFamily: "var(--font-mono)",
            color: "var(--color-text-secondary)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            marginBottom: "8px",
          }}
          title={`入参: ${item.input_args}`}
        >
          <span style={{ fontWeight: 600, color: "var(--color-text)" }}>入参: </span>
          {item.input_args}
        </div>
      )}

      {/* 结果/快照头部 2 行预览 */}
      <div
        style={{
          backgroundColor: "var(--color-surface-container)",
          padding: "10px 12px",
          borderRadius: "var(--radius-md)",
          fontSize: "13px",
          fontFamily: "var(--font-mono)",
          color: "var(--color-text)",
          lineHeight: "1.5",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
        }}
      >
        {preview.text}
        {preview.isTruncated && (
          <span
            style={{
              display: "block",
              marginTop: "4px",
              color: "var(--color-primary)",
              fontSize: "12px",
              fontWeight: 500,
            }}
          >
            ... (剩余 {preview.remainingChars} 字符已折叠，点击卡片展开详情)
          </span>
        )}
      </div>
    </div>
  );
};
