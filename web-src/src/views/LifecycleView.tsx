import React, { useState, useEffect, useCallback } from "react";
import {
  ActiveContextItem,
  LifecycleLogItem,
} from "../types";
import { ConfirmDialog } from "../components/ConfirmDialog";

interface LifecycleViewProps {
  showBanner: (text: string, type?: "info" | "error") => void;
  isBridgeReady: boolean;
}

// 离线模式模拟数据
const MOCK_ACTIVE_CONTEXTS: ActiveContextItem[] = [
  {
    context_key: "group_1001:user_88",
    session_id: "group_1001",
    session_name: "开发架构讨论群",
    owner_id: "user_88",
    allowed_users: ["user_88", "user_99"],
    created_time: Date.now() / 1000 - 1800,
    last_active_time: Date.now() / 1000 - 120,
    tab_count: 2,
    active_tab_url: "https://github.com/SmileYik/astrbot_plugin_playwright_tools",
    tabs: [
      {
        index: 0,
        url: "https://github.com/trending",
        title: "Trending repositories on GitHub today · GitHub",
        is_active: false,
      },
      {
        index: 1,
        url: "https://github.com/SmileYik/astrbot_plugin_playwright_tools",
        title: "SmileYik/astrbot_plugin_playwright_tools: AstrBot Playwright Tool Plugin",
        is_active: true,
      },
    ],
  },
  {
    context_key: "private_2002:user_77",
    session_id: "private_2002",
    session_name: "私聊: 测试员小王",
    owner_id: "user_77",
    allowed_users: ["user_77"],
    created_time: Date.now() / 1000 - 600,
    last_active_time: Date.now() / 1000 - 45,
    tab_count: 1,
    active_tab_url: "https://news.ycombinator.com",
    tabs: [
      {
        index: 0,
        url: "https://news.ycombinator.com",
        title: "Hacker News",
        is_active: true,
      },
    ],
  },
];

const MOCK_LIFECYCLE_LOGS: LifecycleLogItem[] = [
  {
    id: 101,
    timestamp: "2026-11-20 00:25:10",
    event_type: "switch",
    session_id: "group_1001",
    session_name: "开发架构讨论群",
    context_key: "group_1001:user_88",
    owner_id: "user_88",
    operator_id: "user_88",
    details: JSON.stringify({ tab_index: 1, title: "SmileYik/astrbot_plugin_playwright_tools" }),
  },
  {
    id: 100,
    timestamp: "2026-11-20 00:20:00",
    event_type: "join",
    session_id: "group_1001",
    session_name: "开发架构讨论群",
    context_key: "group_1001:user_88",
    owner_id: "user_88",
    operator_id: "user_99",
    details: JSON.stringify({ added_user: "user_99", reason: "collab_request" }),
  },
  {
    id: 99,
    timestamp: "2026-11-20 00:15:00",
    event_type: "create",
    session_id: "group_1001",
    session_name: "开发架构讨论群",
    context_key: "group_1001:user_88",
    owner_id: "user_88",
    operator_id: "user_88",
    details: JSON.stringify({ browser_type: "chromium", headless: true }),
  },
  {
    id: 98,
    timestamp: "2026-11-20 00:10:00",
    event_type: "timeout",
    session_id: "group_1002",
    session_name: "已闲置群组",
    context_key: "group_1002:user_33",
    owner_id: "user_33",
    operator_id: "system_cleaner",
    details: JSON.stringify({ idle_minutes: 10, reason: "idle_cleanup" }),
  },
];

function formatTime(val?: number | string): string {
  if (!val) return "未知";
  if (typeof val === "number") {
    const ms = val < 10000000000 ? val * 1000 : val;
    return new Date(ms).toLocaleString("zh-CN", { hour12: false });
  }
  return String(val);
}

