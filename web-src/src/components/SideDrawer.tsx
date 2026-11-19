import React, { useState, useEffect } from "react";
import { AuditLogItem } from "../types";

interface SideDrawerProps {
  item: AuditLogItem | null;
  onClose: () => void;
}

export const SideDrawer: React.FC<SideDrawerProps> = ({ item, onClose }) => {
  const [copiedType, setCopiedType] = useState<string | null>(null);

  // 监听 ESC 键关闭抽屉
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

  if (!item) return null;

  const handleCopy = (text: string, type: string) => {
    navigator.clipboard.writeText(text);
    setCopiedType(type);
    setTimeout(() => {
      setCopiedType(null);
    }, 2000);
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
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 1000,
        display: "flex",
        justifyContent: "flex-end",
      }}
    >
      {/* 半透明遮罩层 */}
      <div
        onClick={onClose}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0, 0, 0, 0.4)",
          backdropFilter: "blur(2px)",
          transition: "opacity var(--transition-normal)",
        }}
      />

      {/* 右侧大圆角抽屉主体 */}
      <div
        style={{
          position: "relative",
          width: "100%",
          maxWidth: "680px",
          height: "100%",
          backgroundColor: "var(--color-surface)",
          borderTopLeftRadius: "var(--radius-2xl)",
          borderBottomLeftRadius: "var(--radius-2xl)",
          boxShadow: "var(--shadow-drawer)",
          display: "flex",
          flexDirection: "column",
          zIndex: 1001,
          animation: "slideInRight 0.25s cubic-bezier(0, 0, 0.2, 1)",
          overflow: "hidden",
        }}
      >
        <style>{`
          @keyframes slideInRight {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
          }
        `}</style>

        {/* 顶部标题栏 */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "20px 24px",
            borderBottom: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span
              style={{
                fontSize: "18px",
                fontWeight: 700,
                color: "var(--color-text)",
              }}
            >
              审计详情 #{item.id}
            </span>
            <span
              style={{
                padding: "2px 8px",
                borderRadius: "var(--radius-sm)",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                fontWeight: 600,
                backgroundColor: "var(--color-primary-container)",
                color: "var(--color-on-primary-container)",
              }}
            >
              {item.tool_name}
            </span>
          </div>

          <button
            onClick={onClose}
            style={{
              width: "36px",
              height: "36px",
              borderRadius: "var(--radius-full)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "18px",
              color: "var(--color-text-secondary)",
              backgroundColor: "var(--color-surface-container)",
              transition: "background var(--transition-fast)",
            }}
            title="关闭 (Esc)"
          >
            ✕
          </button>
        </div>

        {/* 可滚动内容区 */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "24px",
            display: "flex",
            flexDirection: "column",
            gap: "20px",
          }}
        >
          {/* 状态提醒横幅 */}
          {!item.is_permitted && (
            <div
              style={{
                backgroundColor: "var(--color-error-bg)",
                border: "1px solid var(--color-error)",
                borderRadius: "var(--radius-md)",
                padding: "12px 16px",
                color: "var(--color-error)",
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: "4px" }}>🚫 动作已被安全拦截</div>
              <div style={{ fontSize: "13px" }}>原因: {item.deny_reason || "命中系统白名单拦截策略"}</div>
            </div>
          )}

          {item.is_error && (
            <div
              style={{
                backgroundColor: "var(--color-warning-bg)",
                border: "1px solid var(--color-warning)",
                borderRadius: "var(--radius-md)",
                padding: "12px 16px",
                color: "var(--color-warning)",
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: "4px" }}>⚠️ 工具执行发生异常</div>
              <div style={{ fontSize: "13px", fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>
                {item.error_message || "未知异常"}
              </div>
            </div>
          )}

          {/* 基础元数据网格 */}
          <div
            style={{
              backgroundColor: "var(--color-surface-container)",
              borderRadius: "var(--radius-lg)",
              padding: "16px",
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: "12px",
              fontSize: "13px",
            }}
          >
            <div>
              <span style={{ color: "var(--color-text-secondary)" }}>时间戳: </span>
              <strong style={{ color: "var(--color-text)" }}>{item.timestamp}</strong>
            </div>
            <div>
              <span style={{ color: "var(--color-text-secondary)" }}>会话名: </span>
              <strong style={{ color: "var(--color-text)" }}>{sessionDisplayName}</strong>
            </div>
            <div>
              <span style={{ color: "var(--color-text-secondary)" }}>发送者: </span>
              <strong style={{ color: "var(--color-text)" }}>{senderDisplayName}</strong>
            </div>
            <div>
              <span style={{ color: "var(--color-text-secondary)" }}>发送者 UID: </span>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text)" }}>{item.sender_id}</span>
            </div>
            <div>
              <span style={{ color: "var(--color-text-secondary)" }}>会话 ID: </span>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text)" }}>{item.session_id}</span>
            </div>
            <div>
              <span style={{ color: "var(--color-text-secondary)" }}>多租户上下文: </span>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text)" }}>{item.context_key}</span>
            </div>
          </div>

          {/* 目标 URL */}
          {item.url && (
            <div>
              <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "6px" }}>
                目标网页 URL
              </div>
              <div
                style={{
                  backgroundColor: "var(--color-surface-container)",
                  padding: "10px 14px",
                  borderRadius: "var(--radius-md)",
                  fontSize: "13px",
                  fontFamily: "var(--font-mono)",
                  wordBreak: "break-all",
                  color: "var(--color-primary)",
                }}
              >
                🌐 {item.url}
              </div>
            </div>
          )}

          {/* 入参详情 */}
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "8px",
              }}
            >
              <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--color-text)" }}>
                调用输入参数 (JSON)
              </span>
              <button
                onClick={() => handleCopy(formattedArgs, "args")}
                style={{
                  fontSize: "12px",
                  padding: "4px 10px",
                  borderRadius: "var(--radius-sm)",
                  backgroundColor: "var(--color-surface-container-high)",
                  color: "var(--color-text)",
                  fontWeight: 500,
                  transition: "background var(--transition-fast)",
                }}
              >
                {copiedType === "args" ? "✓ 已复制" : "📋 复制入参"}
              </button>
            </div>
            <pre
              style={{
                backgroundColor: "var(--color-surface-container)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-lg)",
                padding: "14px",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                color: "var(--color-text)",
                overflowX: "auto",
                lineHeight: "1.5",
              }}
            >
              {formattedArgs || "{}"}
            </pre>
          </div>

          {/* 输出结果 / DOM 快照长文本 */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "8px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--color-text)" }}>
                  输出结果 / 快照内容
                </span>
                <span style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
                  ({(item.output_result || "").length} 字符)
                </span>
              </div>
              <button
                onClick={() => handleCopy(item.output_result, "output")}
                style={{
                  fontSize: "12px",
                  padding: "4px 10px",
                  borderRadius: "var(--radius-sm)",
                  backgroundColor: "var(--color-surface-container-high)",
                  color: "var(--color-text)",
                  fontWeight: 500,
                  transition: "background var(--transition-fast)",
                }}
              >
                {copiedType === "output" ? "✓ 已复制" : "📋 复制完整内容"}
              </button>
            </div>
            <div
              style={{
                backgroundColor: "var(--color-surface-container)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-lg)",
                padding: "16px",
                fontSize: "13px",
                fontFamily: "var(--font-mono)",
                color: "var(--color-text)",
                lineHeight: "1.6",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                maxHeight: "500px",
                overflowY: "auto",
              }}
            >
              {item.output_result || "(无执行结果输出)"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
