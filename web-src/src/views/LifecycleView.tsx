import React, { useState, useEffect, useCallback } from "react";
import { ActiveContextItem, LifecycleLogItem } from "../types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useAutoStream } from "../hooks/useAutoStream";
import {
  fetchActiveContexts,
  fetchLifecycleLogs,
  killContext,
  triggerManualScreenshot,
  isBridgeAvailable,
} from "../api";
import styles from "./LifecycleView.module.css";

interface LifecycleViewProps {
  showBanner?: (msg: string, type?: "info" | "error") => void;
  isBridgeReady?: boolean;
}

export const LifecycleView: React.FC<LifecycleViewProps> = ({
  showBanner: externalShowBanner,
  isBridgeReady: externalBridgeReady,
}) => {
  const [activeContexts, setActiveContexts] = useState<ActiveContextItem[]>([]);
  const [isActiveLoading, setIsActiveLoading] = useState<boolean>(false);
  const [includeAll, setIncludeAll] = useState<boolean>(false);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  const [lifecycleLogs, setLifecycleLogs] = useState<LifecycleLogItem[]>([]);
  const [isLogsLoading, setIsLogsLoading] = useState<boolean>(false);
  const [totalLogs, setTotalLogs] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);
  const [logKeyword, setLogKeyword] = useState<string>("");
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("all");

  const [killModalTarget, setKillModalTarget] = useState<{
    contextKey: string;
    isForce: boolean;
  } | null>(null);

  const [previewScreenshotUrl, setPreviewScreenshotUrl] = useState<string | null>(null);
  const [previewScreenshotTitle, setPreviewScreenshotTitle] = useState<string>("");

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

  // 加载活跃上下文
  const loadContexts = useCallback(async () => {
    setIsActiveLoading(true);
    try {
      const items = await fetchActiveContexts(includeAll);
      setActiveContexts(items);
    } catch (err) {
      showBanner(`获取上下文失败: ${err}`, "error");
    } finally {
      setIsActiveLoading(false);
    }
  }, [includeAll, showBanner]);

  // 加载生命周期日志
  const loadLogs = useCallback(async () => {
    setIsLogsLoading(true);
    try {
      const data = await fetchLifecycleLogs({
        page,
        page_size: pageSize,
        keyword: logKeyword.trim(),
        event_type: eventTypeFilter,
      });
      setLifecycleLogs(data.items || []);
      setTotalLogs(data.total || 0);
    } catch (err) {
      showBanner(`获取生命周期日志失败: ${err}`, "error");
    } finally {
      setIsLogsLoading(false);
    }
  }, [page, pageSize, logKeyword, eventTypeFilter, showBanner]);

  useEffect(() => {
    loadContexts();
  }, [loadContexts]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  // 实时流式自动更新
  useAutoStream({
    enabled: autoRefresh,
    intervalMs: 2500,
    canStream: page === 1 && !previewScreenshotUrl && !killModalTarget,
    onStreamUpdate: async () => {
      try {
        const [activeItems, logsData] = await Promise.all([
          fetchActiveContexts(includeAll).catch(() => null),
          fetchLifecycleLogs({
            page: 1,
            page_size: pageSize,
            keyword: logKeyword.trim(),
            event_type: eventTypeFilter,
          }).catch(() => null),
        ]);
        if (activeItems !== null) {
          setActiveContexts(activeItems);
        }
        if (logsData !== null && logsData.items) {
          setLifecycleLogs(logsData.items);
          setTotalLogs(logsData.total || 0);
        }
      } catch {
        // 静默
      }
    },
    onBackgroundSync: async () => {
      try {
        const activeItems = await fetchActiveContexts(includeAll);
        if (activeItems) {
          setActiveContexts(activeItems);
        }
      } catch {
        // 静默
      }
    },
  });

  // 手动截取某个活跃标签页或上下文
  const handleManualScreenshot = async (contextKey: string, tabIndex?: number) => {
    showBanner(`正在请求生成 ${contextKey} 的即时截图...`, "info");
    try {
      const shotUrl = await triggerManualScreenshot(contextKey, tabIndex);
      if (shotUrl) {
        setPreviewScreenshotUrl(shotUrl);
        setPreviewScreenshotTitle(
          `手动截图 - ${contextKey} (标签页 #${tabIndex ?? 0})`
        );
        showBanner("截图生成成功", "info");
      } else {
        showBanner("截图未返回有效图像", "error");
      }
    } catch (err) {
      showBanner(`手动截图请求失败: ${err}`, "error");
    }
  };

  // 执行终止上下文
  const executeKillContext = async () => {
    if (!killModalTarget) return;
    const { contextKey, isForce } = killModalTarget;
    try {
      await killContext(contextKey, isForce);
      showBanner(`已成功关闭上下文 ${contextKey}`, "info");
      setKillModalTarget(null);
      loadContexts();
      loadLogs();
    } catch (err) {
      showBanner(`终止上下文失败: ${err}`, "error");
    }
  };

  const formatTime = (ts?: number) => {
    if (!ts) return "--";
    const d = new Date(ts * 1000);
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
  };

  const getEventBadge = (eventType: string) => {
    const map: Record<string, { label: string; bg: string; color: string }> = {
      create: { label: "创建", bg: "var(--color-primary-container)", color: "var(--color-on-primary-container)" },
      close: { label: "正常关闭", bg: "var(--color-surface-container)", color: "var(--color-text-secondary)" },
      timeout: { label: "超时回收", bg: "var(--color-warning-bg)", color: "var(--color-warning)" },
      join: { label: "成员加入", bg: "var(--color-info-bg)", color: "var(--color-info)" },
      switch: { label: "标签切换", bg: "var(--color-secondary-container, #e8def8)", color: "var(--color-on-secondary-container, #1d192b)" },
      force_kill: { label: "强制击杀", bg: "var(--color-error-bg)", color: "var(--color-error)" },
    };
    const conf = map[eventType] || { label: eventType, bg: "var(--color-surface-container)", color: "var(--color-text)" };
    return (
      <span
        className={styles.eventBadge}
        style={{ backgroundColor: conf.bg, color: conf.color }}
      >
        {conf.label}
      </span>
    );
  };

  const totalPages = Math.ceil(totalLogs / pageSize) || 1;

  return (
    <div className={styles.container}>
      {/* 顶部总览栏 */}
      <header className={styles.header}>
        <div className={styles.headerBrand}>
          <span className={styles.brandIcon}>🌐</span>
          <div>
            <div className={styles.headerTitleRow}>
              <h1 className={styles.headerTitle}>会话生命周期管理</h1>
              <span className={`${styles.badge} ${styles.contextCountBadge}`}>
                活跃上下文: {activeContexts.length}
              </span>
              <span
                className={`${styles.badge} ${
                  (externalBridgeReady !== undefined ? externalBridgeReady : isBridgeAvailable())
                    ? styles.bridgeOnline
                    : styles.bridgeOffline
                }`}
              >
                {(externalBridgeReady !== undefined ? externalBridgeReady : isBridgeAvailable())
                  ? "● 已连接"
                  : "○ 离线"}
              </span>
            </div>
            <p className={styles.headerSubtitle}>
              实时监控与管理活跃的浏览器上下文、标签页与生命周期事件历史
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          {/* 自动更新流式开关 */}
          <label className={styles.autoRefreshLabel} title="以流的形式自动将最新的记录显示到页面中">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className={styles.autoRefreshCheckbox}
            />
            <span
              className={`${styles.streamDot} ${
                autoRefresh ? styles.streamDotActive : ""
              }`}
            />
            <span className={styles.autoRefreshText}>自动更新</span>
          </label>

          <button
            onClick={() => {
              loadContexts();
              loadLogs();
            }}
            disabled={isActiveLoading || isLogsLoading}
            className={styles.refreshBtn}
            title="刷新全部数据"
          >
            <span
              className={`${styles.refreshIcon} ${
                isActiveLoading || isLogsLoading ? styles.refreshRotating : ""
              }`}
            >
              🔄
            </span>
            刷新状态
          </button>
        </div>
      </header>

      {/* 消息反馈横幅 */}
      {banner && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: "var(--radius-lg)",
            fontSize: "13px",
            backgroundColor: banner.type === "error" ? "var(--color-error-bg)" : "var(--color-info-bg)",
            color: banner.type === "error" ? "var(--color-error)" : "var(--color-info)",
            border: `1px solid ${banner.type === "error" ? "var(--color-error)" : "var(--color-info)"}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>{banner.msg}</span>
          <button
            onClick={() => setBanner(null)}
            style={{ background: "transparent", border: "none", color: "currentColor", cursor: "pointer" }}
          >
            ✕
          </button>
        </div>
      )}

      {/* 活跃上下文监控区 */}
      <section>
        <div className={styles.sectionTitleRow}>
          <div style={{ display: "flex", alignItems: "center" }}>
            <h2 className={styles.sectionTitle}>⚡ 活跃上下文监控</h2>
            <span className={styles.sectionCount}>({activeContexts.length} 个实例运行中)</span>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", color: "var(--color-text-secondary)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={includeAll}
              onChange={(e) => setIncludeAll(e.target.checked)}
            />
            包含全局全部上下文 (全量视图)
          </label>
        </div>

        {isActiveLoading && activeContexts.length === 0 ? (
          <div className={styles.emptyCard}>
            <div className={styles.emptyCardIcon}>🔄</div>
            <div className={styles.emptyCardTitle}>正在检索活跃上下文...</div>
          </div>
        ) : activeContexts.length === 0 ? (
          <div className={styles.emptyCard}>
            <div className={styles.emptyCardIcon}>💤</div>
            <div className={styles.emptyCardTitle}>暂无活跃的浏览器会话</div>
            <div className={styles.emptyCardSubtitle}>
              所有多租户浏览器实例均已超时释放或主动关闭
            </div>
          </div>
        ) : (
          <div className={styles.contextList}>
            {activeContexts.map((ctx) => (
              <div key={ctx.context_key} className={styles.contextCard}>
                {/* 实例头部信息 */}
                <div className={styles.contextHeader}>
                  <div>
                    <div className={styles.contextMetaGroup}>
                      <span className={styles.contextKeyBadge}>{ctx.context_key}</span>
                      <span className={styles.sessionTag}>
                        💬 {ctx.session_name ? `${ctx.session_name} (${ctx.session_id})` : ctx.session_id}
                      </span>
                      <span className={styles.tabCountTag}>📑 {ctx.tab_count} 个标签页</span>
                    </div>
                    <div className={styles.contextInfoRow}>
                      <span>
                        所有者: <strong>{ctx.owner_name ? `${ctx.owner_name} (${ctx.owner_id})` : ctx.owner_id}</strong>
                      </span>
                      <span>创建时间: {formatTime(ctx.created_time)}</span>
                      <span>最后活跃: {formatTime(ctx.last_active_time)}</span>
                      <span>当前活动 URL: <strong>{ctx.active_tab_url || "(空白页)"}</strong></span>
                    </div>
                  </div>

                  <div className={styles.actionBtnGroup}>
                    <button
                      onClick={() => handleManualScreenshot(ctx.context_key)}
                      className={styles.btnPrimary}
                      title="截取当前活跃视口"
                    >
                      📸 即时截图
                    </button>
                    <button
                      onClick={() => setKillModalTarget({ contextKey: ctx.context_key, isForce: false })}
                      className={styles.btnDanger}
                      title="优雅关闭此上下文"
                    >
                      🛑 终止
                    </button>
                    <button
                      onClick={() => setKillModalTarget({ contextKey: ctx.context_key, isForce: true })}
                      className={styles.btnDanger}
                      style={{ backgroundColor: "var(--color-error)", color: "#fff" }}
                      title="强制杀死浏览器进程"
                    >
                      ⚡ 强杀
                    </button>
                  </div>
                </div>

                {/* 标签页明细 */}
                {ctx.tabs && ctx.tabs.length > 0 && (
                  <div className={styles.tabsContainer}>
                    <div className={styles.tabsTitle}>📑 运行中的标签页清单:</div>
                    <div className={styles.tabsList}>
                      {ctx.tabs.map((tab) => (
                        <div key={tab.index} className={styles.tabRow}>
                          <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: 1, overflow: "hidden" }}>
                            {tab.is_active && (
                              <span className={styles.tabActiveIndicator}>活跃</span>
                            )}
                            <span style={{ fontSize: "12px", color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)" }}>
                              #{tab.index}
                            </span>
                            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              <div className={styles.tabTitle}>{tab.title || "无标题标签页"}</div>
                              <div className={styles.tabUrl}>{tab.url}</div>
                            </div>
                          </div>
                          <button
                            onClick={() => handleManualScreenshot(ctx.context_key, tab.index)}
                            className={styles.tabBtnSmall}
                          >
                            📸 截此页
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 生命周期历史日志区 */}
      <section style={{ marginTop: "12px" }}>
        <div className={styles.sectionTitleRow}>
          <div style={{ display: "flex", alignItems: "center" }}>
            <h2 className={styles.sectionTitle}>📜 生命周期事件轨迹</h2>
            <span className={styles.sectionCount}>({totalLogs} 条记录)</span>
          </div>
        </div>

        {/* 筛选工具栏 */}
        <div className={styles.filterCard}>
          <input
            type="text"
            value={logKeyword}
            onChange={(e) => {
              setLogKeyword(e.target.value);
              setPage(1);
            }}
            placeholder="过滤上下文键、会话 ID 或操作者..."
            className={styles.inputSearch}
          />
          <select
            value={eventTypeFilter}
            onChange={(e) => {
              setEventTypeFilter(e.target.value);
              setPage(1);
            }}
            className={styles.selectEvent}
          >
            <option value="all">所有事件类型</option>
            <option value="create">创建 (create)</option>
            <option value="close">关闭 (close)</option>
            <option value="timeout">超时 (timeout)</option>
            <option value="join">加入 (join)</option>
            <option value="switch">切换 (switch)</option>
            <option value="force_kill">强杀 (force_kill)</option>
          </select>
        </div>

        {/* 日志表格 */}
        <div className={styles.logsTableCard}>
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.th}>ID</th>
                  <th className={styles.th}>时间</th>
                  <th className={styles.th}>事件类型</th>
                  <th className={styles.th}>上下文 / 会话</th>
                  <th className={styles.th}>所有者 / 操作人</th>
                  <th className={styles.th}>事件详情</th>
                </tr>
              </thead>
              <tbody>
                {isLogsLoading && lifecycleLogs.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", padding: "32px", color: "var(--color-text-secondary)" }}>
                      加载中...
                    </td>
                  </tr>
                ) : lifecycleLogs.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", padding: "32px", color: "var(--color-text-secondary)" }}>
                      暂无生命周期事件记录
                    </td>
                  </tr>
                ) : (
                  lifecycleLogs.map((log) => (
                    <tr key={log.id} className={styles.tr}>
                      <td className={styles.td} style={{ fontFamily: "var(--font-mono)" }}>#{log.id}</td>
                      <td className={styles.td} style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>{log.timestamp}</td>
                      <td className={styles.td}>{getEventBadge(log.event_type)}</td>
                      <td className={styles.td}>
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-primary)" }}>
                          {log.context_key}
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--color-text-secondary)" }}>
                          💬 {log.session_name ? `${log.session_name} (${log.session_id})` : log.session_id}
                        </div>
                      </td>
                      <td className={styles.td}>
                        <div>
                          所有者: <strong>{log.owner_name ? `${log.owner_name} (${log.owner_id})` : log.owner_id}</strong>
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--color-text-secondary)" }}>
                          操作人: {log.operator_name ? `${log.operator_name} (${log.operator_id})` : log.operator_id}
                        </div>
                      </td>
                      <td className={styles.td} style={{ fontFamily: "var(--font-mono)", fontSize: "12px", maxWidth: "260px", wordBreak: "break-all" }}>
                        {log.details || "--"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* 分页条 */}
        {totalLogs > 0 && (
          <div className={styles.paginationRow}>
            <div style={{ fontSize: "13px", color: "var(--color-text-secondary)" }}>
              共 <strong>{totalLogs}</strong> 条记录，当前第 {page} / {totalPages} 页
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className={styles.tabBtnSmall}
              >
                ← 上一页
              </button>
              <span style={{ fontSize: "13px", fontWeight: 500 }}>
                {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className={styles.tabBtnSmall}
              >
                下一页 →
              </button>

              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className={styles.selectEvent}
                style={{ padding: "4px 8px", fontSize: "12px" }}
              >
                <option value={10}>10 条/页</option>
                <option value={20}>20 条/页</option>
                <option value={50}>50 条/页</option>
              </select>
            </div>
          </div>
        )}
      </section>

      {/* 终止确认弹窗 */}
      <ConfirmDialog
        isOpen={killModalTarget !== null}
        title={killModalTarget?.isForce ? "⚡ 强制杀死浏览器上下文" : "🛑 终止浏览器上下文"}
        message={`确认${killModalTarget?.isForce ? "强制终止进程并清理" : "优雅关闭"}上下文 "${killModalTarget?.contextKey}" 吗？该上下文中的全部打开标签页与临时数据都将被销毁。`}
        confirmText={killModalTarget?.isForce ? "强制强杀" : "确认终止"}
        cancelText="取消"
        isDestructive={true}
        onConfirm={executeKillContext}
        onCancel={() => setKillModalTarget(null)}
      />

      {/* 手动截图预览模态框 */}
      {previewScreenshotUrl && (
        <div className={styles.modalOverlay} onClick={() => setPreviewScreenshotUrl(null)}>
          <div className={styles.modalDialog} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div className={styles.modalTitle}>{previewScreenshotTitle || "📸 手动截图预览"}</div>
              <button onClick={() => setPreviewScreenshotUrl(null)} className={styles.modalCloseBtn}>
                ✕
              </button>
            </div>

            <div className={styles.modalImgBox}>
              <img
                src={previewScreenshotUrl}
                alt="截图预览"
                className={styles.modalImg}
              />
            </div>

            <div className={styles.modalActions}>
              <button
                onClick={() => {
                  const w = window.open("");
                  if (w) {
                    w.document.write(
                      `<title>截图预览</title><body style="margin:0;background:#111;display:flex;align-items:center;justify-content:center;height:100vh;"><img src="${previewScreenshotUrl}" style="max-width:98%;max-height:98%;object-fit:contain;"/></body>`
                    );
                    w.document.close();
                  }
                }}
                className={styles.tabBtnSmall}
                style={{ padding: "8px 16px", borderRadius: "var(--radius-full)" }}
              >
                在新标签打开 ↗
              </button>
              <a
                href={previewScreenshotUrl}
                download={`screenshot-${Date.now()}.${previewScreenshotUrl.startsWith("data:image/svg") ? "svg" : "png"}`}
                className={styles.btnDownload}
              >
                📥 下载截图
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
