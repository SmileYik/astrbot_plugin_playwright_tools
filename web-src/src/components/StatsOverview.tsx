import React from "react";
import { AuditStats } from "../types";
import styles from "./StatsOverview.module.css";

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
      status: null,
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
    <div className={styles.container}>
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
            className={`${styles.chip} ${chip.status === null ? styles.nonClickable : ""}`}
            style={{
              backgroundColor: isSelected ? chip.bg : undefined,
              borderColor: isSelected ? chip.color : undefined,
              borderWidth: isSelected ? "2px" : undefined,
            }}
          >
            <div>
              <div className={styles.label}>
                {chip.icon} {chip.label}
              </div>
              <div className={styles.count}>{chip.count}</div>
            </div>
            {isSelected && (
              <span
                className={styles.badge}
                style={{
                  color: chip.color,
                  backgroundColor: "rgba(255,255,255,0.6)",
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
