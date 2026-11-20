import { useState, useEffect, useCallback } from "react";
import "./styles/theme.css";
import { AuditLogItem, AuditStats } from "./types";
import { TopAppBar } from "./components/TopAppBar";
import { StatsOverview } from "./components/StatsOverview";
import { AuditCard } from "./components/AuditCard";
import { SideDrawer } from "./components/SideDrawer";
import { ConfirmDialog } from "./components/ConfirmDialog";

// 离线/预览模式模拟数据
const MOCK_ITEMS: AuditLogItem[] = [
  {
    id: 1,
    timestamp: "2026-11-20 00:15:30",
    session_id: "group_1001",
    session_name: "开发架构讨论群",
    context_key: "group_1001:user_88",
    sender_id: "user_88",
    sender_name: "林架构师",
    tool_name: "pw_page:open",
    url: "https://github.com/SmileYik/astrbot_plugin_playwright_tools",
    input_args: JSON.stringify({ url: "https://github.com/SmileYik/astrbot_plugin_playwright_tools" }),
    output_result: "页面加载成功 (200 OK)\n标题: SmileYik/astrbot_plugin_playwright_tools\n[1] <button> Code\n[2] <a> Issues\n[3] <a> Pull Requests",
    is_permitted: true,
    deny_reason: "",
    is_error: false,
    error_message: "",
  },
  {
    id: 2,
    timestamp: "2026-11-20 00:18:42",
    session_id: "private_2002",
    session_name: "私聊: 自动化测试机",
    context_key: "private_2002:user_99",
    sender_id: "user_99",
    sender_name: "测试机",
    tool_name: "pw_interact:click",
    url: "https://internal-bank.local/transfer",
    input_args: JSON.stringify({ ref: 42 }),
    output_result: "",
    is_permitted: false,
    deny_reason: "黑名单拦截：域名 internal-bank.local 不在允许访问的白名单中",
    is_error: false,
    error_message: "",
  },
  {
    id: 3,
    timestamp: "2026-11-20 00:22:15",
    session_id: "group_1001",
    session_name: "开发架构讨论群",
    context_key: "group_1001:user_88",
    sender_id: "user_88",
    sender_name: "林架构师",
    tool_name: "pw_media:screenshot_full",
    url: "https://github.com/trending",
    input_args: JSON.stringify({ target: "chat", max_height_px: 8000 }),
    output_result: "[IMAGE_PATH:/data/downloads/screenshot_1700000000.png]\n全页面长截图生成完毕，高度 3240px",
    is_permitted: true,
    deny_reason: "",
    is_error: false,
    error_message: "",
  },
];