function getEventBadgeStyle(type: string): { bg: string; color: string; label: string } {
  switch (type) {
    case "create":
      return { bg: "var(--color-success-bg)", color: "var(--color-success)", label: "创建会话" };
    case "close":
      return { bg: "var(--color-surface-container-high)", color: "var(--color-text-secondary)", label: "正常关闭" };
    case "timeout":
      return { bg: "var(--color-warning-bg)", color: "var(--color-warning)", label: "空闲超时" };
    case "join":
      return { bg: "var(--color-info-bg)", color: "var(--color-info)", label: "加入协作者" };
    case "switch":
      return { bg: "var(--color-primary-container)", color: "var(--color-on-primary-container)", label: "切换标签页" };
    case "force_kill":
      return { bg: "var(--color-error-bg)", color: "var(--color-error)", label: "强制关闭" };
    default:
      return { bg: "var(--color-surface-container)", color: "var(--color-text)", label: type };
  }
}

export const LifecycleView: React.FC<LifecycleViewProps> = ({
  showBanner,
  isBridgeReady,
}) => {
  // 活跃上下文状态
  const [activeContexts, setActiveContexts] = useState<ActiveContextItem[]>([]);
  const [isActiveLoading, setIsActiveLoading] = useState(false);

  // 生命周期日志状态
  const [logs, setLogs] = useState<LifecycleLogItem[]>([]);
  const [totalLogs, setTotalLogs] = useState(0);
  const [isLogsLoading, setIsLogsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [eventType, setEventType] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [searchInput, setSearchInput] = useState("");

  // 强行关闭确认弹窗
  const [killTargetKey, setKillTargetKey] = useState<string | null>(null);

  // 截图预览弹窗状态
  const [previewScreenshotUrl, setPreviewScreenshotUrl] = useState<string | null>(null);
  const [previewScreenshotTitle, setPreviewScreenshotTitle] = useState<string>("");
  const [isCapturingShot, setIsCapturingShot] = useState(false);

  // 拉取活跃上下文
  const fetchActiveContexts = useCallback(async () => {
    setIsActiveLoading(true);
    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
    if (bridge && typeof bridge.apiGet === "function") {
      try {
        const res = await bridge.apiGet<any>("lifecycle/active");
        const data = (res && Array.isArray((res as any).items)) ? res : (res?.data ?? res);
        if (data && Array.isArray(data.items)) {
          setActiveContexts(data.items);
        } else if (Array.isArray(data)) {
          setActiveContexts(data);
        } else {
          showBanner(res?.message || "获取活跃上下文失败", "error");
        }
      } catch (err) {
        showBanner(`请求活跃上下文异常: ${err}`, "error");
      }
    } else {
      // 离线 Mock
      setActiveContexts(MOCK_ACTIVE_CONTEXTS);
    }
    setIsActiveLoading(false);
  }, [showBanner]);

  // 拉取生命周期日志
  const fetchLifecycleLogs = useCallback(async () => {
    setIsLogsLoading(true);
    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
    if (bridge && typeof bridge.apiGet === "function") {
      try {
        const params: Record<string, any> = {
          page,
          page_size: pageSize,
        };
        if (eventType && eventType !== "all") {
          params.event_type = eventType;
        }
        if (keyword.trim()) {
          params.keyword = keyword.trim();
        }
        const res = await bridge.apiGet<any>("lifecycle/logs", params);
        const data = (res && Array.isArray((res as any).items)) ? res : (res?.data ?? res);
        if (data && Array.isArray(data.items)) {
          setLogs(data.items);
          setTotalLogs(data.total || 0);
        } else {
          showBanner(res?.message || "获取生命周期历史失败", "error");
        }
      } catch (err) {
        showBanner(`请求生命周期日志异常: ${err}`, "error");
      }
    } else {
      // 离线 Mock
      let filtered = [...MOCK_LIFECYCLE_LOGS];
      if (eventType !== "all") {
        filtered = filtered.filter((i) => i.event_type === eventType);
      }
      if (keyword.trim()) {
        const kw = keyword.toLowerCase();
        filtered = filtered.filter(
          (i) =>
            i.context_key.toLowerCase().includes(kw) ||
            (i.session_name && i.session_name.toLowerCase().includes(kw)) ||
            i.operator_id.toLowerCase().includes(kw) ||
            i.details.toLowerCase().includes(kw)
        );
      }
      setTotalLogs(filtered.length);
      setLogs(filtered.slice((page - 1) * pageSize, page * pageSize));
    }
    setIsLogsLoading(false);
  }, [page, pageSize, eventType, keyword, showBanner]);

  useEffect(() => {
    fetchActiveContexts();
  }, [fetchActiveContexts]);

  useEffect(() => {
    fetchLifecycleLogs();
  }, [fetchLifecycleLogs]);

  // 搜索防抖
  useEffect(() => {
    if (searchInput !== keyword) {
      const timer = setTimeout(() => {
        setKeyword(searchInput);
        setPage(1);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [searchInput, keyword]);

  // 手动截图处理
  const handleManualScreenshot = async (contextKey: string, tabIndex?: number) => {
    setIsCapturingShot(true);
    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
    if (bridge && typeof bridge.apiPost === "function") {
      try {
        const payload: Record<string, any> = { context_key: contextKey };
        if (tabIndex !== undefined) {
          payload.tab_index = tabIndex;
          payload.page_index = tabIndex;
        }
        const res = await bridge.apiPost<any>("lifecycle/screenshot", payload as any);
        const data = res?.data ?? res;
        const shotPath = data?.screenshot_path;
        if (shotPath) {
          const shotUrl = `/api/v1/plugins/extensions/astrbot_plugin_playwright_tools/audit/screenshot?path=${encodeURIComponent(shotPath)}`;
          setPreviewScreenshotUrl(shotUrl);
          setPreviewScreenshotTitle(`手动截图 - ${contextKey} (标签页 #${tabIndex ?? 0})`);
          showBanner("手动截图成功生成！", "info");
          fetchLifecycleLogs();
        } else {
          showBanner(res?.message || "手动截图未返回保存路径", "error");
        }
      } catch (err) {
        showBanner(`手动截图失败: ${err}`, "error");
      }
    } else {
      // 离线模式模拟截图
      const mockSvg = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450"><rect width="800" height="450" fill="%231e293b"/><text x="400" y="200" fill="%23ffffff" font-family="sans-serif" font-size="24" text-anchor="middle">离线预览截图 (${contextKey})</text><text x="400" y="240" fill="%2394a3b8" font-family="sans-serif" font-size="16" text-anchor="middle">标签页索引: ${tabIndex ?? 0} · 捕获时间: ${new Date().toLocaleTimeString()}</text></svg>`;
      setPreviewScreenshotUrl(mockSvg);
      setPreviewScreenshotTitle(`离线预览截图 - ${contextKey}`);
      showBanner("离线模式：生成模拟快照", "info");
    }
    setIsCapturingShot(false);
  };

  // 强行关闭处理
  const handleConfirmKill = async () => {
    if (!killTargetKey) return;
    const target = killTargetKey;
    setKillTargetKey(null);

    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
    if (bridge && typeof bridge.apiPost === "function") {
      try {
        const res = await bridge.apiPost<any>("lifecycle/kill", {
          context_key: target,
        });
        if (res?.code === 0 || res?.data?.message) {
          showBanner(`成功强制关闭上下文: ${target}`, "info");
          fetchActiveContexts();
          fetchLifecycleLogs();
        } else {
          showBanner(res?.message || res?.error || "强制关闭失败", "error");
        }
      } catch (err) {
        showBanner(`强制关闭请求异常: ${err}`, "error");
      }
    } else {
      // 离线 Mock
      setActiveContexts((prev) => prev.filter((c) => c.context_key !== target));
      showBanner(`离线模式：已移除上下文 ${target}`, "info");
    }
  };

  const totalPages = Math.ceil(totalLogs / pageSize) || 1;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
      {/* 顶部工具栏与总览 */}
      <header
        style={{
          backgroundColor: "var(--color-surface)",
          borderRadius: "var(--radius-xl)",
          padding: "16px 20px",
          boxShadow: "var(--shadow-sm)",
          border: "1px solid var(--color-border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "24px" }}>🌐</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h1 style={{ fontSize: "18px", fontWeight: 700, color: "var(--color-text)" }}>
                会话生命周期管理
              </h1>
              <span
                style={{
                  fontSize: "11px",
                  padding: "1px 8px",
                  borderRadius: "var(--radius-full)",
                  backgroundColor: "var(--color-primary-container)",
                  color: "var(--color-on-primary-container)",
                  fontWeight: 600,
                }}
              >
                活跃上下文: {activeContexts.length}
              </span>
              <span
                style={{
                  fontSize: "11px",
                  padding: "1px 6px",
                  borderRadius: "var(--radius-full)",
                  backgroundColor: isBridgeReady
                    ? "var(--color-success-bg)"
                    : "var(--color-surface-container-high)",
                  color: isBridgeReady
                    ? "var(--color-success)"
                    : "var(--color-text-secondary)",
                  fontWeight: 600,
                }}
              >
                {isBridgeReady ? "● 已连接" : "○ 离线"}
              </span>
            </div>
            <p style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
              实时监控与管理活跃的浏览器上下文、标签页与生命周期事件历史
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            onClick={() => {
              fetchActiveContexts();
              fetchLifecycleLogs();
            }}
            disabled={isActiveLoading || isLogsLoading}
            style={{
              padding: "8px 16px",
              borderRadius: "var(--radius-full)",
              fontSize: "13px",
              fontWeight: 500,
              backgroundColor: "var(--color-surface-container)",
              color: "var(--color-text)",
              border: "1px solid var(--color-border)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
              cursor: "pointer",
            }}
            title="刷新全部数据"
          >
            <span
              style={{
                display: "inline-block",
                transform: isActiveLoading || isLogsLoading ? "rotate(180deg)" : "none",
                transition: "transform 0.4s",
              }}
            >
              🔄
            </span>
            刷新状态
          </button>
        </div>
      </header>

      {/* 活跃上下文监控区 (Active Contexts) */}
      <section>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "14px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h2 style={{ fontSize: "16px", fontWeight: 700, color: "var(--color-text)" }}>
              ⚡ 活跃上下文监控
            </h2>
            <span
              style={{
                fontSize: "12px",
                color: "var(--color-text-secondary)",
              }}
            >
              ({activeContexts.length} 个实例运行中)
            </span>
          </div>
        </div>

        {isActiveLoading && activeContexts.length === 0 ? (
          <div
            style={{
              padding: "36px",
              textAlign: "center",
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-xl)",
              border: "1px solid var(--color-border)",
              color: "var(--color-text-secondary)",
              fontSize: "14px",
            }}
          >
            正在获取活跃上下文...
          </div>
        ) : activeContexts.length === 0 ? (
          <div
            style={{
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-xl)",
              border: "1px dashed var(--color-border)",
              padding: "48px 24px",
              textAlign: "center",
              color: "var(--color-text-secondary)",
            }}
          >
            <div style={{ fontSize: "36px", marginBottom: "8px" }}>💤</div>
            <div style={{ fontSize: "15px", fontWeight: 600, color: "var(--color-text)" }}>
              当前全平台暂无活跃的浏览器上下文
            </div>
            <div style={{ fontSize: "13px", marginTop: "4px" }}>
              当用户或大模型调用网页工具时，系统会自动拉起并在此展示上下文与标签页状态
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {activeContexts.map((ctx) => (
              <div
                key={ctx.context_key}
                style={{
                  backgroundColor: "var(--color-surface)",
                  borderRadius: "var(--radius-xl)",
                  border: "1px solid var(--color-border)",
                  boxShadow: "var(--shadow-sm)",
                  padding: "18px 20px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "14px",
                  transition: "border-color var(--transition-fast), box-shadow var(--transition-fast)",
                }}
              >
                {/* 卡片头部信息与操作按钮 */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: "12px",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                      <span
                        style={{
                          fontSize: "14px",
                          fontWeight: 700,
                          fontFamily: "var(--font-mono)",
                          color: "var(--color-text)",
                        }}
                      >
                        {ctx.context_key}
                      </span>
                      {ctx.session_name && (
                        <span
                          style={{
                            fontSize: "12px",
                            padding: "2px 8px",
                            borderRadius: "var(--radius-sm)",
                            backgroundColor: "var(--color-surface-container-high)",
                            color: "var(--color-text)",
                            fontWeight: 500,
                          }}
                        >
                          {ctx.session_name}
                        </span>
                      )}
                      <span
                        style={{
                          fontSize: "11px",
                          padding: "2px 8px",
                          borderRadius: "var(--radius-full)",
                          backgroundColor: "var(--color-success-bg)",
                          color: "var(--color-success)",
                          fontWeight: 600,
                        }}
                      >
                        ● 活跃中
                      </span>
                    </div>

                    {/* 元数据详情 */}
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "16px",
                        flexWrap: "wrap",
                        fontSize: "12px",
                        color: "var(--color-text-secondary)",
                        marginTop: "6px",
                      }}
                    >
                      <span>
                        所有者: <strong style={{ color: "var(--color-text)" }}>{ctx.owner_id}</strong>
                      </span>
                      <span>
                        协作者:{" "}
                        <strong style={{ color: "var(--color-text)" }}>
                          {ctx.allowed_users && ctx.allowed_users.length > 0
                            ? ctx.allowed_users.join(", ")
                            : "无"}
                        </strong>
                      </span>
                      <span>
                        创建于:{" "}
                        <span style={{ color: "var(--color-text)" }}>{formatTime(ctx.created_time)}</span>
                      </span>
                      <span>
                        最近活跃:{" "}
                        <span style={{ color: "var(--color-text)" }}>{formatTime(ctx.last_active_time)}</span>
                      </span>
                      <span>
                        标签页数:{" "}
                        <strong style={{ color: "var(--color-primary)" }}>
                          {ctx.tab_count ?? ctx.tabs?.length ?? 0}
                        </strong>
                      </span>
                    </div>
                  </div>

                  {/* 针对该上下文的快捷操作 */}
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <button
                      onClick={() => handleManualScreenshot(ctx.context_key)}
                      disabled={isCapturingShot}
                      style={{
                        padding: "6px 14px",
                        borderRadius: "var(--radius-full)",
                        fontSize: "12px",
                        fontWeight: 600,
                        backgroundColor: "var(--color-primary-container)",
                        color: "var(--color-on-primary-container)",
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        cursor: "pointer",
                      }}
                      title="截取当前活跃标签页快照"
                    >
                      📸 手动截图
                    </button>

                    <button
                      onClick={() => setKillTargetKey(ctx.context_key)}
                      style={{
                        padding: "6px 14px",
                        borderRadius: "var(--radius-full)",
                        fontSize: "12px",
                        fontWeight: 600,
                        backgroundColor: "var(--color-error-bg)",
                        color: "var(--color-error)",
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        cursor: "pointer",
                      }}
                      title="强制关闭此上下文并销毁所有标签页"
                    >
                      ⛔ 强行关闭
                    </button>
                  </div>
                </div>

                {/* 标签页列表 (Tabs) */}
                <div
                  style={{
                    backgroundColor: "var(--color-surface-container)",
                    borderRadius: "var(--radius-lg)",
                    padding: "12px 14px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "8px",
                  }}
                >
                  <div
                    style={{
                      fontSize: "12px",
                      fontWeight: 600,
                      color: "var(--color-text-secondary)",
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                    }}
                  >
                    <span>📑 打开的标签页清单:</span>
                  </div>

                  {(!ctx.tabs || ctx.tabs.length === 0) ? (
                    <div style={{ fontSize: "12px", color: "var(--color-text-secondary)", padding: "4px 0" }}>
                      暂无打开的标签页
                    </div>
                  ) : (
                    ctx.tabs.map((tab) => (
                      <div
                        key={tab.index}
                        style={{
                          backgroundColor: tab.is_active ? "var(--color-surface)" : "transparent",
                          border: tab.is_active
                            ? "1px solid var(--color-primary)"
                            : "1px solid transparent",
                          borderRadius: "var(--radius-md)",
                          padding: "8px 12px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          flexWrap: "wrap",
                          gap: "8px",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0, flex: 1 }}>
                          <span
                            style={{
                              fontSize: "11px",
                              fontFamily: "var(--font-mono)",
                              fontWeight: 700,
                              color: "var(--color-text-secondary)",
                              minWidth: "20px",
                            }}
                          >
                            #{tab.index}
                          </span>

                          {tab.is_active && (
                            <span
                              style={{
                                fontSize: "11px",
                                padding: "1px 6px",
                                borderRadius: "var(--radius-full)",
                                backgroundColor: "var(--color-primary-container)",
                                color: "var(--color-on-primary-container)",
                                fontWeight: 700,
                                flexShrink: 0,
                              }}
                            >
                              激活中
                            </span>
                          )}

                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              minWidth: 0,
                              flex: 1,
                            }}
                          >
                            <span
                              style={{
                                fontSize: "13px",
                                fontWeight: tab.is_active ? 600 : 500,
                                color: "var(--color-text)",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                              title={tab.title || "无标题页"}
                            >
                              {tab.title || "(无标题页)"}
                            </span>
                            <span
                              style={{
                                fontSize: "11px",
                                fontFamily: "var(--font-mono)",
                                color: "var(--color-primary)",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                              title={tab.url}
                            >
                              {tab.url || "about:blank"}
                            </span>
                          </div>
                        </div>

                        {/* 单标签页操作 */}
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <button
                            onClick={() => handleManualScreenshot(ctx.context_key, tab.index)}
                            disabled={isCapturingShot}
                            style={{
                              padding: "4px 8px",
                              borderRadius: "var(--radius-sm)",
                              fontSize: "11px",
                              fontWeight: 500,
                              backgroundColor: "var(--color-surface-container-high)",
                              color: "var(--color-text)",
                              cursor: "pointer",
                            }}
                            title="截图该指定标签页"
                          >
                            📸 截图此页
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 生命周期事件历史 (Lifecycle Logs) */}
      <section
        style={{
          backgroundColor: "var(--color-surface)",
          borderRadius: "var(--radius-xl)",
          padding: "20px",
          boxShadow: "var(--shadow-sm)",
          border: "1px solid var(--color-border)",
          display: "flex",
          flexDirection: "column",
          gap: "16px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h2 style={{ fontSize: "16px", fontWeight: 700, color: "var(--color-text)" }}>
              📜 生命周期事件历史
            </h2>
            <span style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
              (共 {totalLogs} 条记录)
            </span>
          </div>

          {/* 筛选与搜索控件 */}
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
            {/* 搜索框 */}
            <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
              <span
                style={{
                  position: "absolute",
                  left: "10px",
                  fontSize: "12px",
                  color: "var(--color-text-secondary)",
                  pointerEvents: "none",
                }}
              >
                🔍
              </span>
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="搜索 Context Key、会话、操作人..."
                style={{
                  padding: "6px 28px 6px 30px",
                  borderRadius: "var(--radius-full)",
                  border: "1px solid var(--color-border)",
                  backgroundColor: "var(--color-surface-container)",
                  color: "var(--color-text)",
                  fontSize: "12px",
                  width: "220px",
                }}
              />
              {searchInput && (
                <button
                  onClick={() => setSearchInput("")}
                  style={{
                    position: "absolute",
                    right: "8px",
                    fontSize: "11px",
                    color: "var(--color-text-secondary)",
                    cursor: "pointer",
                  }}
                >
                  ✕
                </button>
              )}
            </div>

            {/* 事件类型选择 */}
            <select
              value={eventType}
              onChange={(e) => {
                setEventType(e.target.value);
                setPage(1);
              }}
              style={{
                padding: "6px 12px",
                borderRadius: "var(--radius-full)",
                border: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface-container)",
                color: "var(--color-text)",
                fontSize: "12px",
                cursor: "pointer",
              }}
            >
              <option value="all">所有事件类型</option>
              <option value="create">创建 (create)</option>
              <option value="close">关闭 (close)</option>
              <option value="timeout">超时释放 (timeout)</option>
              <option value="join">协作者加入 (join)</option>
              <option value="switch">切换标签页 (switch)</option>
              <option value="force_kill">强制销毁 (force_kill)</option>
            </select>
          </div>
        </div>

        {/* 表格或列表展示 */}
        {isLogsLoading && logs.length === 0 ? (
          <div
            style={{
              padding: "36px",
              textAlign: "center",
              color: "var(--color-text-secondary)",
              fontSize: "13px",
            }}
          >
            正在拉取生命周期历史...
          </div>
        ) : logs.length === 0 ? (
          <div
            style={{
              padding: "40px 20px",
              textAlign: "center",
              color: "var(--color-text-secondary)",
              border: "1px dashed var(--color-border)",
              borderRadius: "var(--radius-lg)",
            }}
          >
            <div style={{ fontSize: "28px", marginBottom: "6px" }}>📭</div>
            <div style={{ fontSize: "14px", fontWeight: 600 }}>暂无匹配的生命周期记录</div>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "13px",
                textAlign: "left",
              }}
            >
              <thead>
                <tr
                  style={{
                    borderBottom: "1px solid var(--color-border)",
                    color: "var(--color-text-secondary)",
                    fontSize: "12px",
                  }}
                >
                  <th style={{ padding: "10px 12px" }}>时间戳</th>
                  <th style={{ padding: "10px 12px" }}>事件类型</th>
                  <th style={{ padding: "10px 12px" }}>Context Key</th>
                  <th style={{ padding: "10px 12px" }}>会话 / 操作人</th>
                  <th style={{ padding: "10px 12px" }}>事件详情 (Details)</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((item) => {
                  const badge = getEventBadgeStyle(item.event_type);
                  return (
                    <tr
                      key={item.id}
                      style={{
                        borderBottom: "1px solid var(--color-border)",
                        transition: "background var(--transition-fast)",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.backgroundColor = "var(--color-surface-container)")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.backgroundColor = "transparent")
                      }
                    >
                      <td
                        style={{
                          padding: "12px",
                          fontFamily: "var(--font-mono)",
                          fontSize: "12px",
                          whiteSpace: "nowrap",
                          color: "var(--color-text-secondary)",
                        }}
                      >
                        {item.timestamp}
                      </td>
                      <td style={{ padding: "12px", whiteSpace: "nowrap" }}>
                        <span
                          style={{
                            padding: "3px 8px",
                            borderRadius: "var(--radius-full)",
                            backgroundColor: badge.bg,
                            color: badge.color,
                            fontSize: "11px",
                            fontWeight: 700,
                          }}
                        >
                          {badge.label}
                        </span>
                      </td>
                      <td
                        style={{
                          padding: "12px",
                          fontFamily: "var(--font-mono)",
                          fontSize: "12px",
                          color: "var(--color-text)",
                        }}
                      >
                        {item.context_key}
                      </td>
                      <td style={{ padding: "12px" }}>
                        <div style={{ color: "var(--color-text)", fontWeight: 500 }}>
                          {item.session_name || item.session_id}
                        </div>
                        <div
                          style={{
                            fontSize: "11px",
                            color: "var(--color-text-secondary)",
                            fontFamily: "var(--font-mono)",
                          }}
                        >
                          操作人: {item.operator_id}
                        </div>
                      </td>
                      <td style={{ padding: "12px" }}>
                        <div
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontSize: "11px",
                            backgroundColor: "var(--color-surface-container-high)",
                            padding: "6px 10px",
                            borderRadius: "var(--radius-sm)",
                            maxHeight: "80px",
                            overflowY: "auto",
                            wordBreak: "break-all",
                            whiteSpace: "pre-wrap",
                            color: "var(--color-text)",
                          }}
                        >
                          {item.details || "{}"}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* 分页控制栏 */}
        {totalLogs > 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "12px",
              marginTop: "12px",
              paddingTop: "12px",
              borderTop: "1px solid var(--color-border)",
            }}
          >
            <div style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
              第 <strong>{page}</strong> / <strong>{totalPages}</strong> 页，共 <strong>{totalLogs}</strong> 条
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                style={{
                  padding: "4px 8px",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--color-border)",
                  backgroundColor: "var(--color-surface-container)",
                  color: "var(--color-text)",
                  fontSize: "12px",
                }}
              >
                <option value={10}>每页 10 条</option>
                <option value={20}>每页 20 条</option>
                <option value={50}>每页 50 条</option>
              </select>

              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                style={{
                  padding: "4px 12px",
                  borderRadius: "var(--radius-full)",
                  fontSize: "12px",
                  backgroundColor: page <= 1 ? "var(--color-surface-container)" : "var(--color-primary)",
                  color: page <= 1 ? "var(--color-text-secondary)" : "var(--color-on-primary)",
                  cursor: page <= 1 ? "not-allowed" : "pointer",
                  fontWeight: 500,
                }}
              >
                上一页
              </button>

              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                style={{
                  padding: "4px 12px",
                  borderRadius: "var(--radius-full)",
                  fontSize: "12px",
                  backgroundColor: page >= totalPages ? "var(--color-surface-container)" : "var(--color-primary)",
                  color: page >= totalPages ? "var(--color-text-secondary)" : "var(--color-on-primary)",
                  cursor: page >= totalPages ? "not-allowed" : "pointer",
                  fontWeight: 500,
                }}
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </section>

      {/* 强行关闭二次确认弹窗 */}
      <ConfirmDialog
        isOpen={killTargetKey !== null}
        title="确认强制关闭该浏览器上下文？"
        message={`确定要强制关闭上下文 [${killTargetKey}] 吗？当前该上下文下的所有标签页与后台浏览器进程资源将被立即释放，该操作不可撤销。`}
        confirmText="确认强行关闭"
        cancelText="取消"
        isDestructive={true}
        onConfirm={handleConfirmKill}
        onCancel={() => setKillTargetKey(null)}
      />

      {/* 手动截图预览模态框 */}
      {previewScreenshotUrl && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 2500,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(0, 0, 0, 0.55)",
            backdropFilter: "blur(2px)",
          }}
          onClick={() => setPreviewScreenshotUrl(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-2xl)",
              padding: "20px",
              maxWidth: "850px",
              width: "90%",
              maxHeight: "90vh",
              display: "flex",
              flexDirection: "column",
              gap: "14px",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--color-text)" }}>
                {previewScreenshotTitle || "📸 手动截图预览"}
              </div>
              <button
                onClick={() => setPreviewScreenshotUrl(null)}
                style={{
                  width: "32px",
                  height: "32px",
                  borderRadius: "var(--radius-full)",
                  backgroundColor: "var(--color-surface-container)",
                  color: "var(--color-text-secondary)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "16px",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>

            <div
              style={{
                flex: 1,
                overflow: "auto",
                backgroundColor: "var(--color-surface-container)",
                borderRadius: "var(--radius-lg)",
                padding: "12px",
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              <img
                src={previewScreenshotUrl}
                alt="截图预览"
                style={{
                  maxWidth: "100%",
                  maxHeight: "65vh",
                  objectFit: "contain",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--color-border)",
                }}
              />
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <a
                href={previewScreenshotUrl}
                target="_blank"
                rel="noreferrer"
                style={{
                  padding: "8px 16px",
                  borderRadius: "var(--radius-full)",
                  fontSize: "13px",
                  fontWeight: 500,
                  backgroundColor: "var(--color-surface-container)",
                  color: "var(--color-text)",
                  textDecoration: "none",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                }}
              >
                在新标签打开 ↗
              </a>
              <a
                href={previewScreenshotUrl}
                download={`screenshot-${Date.now()}.png`}
                style={{
                  padding: "8px 16px",
                  borderRadius: "var(--radius-full)",
                  fontSize: "13px",
                  fontWeight: 600,
                  backgroundColor: "var(--color-primary)",
                  color: "var(--color-on-primary)",
                  textDecoration: "none",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                }}
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
