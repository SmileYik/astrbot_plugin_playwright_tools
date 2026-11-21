import { apiGet, apiPost } from "./client";
import type {
  AuditLogItem,
  AuditStats,
  LogsResponseData,
  QueryParams,
  ApiResponse,
} from "../types";

export const MOCK_STATS: AuditStats = {
  total: 42,
  allowed: 38,
  denied: 3,
  error: 1,
  today_count: 15,
};

export const MOCK_LOGS: AuditLogItem[] = [
  {
    id: 1,
    timestamp: "2026-11-20 18:00:22",
    session_id: "session_mock_01",
    session_name: "GitHub自动化开发会话",
    context_key: "personal:user_1001",
    sender_id: "user_1001",
    sender_name: "Alice",
    tool_name: "pw_page:navigate",
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
    timestamp: "2026-11-20 18:01:05",
    session_id: "session_mock_01",
    session_name: "GitHub自动化开发会话",
    context_key: "personal:user_1001",
    sender_id: "user_1001",
    sender_name: "Alice",
    tool_name: "pw_interact:click",
    url: "https://github.com/SmileYik/astrbot_plugin_playwright_tools",
    input_args: JSON.stringify({ ref: 2 }),
    output_result: "成功点击元素 [2] <a> Issues\n跳转至: https://github.com/SmileYik/astrbot_plugin_playwright_tools/issues",
    is_permitted: true,
    deny_reason: "",
    is_error: false,
    error_message: "",
  },
  {
    id: 3,
    timestamp: "2026-11-20 18:02:40",
    session_id: "session_mock_02",
    session_name: "安全测试会话",
    context_key: "session:group_501",
    sender_id: "user_9999",
    sender_name: "Eve",
    tool_name: "pw_page:navigate",
    url: "https://malicious-phishing-site.org",
    input_args: JSON.stringify({ url: "https://malicious-phishing-site.org" }),
    output_result: "",
    is_permitted: false,
    deny_reason: "域名不在白名单允许列表中，操作已被系统安全策略拦截",
    is_error: false,
    error_message: "",
  },
  {
    id: 4,
    timestamp: "2026-11-20 18:03:15",
    session_id: "session_mock_01",
    session_name: "GitHub自动化开发会话",
    context_key: "personal:user_1001",
    sender_id: "user_1001",
    sender_name: "Alice",
    tool_name: "pw_media:screenshot_full",
    url: "https://github.com/SmileYik/astrbot_plugin_playwright_tools",
    input_args: JSON.stringify({ target: "chat", full_page: true }),
    output_result: "[IMAGE_PATH:data/screenshots/mock_screenshot_sample.png]\n全页面长截图生成完毕，高度 3240px",
    is_permitted: true,
    deny_reason: "",
    is_error: false,
    error_message: "",
    screenshot_path: "data/screenshots/mock_screenshot_sample.png",
  },
];

export async function fetchAuditLogs(
  params: Partial<QueryParams> = {}
): Promise<LogsResponseData> {
  const query = {
    page: params.page ?? 1,
    page_size: params.page_size ?? 15,
    keyword: params.keyword ?? "",
    status: params.status ?? "all",
    tool_name: params.tool_name ?? "",
  };

  try {
    const res = await apiGet<ApiResponse<LogsResponseData>>("audit/logs", query);
    if (res && res.code === 0 && res.data) {
      return res.data;
    }
    if (res && "items" in (res as any)) {
      return res as unknown as LogsResponseData;
    }
  } catch (err) {
    console.warn("[AuditAPI] fetchAuditLogs falling back to mock:", err);
  }

  // 离线/开发环境 Mock 过滤
  let filtered = [...MOCK_LOGS];
  if (query.keyword) {
    const kw = query.keyword.toLowerCase();
    filtered = filtered.filter(
      (item) =>
        item.url.toLowerCase().includes(kw) ||
        item.session_name?.toLowerCase().includes(kw) ||
        item.tool_name.toLowerCase().includes(kw) ||
        item.sender_name?.toLowerCase().includes(kw)
    );
  }
  if (query.status && query.status !== "all") {
    if (query.status === "allowed") filtered = filtered.filter((i) => i.is_permitted && !i.is_error);
    if (query.status === "denied") filtered = filtered.filter((i) => !i.is_permitted);
    if (query.status === "error") filtered = filtered.filter((i) => i.is_error);
  }
  if (query.tool_name) {
    filtered = filtered.filter((i) => i.tool_name === query.tool_name);
  }

  return {
    total: filtered.length,
    items: filtered,
    page: query.page,
    page_size: query.page_size,
  };
}

export async function fetchAuditStats(): Promise<AuditStats> {
  try {
    const res = await apiGet<ApiResponse<AuditStats>>("audit/stats");
    if (res && res.code === 0 && res.data) {
      return res.data;
    }
    if (res && "total" in (res as any)) {
      return res as unknown as AuditStats;
    }
  } catch (err) {
    console.warn("[AuditAPI] fetchAuditStats falling back to mock:", err);
  }
  return MOCK_STATS;
}

export async function clearAuditLogs(): Promise<boolean> {
  try {
    const res = await apiPost<ApiResponse<{ cleared: number }>>("audit/clear", { confirm: true });
    return res?.code === 0;
  } catch (err) {
    console.error("[AuditAPI] clearAuditLogs failed:", err);
    throw err;
  }
}

export async function exportAuditLogs(
  format: "json" | "csv" = "json"
): Promise<{ data: string; format: string }> {
  try {
    const res = await apiGet<ApiResponse<any>>("audit/export", { format });
    if (res && res.code === 0) {
      return { data: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2), format };
    }
  } catch (err) {
    console.warn("[AuditAPI] exportAuditLogs fallback to local export:", err);
  }
  return {
    data: format === "json" ? JSON.stringify(MOCK_LOGS, null, 2) : "id,tool_name\n1,pw_page:navigate",
    format,
  };
}

export async function fetchScreenshot(path: string): Promise<string> {
  if (!path) return "";
  try {
    const res = await apiGet<ApiResponse<{ data_url: string; media_type?: string }>>(
      "audit/screenshot",
      { path, format: "data_url" }
    );
    const dataUrl = (res as any)?.data?.data_url || (res as any)?.data_url;
    if (typeof dataUrl === "string" && dataUrl.startsWith("data:")) {
      return dataUrl;
    }
  } catch (err) {
    console.warn(`[AuditAPI] fetchScreenshot(${path}) failed, using SVG preview:`, err);
  }

  // 离线环境/模拟预览 SVG
  const encodedPath = path.replace(/[<>&"]/g, "");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">
    <defs>
      <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#1e1e2d"/>
        <stop offset="100%" stop-color="#14141e"/>
      </linearGradient>
    </defs>
    <rect width="100%" height="100%" fill="url(#bg)"/>
    <rect x="20" y="20" width="760" height="410" rx="8" fill="#181824" stroke="#2d3148" stroke-width="1.5"/>
    <text x="400" y="190" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="48" text-anchor="middle" fill="#6366f1">📸</text>
    <text x="400" y="240" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="18" font-weight="600" text-anchor="middle" fill="#f8fafc">截图存档预览</text>
    <text x="400" y="275" font-family="monospace" font-size="12" text-anchor="middle" fill="#94a3b8">${encodedPath}</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