export function App() {
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<AuditStats>({
    total: 0,
    allowed: 0,
    denied: 0,
    error: 0,
    today_count: 0,
  });

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<"all" | "allowed" | "denied" | "error">("all");
  const [toolName, setToolName] = useState("");

  const [selectedItem, setSelectedItem] = useState<AuditLogItem | null>(null);
  const [isClearModalOpen, setIsClearModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isBridgeReady, setIsBridgeReady] = useState(false);
  const [bannerMsg, setBannerMsg] = useState<{ text: string; type: "info" | "error" } | null>(null);

  // 初始化 Bridge 连接
  useEffect(() => {
    const initBridge = async () => {
      const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
      if (bridge && typeof bridge.ready === "function") {
        try {
          const ctx = await bridge.ready();
          if (ctx?.isDark) {
            document.documentElement.setAttribute("data-theme", "dark");
          }
          setIsBridgeReady(true);
        } catch {
          setIsBridgeReady(false);
        }
      } else {
        setIsBridgeReady(false);
      }
    };
    initBridge();
  }, []);

  const showBanner = (text: string, type: "info" | "error" = "info") => {
    setBannerMsg({ text, type });
    setTimeout(() => setBannerMsg(null), 3000);
  };

  // 获取审计列表
  const fetchLogs = useCallback(async () => {
    setIsLoading(true);
    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

    if (bridge && typeof bridge.apiGet === "function") {
      try {
        const res = await bridge.apiGet<any>("audit/logs", {
          page,
          page_size: pageSize,
          keyword: keyword.trim(),
          status,
          tool_name: toolName.trim(),
        });
        const data = (res && Array.isArray((res as any).items)) ? res : (res?.data ?? res);
        if (data && Array.isArray(data.items)) {
          setLogs(data.items);
          setTotal(data.total || 0);
        } else {
          showBanner(res?.message || "拉取日志失败", "error");
        }
      } catch (err) {
        showBanner(`接口请求异常: ${err}`, "error");
      }
    } else {
      // 离线/预览模式自动回退模拟数据过滤
      let filtered = [...MOCK_ITEMS];
      if (status !== "all") {
        if (status === "allowed") filtered = filtered.filter((i) => i.is_permitted && !i.is_error);
        if (status === "denied") filtered = filtered.filter((i) => !i.is_permitted);
        if (status === "error") filtered = filtered.filter((i) => i.is_error);
      }
      if (toolName) {
        filtered = filtered.filter((i) => i.tool_name.startsWith(toolName));
      }
      if (keyword) {
        const kw = keyword.toLowerCase();
        filtered = filtered.filter(
          (i) =>
            i.url.toLowerCase().includes(kw) ||
            i.input_args.toLowerCase().includes(kw) ||
            i.output_result.toLowerCase().includes(kw) ||
            i.session_name.toLowerCase().includes(kw) ||
            i.sender_name.toLowerCase().includes(kw)
        );
      }
      const totalCount = filtered.length;
      const sliced = filtered.slice((page - 1) * pageSize, page * pageSize);
      setLogs(sliced);
      setTotal(totalCount);
    }
    setIsLoading(false);
  }, [page, pageSize, keyword, status, toolName]);

  // 获取指标统计
  const fetchStats = useCallback(async () => {
    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
    if (bridge && typeof bridge.apiGet === "function") {
      try {
        const res = await bridge.apiGet<any>("audit/stats");
        const data = (res && typeof (res as any).total === "number") ? res : (res?.data ?? res);
        if (data && typeof data.total === "number") {
          setStats(data);
        }
      } catch {
        // 静默失败
      }
    } else {
      setStats({
        total: MOCK_ITEMS.length,
        allowed: MOCK_ITEMS.filter((i) => i.is_permitted && !i.is_error).length,
        denied: MOCK_ITEMS.filter((i) => !i.is_permitted).length,
        error: MOCK_ITEMS.filter((i) => i.is_error).length,
        today_count: MOCK_ITEMS.length,
      });
    }
  }, []);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // 导出日志
  const handleExport = async (format: "json" | "csv") => {
    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
    if (bridge && typeof bridge.apiGet === "function") {
      try {
        const res = await bridge.apiGet<any>("audit/export", {
          format,
          keyword: keyword.trim(),
          status,
          tool_name: toolName.trim(),
        });
        const content = typeof res === "string" ? res : (res?.data ?? res);
        if (content && typeof content === "string") {
          const mime = format === "csv" ? "text/csv;charset=utf-8;" : "application/json;charset=utf-8;";
          const blob = new Blob([content], { type: mime });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.${format}`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
          showBanner(`成功导出 ${format.toUpperCase()} 文件`, "info");
        } else {
          showBanner(res?.message || "导出内容为空或失败", "error");
        }
      } catch (err) {
        showBanner(`导出失败: ${err}`, "error");
      }
    } else {
      showBanner("当前处于离线模式，无法从后端生成导出文件", "error");
    }
  };

  // 清空日志
  const handleClear = async () => {
    const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
    if (bridge && typeof bridge.apiPost === "function") {
      try {
        const res = await bridge.apiPost<any>("audit/clear", {
          confirm: true,
        });
        const cleared = typeof res?.cleared === "number" ? res.cleared : res?.data?.cleared;
        if (cleared !== undefined || res?.code === 0) {
          showBanner(`已清空 ${cleared ?? 0} 条历史审计记录`, "info");
          setIsClearModalOpen(false);
          setPage(1);
          fetchLogs();
          fetchStats();
        } else {
          showBanner(res?.message || "清空失败", "error");
        }
      } catch (err) {
        showBanner(`清空请求失败: ${err}`, "error");
      }
    } else {
      setLogs([]);
      setTotal(0);
      setStats({ total: 0, allowed: 0, denied: 0, error: 0, today_count: 0 });
      setIsClearModalOpen(false);
      showBanner("离线模式：模拟数据已清空", "info");
    }
  };

  const totalPages = Math.ceil(total / pageSize) || 1;

  return (
    <div
      style={{
        maxWidth: "1140px",
        margin: "0 auto",
        padding: "24px 20px 60px 20px",
      }}
    >
      {/* 离线预览或通知气泡 */}
      {bannerMsg && (
        <div
          style={{
            position: "fixed",
            top: "20px",
            right: "20px",
            zIndex: 3000,
            padding: "12px 20px",
            borderRadius: "var(--radius-lg)",
            backgroundColor: bannerMsg.type === "error" ? "var(--color-error)" : "var(--color-primary)",
            color: "#ffffff",
            boxShadow: "var(--shadow-lg)",
            fontSize: "14px",
            fontWeight: 500,
            animation: "fadeIn 0.2s ease-in-out",
          }}
        >
          {bannerMsg.text}
        </div>
      )}

      {/* 顶部操作条 */}
      <TopAppBar
        keyword={keyword}
        onKeywordChange={(val) => {
          setKeyword(val);
          setPage(1);
        }}
        status={status}
        onStatusChange={(val) => {
          setStatus(val);
          setPage(1);
        }}
        toolName={toolName}
        onToolNameChange={(val) => {
          setToolName(val);
          setPage(1);
        }}
        onExport={handleExport}
        onClearClick={() => setIsClearModalOpen(true)}
        onRefresh={() => {
          fetchLogs();
          fetchStats();
        }}
        isLoading={isLoading}
        isBridgeReady={isBridgeReady}
      />

      {/* 指标卡片 Chips */}
      <StatsOverview
        stats={stats}
        activeStatus={status}
        onSelectStatus={(st) => {
          setStatus(st);
          setPage(1);
        }}
      />

      {/* 审计日志列表主体 */}
      <main>
        {isLoading && logs.length === 0 ? (
          <div
            style={{
              padding: "48px 24px",
              textAlign: "center",
              color: "var(--color-text-secondary)",
              fontSize: "14px",
            }}
          >
            正在拉取审计日志...
          </div>
        ) : logs.length === 0 ? (
          <div
            style={{
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-xl)",
              border: "1px dashed var(--color-border)",
              padding: "60px 24px",
              textAlign: "center",
              color: "var(--color-text-secondary)",
            }}
          >
            <div style={{ fontSize: "40px", marginBottom: "12px" }}>📭</div>
            <div style={{ fontSize: "16px", fontWeight: 600, color: "var(--color-text)" }}>
              暂无匹配的审计记录
            </div>
            <div style={{ fontSize: "13px", marginTop: "6px" }}>
              尝试调整搜索词、过滤条件，或让大模型调用网页工具产生调用记录
            </div>
          </div>
        ) : (
          <div>
            {logs.map((item) => (
              <AuditCard
                key={item.id}
                item={item}
                isSelected={selectedItem?.id === item.id}
                onClick={(it) => setSelectedItem(it)}
              />
            ))}
          </div>
        )}

        {/* 分页控制栏 */}
        {total > 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: "12px",
              marginTop: "24px",
              padding: "12px 16px",
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-xl)",
              border: "1px solid var(--color-border)",
            }}
          >
            <div style={{ fontSize: "13px", color: "var(--color-text-secondary)" }}>
              第 <strong>{page}</strong> / <strong>{totalPages}</strong> 页，共 <strong>{total}</strong> 条记录
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                style={{
                  padding: "6px 10px",
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
                <option value={100}>每页 100 条</option>
              </select>

              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                style={{
                  padding: "6px 14px",
                  borderRadius: "var(--radius-full)",
                  fontSize: "13px",
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
                  padding: "6px 14px",
                  borderRadius: "var(--radius-full)",
                  fontSize: "13px",
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
      </main>

      {/* 右侧滑出长文本检视抽屉 */}
      <SideDrawer
        item={selectedItem}
        onClose={() => setSelectedItem(null)}
      />

      {/* 清空二次确认弹窗 */}
      <ConfirmDialog
        isOpen={isClearModalOpen}
        title="确认清空所有审计记录？"
        message="此操作将永久删除全部历史工具调用的审计记录，包含所有多租户会话与历史结果快照，该操作不可逆。"
        confirmText="确认清空"
        cancelText="取消"
        isDestructive={true}
        onConfirm={handleClear}
        onCancel={() => setIsClearModalOpen(false)}
      />
    </div>
  );
}

export default App;
