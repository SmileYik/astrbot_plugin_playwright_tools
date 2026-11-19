import React from "react";
import { AuditStats } from "../types";

interface StatsOverviewProps {
  stats: AuditStats;
  activeStatus: string;
  onSelectStatus: (status: "all" | "allowed" | "denied" | "error") => void;
}

export const StatsOverview: React.FC<StatsOverviewProps> = ({
  stats,
  activeStatus,
  onSelectStatus,
}) => {
  const chips = [
    {
      label: "全部调用",
      count: stats.total,
      status: "all" as const,
      color: "var(--color-primary)",
      bg: "var(--color-primary-container)",
      textColor: "var(--color-on-primary-container)",
      icon: "📊",
    },
    {
      label: "今日调用",
      count: stats.today_count,
      status: null, // 不参与过滤状态切换，仅作为今日指标
      color: "var(--color-info)",
      bg: "var(--color-info-bg)",
      textColor: "var(--color-info)",
      icon: "⚡",
    },
    {
      label: "已允许",
      count: stats.allowed,
      status: "allowed" as const,
      color: "var(--color-success)",
      bg: "var(--color-success-bg)",
      textColor: "var(--color-success)",
      icon: "✓",
    },
    {
      label: "安全拦截",
      count: stats.denied,
      status: "denied" as const,
      color: "var(--color-error)",
      bg: "var(--color-error-bg)",
      textColor: "var(--color-error)",
      icon: "🚫",
    },
    {
      label: "执行异常",
      count: stats.error,
      status: "error" as const,
      color: "var(--color-warning)",
      bg: "var(--color-warning-bg)",
      textColor: "var(--color-warning)",
      icon: "⚠️",
    },
  ];

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "10px",
        margin: "16px 0 20px 0",
      }}
    >
      {chips.map((chip, index) => {
        const isSelected = chip.status !== null && activeStatus === chip.status;
        return (
          <div
            key={index}
            onClick={() => {
              if (chip.status !== null) {
                onSelectStatus(chip.status);
              }
            }}
            style={{
              flex: "1 1 140px",
              minWidth: "120px",
              padding: "10px 14px",
              backgroundColor: isSelected ? chip.bg : "var(--color-surface)",
              borderRadius: "var(--radius-lg)",
              border: isSelected ? `2px solid ${chip.color}` : "1px solid var(--color-border)",
              boxShadow: "var(--shadow-sm)",
              cursor: chip.status !== null ? "pointer" : "default",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              transition: "all var(--transition-fast)",
            }}
          >
            <div>
              <div style={{ fontSize: "11px", color: "var(--color-text-secondary)", marginBottom: "2px" }}>
                {chip.icon} {chip.label}
              </div>
              <div style={{ fontSize: "18px", fontWeight: 700, color: "var(--color-text)" }}>
                {chip.count}
              </div>
            </div>
            {isSelected && (
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 600,
                  color: chip.color,
                  backgroundColor: "rgba(255,255,255,0.6)",
                  padding: "2px 6px",
                  borderRadius: "var(--radius-full)",
                }}
              >
                已选中
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
};
