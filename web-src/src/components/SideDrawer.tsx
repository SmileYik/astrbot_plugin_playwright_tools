import React, { useState, useEffect } from "react";
import { AuditLogItem } from "../types";
import { fetchScreenshot } from "../api";
import styles from "./SideDrawer.module.css";

interface SideDrawerProps {
  item: AuditLogItem | null;
  onClose: () => void;
}

export const SideDrawer: React.FC<SideDrawerProps> = ({ item, onClose }) => {
  const [copiedType, setCopiedType] = useState<string | null>(null);
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    if (item) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [item, onClose]);

  // 加载截图预览（使用统一 API 模块，带宿主认证并以 Data URL 返回，避免 401）
  useEffect(() => {
    let active = true;
    if (!item?.screenshot_path) {
      setScreenshotUrl(null);
      return;
    }
    fetchScreenshot(item.screenshot_path).then((dataUrl) => {
      if (active) {
        setScreenshotUrl(dataUrl);
      }
    });
    return () => {
      active = false;
    };
  }, [item?.screenshot_path]);

  if (!item) return null;

  const handleCopy = (text: string, type: string) => {
    navigator.clipboard.writeText(text);
    setCopiedType(type);
    setTimeout(() => {
      setCopiedType(null);
    }, 2000);
  };

  const handleOpenScreenshot = () => {
    if (!screenshotUrl) return;
    const w = window.open("");
    if (w) {
      w.document.write(
        `<title>截图预览</title><body style="margin:0;background:#111;display:flex;align-items:center;justify-content:center;height:100vh;"><img src="${screenshotUrl}" style="max-width:98%;max-height:98%;object-fit:contain;border-radius:4px;box-shadow:0 4px 20px rgba(0,0,0,0.5);"/></body>`
      );
      w.document.close();
    }
  };

  const formatJson = (raw: string) => {
    try {
      const parsed = JSON.parse(raw);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return raw;
    }
  };

  const formattedArgs = formatJson(item.input_args);
  const sessionDisplayName = item.session_name || item.session_id || "未知会话";
  const senderDisplayName = item.sender_name || item.sender_id || "未知用户";

  return (
    <div className={styles.drawerOverlay}>
      <div onClick={onClose} className={styles.backdrop} />

      <div className={styles.drawer}>
        {/* 抽屉头部 */}
        <div className={styles.header}>
          <div className={styles.headerTitleRow}>
            <span style={{ fontSize: "20px" }}>🔍</span>
            <h2 className={styles.headerTitle}>审计详情 #{item.id}</h2>
          </div>
          <button onClick={onClose} className={styles.closeBtn} title="关闭 (Esc)">
            ✕
          </button>
        </div>

        {/* 抽屉滚动内容 */}
        <div className={styles.content}>
          {/* 状态横幅 */}
          {!item.is_permitted && (
            <div className={`${styles.banner} ${styles.bannerDenied}`}>
              <span className={styles.bannerTitle}>🚫 安全策略拦截</span>
              <span>{item.deny_reason || "该操作已被系统白名单安全规则阻断"}</span>
            </div>
          )}
          {item.is_error && (
            <div className={`${styles.banner} ${styles.bannerError}`}>
              <span className={styles.bannerTitle}>⚠️ 工具执行异常</span>
              <span>
                {item.error_message
                  ? item.error_message.split("\n")[0]
                  : "执行期间发生未捕获异常"}
              </span>
            </div>
          )}

          {/* 网格元信息 */}
          <div className={styles.gridInfo}>
            <div className={styles.gridItem}>
              <span className={styles.gridLabel}>调用工具: </span>
              <span className={styles.gridValueBold}>{item.tool_name}</span>
            </div>
            <div className={styles.gridItem}>
              <span className={styles.gridLabel}>调用时间: </span>
              <span className={styles.gridValue}>{item.timestamp}</span>
            </div>
            <div className={styles.gridItem}>
              <span className={styles.gridLabel}>来源会话: </span>
              <span className={styles.gridValueBold}>{sessionDisplayName}</span>
            </div>
            <div className={styles.gridItem}>
              <span className={styles.gridLabel}>发送用户: </span>
              <span className={styles.gridValueBold}>{senderDisplayName}</span>
            </div>
            <div className={styles.gridItem}>
              <span className={styles.gridLabel}>会话 ID: </span>
              <span className={styles.gridValue}>{item.session_id}</span>
            </div>
            <div className={styles.gridItem}>
              <span className={styles.gridLabel}>上下文键: </span>
              <span className={styles.gridValue}>{item.context_key}</span>
            </div>
          </div>

          {/* 目标 URL */}
          {item.url && (
            <div>
              <div className={styles.sectionTitle}>目标网页 URL</div>
              <div className={styles.urlBox}>🌐 {item.url}</div>
            </div>
          )}

          {/* 入参详情 */}
          <div>
            <div className={styles.sectionHeaderRow}>
              <span className={styles.sectionHeaderTitle}>调用输入参数 (JSON)</span>
              <button onClick={() => handleCopy(formattedArgs, "args")} className={styles.copyBtn}>
                {copiedType === "args" ? "✓ 已复制" : "📋 复制入参"}
              </button>
            </div>
            <pre className={styles.codeBox}>{formattedArgs || "{}"}</pre>
          </div>

          {/* 截图预览 */}
          {item.screenshot_path && (
            <div>
              <div className={styles.sectionHeaderRow}>
                <span className={styles.sectionHeaderTitle}>📸 审计截图存档</span>
                <span style={{ fontSize: "12px", color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)" }}>
                  {item.screenshot_path}
                </span>
              </div>
              <div className={styles.screenshotContainer}>
                {screenshotUrl && (
                  <img
                    src={screenshotUrl}
                    alt="审计截图"
                    className={styles.screenshotImg}
                    onClick={handleOpenScreenshot}
                  />
                )}
                <div className={styles.screenshotHint}>点击可在大图窗口中查看原图</div>
              </div>
            </div>
          )}

          {/* 异常调用堆栈 (Stack Trace) */}
          {item.is_error && item.error_message && item.error_message.includes("\n") && (
            <div>
              <div className={styles.sectionHeaderRow}>
                <span className={styles.sectionHeaderTitle} style={{ color: "var(--color-error)" }}>
                  🚨 异常调用堆栈 (Stack Trace)
                </span>
                <button
                  onClick={() => handleCopy(item.error_message, "traceback")}
                  className={styles.copyBtn}
                >
                  {copiedType === "traceback" ? "✓ 已复制堆栈" : "📋 复制完整堆栈"}
                </button>
              </div>
              <pre className={`${styles.codeBox} ${styles.stackTraceBox}`}>
                {item.error_message}
              </pre>
            </div>
          )}

          {/* 输出结果 / DOM 快照长文本 */}
          <div className={styles.outputResultContainer}>
            <div className={styles.sectionHeaderRow}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className={styles.sectionHeaderTitle}>输出结果 / 快照内容</span>
                <span style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
                  ({(item.output_result || "").length} 字符)
                </span>
              </div>
              <button onClick={() => handleCopy(item.output_result, "output")} className={styles.copyBtn}>
                {copiedType === "output" ? "✓ 已复制" : "📋 复制完整内容"}
              </button>
            </div>
            <div className={styles.outputResultBox}>
              {item.output_result || "(无执行结果输出)"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
