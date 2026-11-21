import React, { useState, useEffect, useCallback } from "react";
import { AuditLogItem, AuditStats } from "../types";
import { TopAppBar } from "../components/TopAppBar";
import { StatsOverview } from "../components/StatsOverview";
import { AuditCard } from "../components/AuditCard";
import { SideDrawer } from "../components/SideDrawer";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useAutoStream } from "../hooks/useAutoStream";
import {
  fetchAuditLogs,
  fetchAuditStats,
  exportAuditLogs,
  clearAuditLogs,
  isBridgeAvailable,
} from "../api";
import styles from "./AuditView.module.css";

interface AuditViewProps {
  showBanner?: (msg: string, type?: "info" | "error") => void;
  isBridgeReady?: boolean;
}

export const AuditView: React.FC<AuditViewProps> = ({
  showBanner: externalShowBanner,
  isBridgeReady: externalBridgeReady,
}) => {
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [stats, setStats] = useState<AuditStats>({
    total: 0,
    allowed: 0,
    denied: 0,
    error: 0,
    today_count: 0,
  });

  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(15);
  const [keyword, setKeyword] = useState<string>("");
  const [status, setStatus] = useState<"all" | "allowed" | "denied" | "error">("all");
  const [toolName, setToolName] = useState<string>("");

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [selectedItem, setSelectedItem] = useState<AuditLogItem | null>(null);
  const [isClearModalOpen, setIsClearModalOpen] = useState<boolean>(false);
  const [banner, setBanner] = useState<{ msg: string; type: "info" | "error" } | null>(null);

  const showBanner = useCallback((msg: string, type: "info" | "error" = "info") => {
    if (externalShowBanner) {
      externalShowBanner(msg, type);
    }
    setBanner({ msg, type });
    setTimeout(() => {
      setBanner((prev) => (prev?.msg === msg ? null : prev));
    }, 4000);
  }, [externalShowBanner]);

  const handleKeywordChange = useCallback((val: string) => {
    setKeyword(val);
    setPage(1);
  }, []);

  const handleStatusChange = useCallback((val: "all" | "allowed" | "denied" | "error") => {
    setStatus(val);
    setPage(1);
  }, []);

  const handleToolNameChange = useCallback((val: string) => {
    setToolName(val);
    setPage(1);
  }, []);

  // 获取审计列表
  const loadLogs = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await fetchAuditLogs({
        page,
        page_size: pageSize,
        keyword: keyword.trim(),
        status,
        tool_name: toolName.trim(),
      });
      setLogs(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      showBanner(`获取日志失败: ${err}`, "error");
    } finally {
      setIsLoading(false);
    }
  }, [page, pageSize, keyword, status, toolName, showBanner]);

  // 获取指标统计
  const loadStats = useCallback(async () => {
    try {
      const s = await fetchAuditStats();
      setStats(s);
    } catch {
      // 静默处理
    }
  }, []);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // 实时流式自动更新
  useAutoStream({
    enabled: autoRefresh,
    intervalMs: 2500,
    canStream: page === 1 && !selectedItem,
    onStreamUpdate: async () => {
      try {
        const [data, s] = await Promise.all([
          fetchAuditLogs({
            page: 1,
            page_size: pageSize,
            keyword: keyword.trim(),
            status,
            tool_name: toolName.trim(),
          }),
          fetchAuditStats().catch(() => null),
        ]);
        if (data && data.items) {
          setLogs(data.items);
          setTotal(data.total || 0);
        }
        if (s) {
          setStats(s);
        }
      } catch {
        // 静默
      }
    },
    onBackgroundSync: async () => {
      try {
        const s = await fetchAuditStats();
        if (s) setStats(s);
      } catch {
        // 静默
      }
    },
  });

  // 导出日志
  const handleExport = async (format: "json" | "csv") => {
    try {
      const result = await exportAuditLogs(format);
      if (result.content === "[DOWNLOADED_BY_BRIDGE]") {
        showBanner(`成功导出 ${format.toUpperCase()} 文件`, "info");
        return;
      }
      if (result.content) {
        const mime = format === "csv" ? "text/csv;charset=utf-8;" : "application/json;charset=utf-8;";
        const blob = new Blob([result.content], { type: mime });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.${format}`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        showBanner(`成功导出 ${format.toUpperCase()} 文件`, "info");
      }
    } catch (err) {
      showBanner(`导出失败: ${err}`, "error");
    }
  };

  // 清空日志
  const handleClear = async () => {
    try {
      const ok = await clearAuditLogs();
      if (ok) {
        showBanner("历史审计记录已清空", "info");
      } else {
        showBanner("清空操作完成", "info");
      }
      setIsClearModalOpen(false);
      setPage(1);
      loadLogs();
      loadStats();
    } catch (err) {
      showBanner(`清空失败: ${err}`, "error");
    }
  };

  const totalPages = Math.ceil(total / pageSize) || 1;

  return (
    <div className={styles.container}>
      {/* 顶部应用栏与过滤组件 */}
      <TopAppBar
        keyword={keyword}
        onKeywordChange={handleKeywordChange}
        status={status}
        onStatusChange={handleStatusChange}
        toolName={toolName}
        onToolNameChange={handleToolNameChange}
        onExport={handleExport}
        onClearClick={() => setIsClearModalOpen(true)}
        onRefresh={() => {
          loadLogs();
          loadStats();
        }}
        isLoading={isLoading}
        isBridgeReady={externalBridgeReady !== undefined ? externalBridgeReady : isBridgeAvailable()}
        autoRefresh={autoRefresh}
        onAutoRefreshChange={setAutoRefresh}
      />

      {/* 横幅消息反馈 */}
      {banner && (
        <div
          className={`${styles.banner} ${
            banner.type === "error" ? styles.bannerError : styles.bannerInfo
          }`}
        >
          <span>{banner.msg}</span>
          <button onClick={() => setBanner(null)} className={styles.bannerCloseBtn}>
            ✕
          </button>
        </div>
      )}

      {/* 指标卡片概览 */}
      <StatsOverview
        stats={stats}
        activeStatus={status}
        onSelectStatus={handleStatusChange}
      />

      {/* 审计日志列表展示 */}
      <div>
        {isLoading && logs.length === 0 ? (
          <div className={styles.loadingBox}>
            <span>🔄 正在加载审计记录...</span>
          </div>
        ) : logs.length === 0 ? (
          <div className={styles.emptyBox}>
            <div className={styles.emptyIcon}>📭</div>
            <div className={styles.emptyTitle}>暂无匹配的审计记录</div>
            <div className={styles.emptySubtitle}>
              没有检索到符合当前筛选条件或关键词的 Playwright 工具调用记录
            </div>
          </div>
        ) : (
          logs.map((item) => (
            <AuditCard
              key={item.id}
              item={item}
              onClick={(clickedItem) => setSelectedItem(clickedItem)}
              isSelected={selectedItem?.id === item.id}
            />
          ))
        )}
      </div>

      {/* 分页控制栏 */}
      {total > 0 && (
        <div className={styles.paginationBar}>
          <div className={styles.paginationSummary}>
            共 <strong>{total}</strong> 条记录，当前第 {page} / {totalPages} 页
          </div>
          <div className={styles.paginationControls}>
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className={styles.pageBtn}
            >
              ← 上一页
            </button>
            <span className={styles.pageIndicator}>
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className={styles.pageBtn}
            >
              下一页 →
            </button>

            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className={styles.pageSizeSelect}
            >
              <option value={10}>10 条/页</option>
              <option value={15}>15 条/页</option>
              <option value={20}>20 条/页</option>
              <option value={50}>50 条/页</option>
            </select>
          </div>
        </div>
      )}

      {/* 详情与快照侧边展开抽屉 */}
      <SideDrawer item={selectedItem} onClose={() => setSelectedItem(null)} />

      {/* 清空确认弹窗 */}
      <ConfirmDialog
        isOpen={isClearModalOpen}
        title="清空历史审计记录"
        message="此操作将永久删除数据库中记录的所有工具调用审计日志及快照信息，且无法撤销恢复。确认继续清空吗？"
        confirmText="确认清空"
        cancelText="取消"
        isDestructive={true}
        onConfirm={handleClear}
        onCancel={() => setIsClearModalOpen(false)}
      />
    </div>
  );
};
