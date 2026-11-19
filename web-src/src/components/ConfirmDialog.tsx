import React, { useEffect } from "react";

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  isDestructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  confirmText = "确认",
  cancelText = "取消",
  isDestructive = false,
  onConfirm,
  onCancel,
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
      }
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 2000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        onClick={onCancel}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0, 0, 0, 0.45)",
          backdropFilter: "blur(2px)",
        }}
      />
      <div
        style={{
          position: "relative",
          zIndex: 2001,
          width: "90%",
          maxWidth: "460px",
          backgroundColor: "var(--color-surface)",
          borderRadius: "var(--radius-2xl)",
          padding: "24px",
          boxShadow: "var(--shadow-lg)",
          display: "flex",
          flexDirection: "column",
          gap: "16px",
        }}
      >
        <div style={{ fontSize: "18px", fontWeight: 700, color: "var(--color-text)" }}>
          {title}
        </div>
        <div style={{ fontSize: "14px", color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
          {message}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px", marginTop: "8px" }}>
          <button
            onClick={onCancel}
            style={{
              padding: "8px 18px",
              borderRadius: "var(--radius-full)",
              fontSize: "14px",
              fontWeight: 500,
              color: "var(--color-text-secondary)",
              backgroundColor: "transparent",
            }}
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            style={{
              padding: "8px 20px",
              borderRadius: "var(--radius-full)",
              fontSize: "14px",
              fontWeight: 600,
              color: "#ffffff",
              backgroundColor: isDestructive ? "var(--color-error)" : "var(--color-primary)",
              boxShadow: "var(--shadow-sm)",
            }}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};
