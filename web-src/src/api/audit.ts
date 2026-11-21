import { apiGet, apiPost } from "./client";
import type {
  AuditStats,
  LogsResponseData,
  QueryParams,
  ApiResponse,
} from "../types";

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
    if (res && Array.isArray(res.items)) {
      return {
        total: typeof res.total === "number" ? res.total : 0,
        items: res.items,
        page: typeof res.page === "number" ? res.page : query.page,
        page_size: typeof res.page_size === "number" ? res.page_size : query.page_size,
      };
    }
    if (res && res.code === 0 && res.data && Array.isArray(res.data.items)) {
      return res.data;
    }
  } catch (err) {
    console.warn("[AuditAPI] fetchAuditLogs error:", err);
  }

  return {
    total: 0,
    items: [],
    page: query.page,
    page_size: query.page_size,
  };
}

export async function fetchAuditStats(): Promise<AuditStats> {
  try {
    const res = await apiGet<ApiResponse<AuditStats>>("audit/stats");
    if (res && typeof res.total === "number") {
      return {
        total: res.total ?? 0,
        allowed: res.allowed ?? 0,
        denied: res.denied ?? 0,
        error: res.error ?? 0,
        today_count: res.today_count ?? 0,
      };
    }
    if (res && res.code === 0 && res.data && typeof res.data.total === "number") {
      return res.data;
    }
  } catch (err) {
    console.warn("[AuditAPI] fetchAuditStats error:", err);
  }
  return {
    total: 0,
    allowed: 0,
    denied: 0,
    error: 0,
    today_count: 0,
  };
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
): Promise<{ content: string; format: string }> {
  const bridge = (window as any).AstrBotPluginPage || (window as any).AstrBotPluginView;
  if (bridge && typeof bridge.download === "function") {
    try {
      const filename = `audit-logs-${new Date().toISOString().slice(0, 10)}.${format}`;
      await bridge.download("audit/export", { format }, filename);
      return { content: "[DOWNLOADED_BY_BRIDGE]", format };
    } catch (err) {
      console.warn("[AuditAPI] bridge.download failed, falling back to apiGet:", err);
    }
  }
  const res = await apiGet<any>("audit/export", { format });
  const content = (res && typeof res.content === "string") ? res.content : (res && res.data) ? res.data : (typeof res === "string" ? res : "");
  return { content, format };
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
    console.warn(`[AuditAPI] fetchScreenshot(${path}) failed:`, err);
  }
  return "";
}
