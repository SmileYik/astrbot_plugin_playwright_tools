import React from "react";
import { AuditLogItem } from "../types";
import styles from "./AuditCard.module.css";

interface AuditCardProps {
  item: AuditLogItem;
  onClick: (item: AuditLogItem) => void;
  isSelected?: boolean;
}

export const AuditCard: React.FC<AuditCardProps> = ({ item, onClick, isSelected }) => {
  const getStatusBadge = () => {
    if (!item.is_permitted) {
      return (
        <span className={`${styles.statusBadge} ${styles.statusDenied}`}>
          ● 已拦截
        </span>
      );
    }
    if (item.is_error) {
      return (
        <span className={`${styles.statusBadge} ${styles.statusError}`}>
          ▲ 异常
        </span>
      );
    }
    return (
      <span className={`${styles.statusBadge} ${styles.statusAllowed}`}>
        ✓ 已允许
      </span>
    );
  };

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
      className={`${styles.card} ${isSelected ? styles.selected : ""}`}
    >
      {/* 头部元数据栏 */}
      <div className={styles.headerRow}>
        <div className={styles.metaGroup}>
          {getStatusBadge()}
          <span className={styles.toolBadge}>{item.tool_name}</span>
          {item.screenshot_path && (
            <span
              className={styles.screenshotBadge}
              title={`截图存档: ${item.screenshot_path}`}
            >
              📸 截图
            </span>
          )}
          <span className={styles.timestamp}>{item.timestamp}</span>
        </div>

        <div className={styles.sessionSender}>
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
        <div className={styles.urlTarget} title={item.url}>
          🌐 {item.url}
        </div>
      )}

      {/* 入参单行预览 */}
      {item.input_args && item.input_args !== "{}" && (
        <div className={styles.inputArgsBox} title={`入参: ${item.input_args}`}>
          <span className={styles.inputArgsLabel}>入参: </span>
          {item.input_args}
        </div>
      )}

      {/* 结果/快照头部 2 行预览 */}
      <div className={styles.outputPreviewBox}>
        {preview.text}
        {preview.isTruncated && (
          <span className={styles.truncatedNote}>
            ... (剩余 {preview.remainingChars} 字符已折叠，点击卡片展开详情)
          </span>
        )}
      </div>
    </div>
  );
};
