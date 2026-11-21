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
    if (res && res.code === 0 && res.data) {
      return res.data;
    }
    if (res && "items" in (res as any)) {
      return res as unknown as LogsResponseData;
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
    if (res && res.code === 0 && res.data) {
      return res.data;
    }
    if (res && "total" in (res as any)) {
      return res as unknown as AuditStats;
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
): Promise<{ data: string; format: string }> {
  try {
    const res = await apiGet<ApiResponse<any>>("audit/export", { format });
    if (res && res.code === 0) {
      return { data: typeof res.data === "string" ? res.data : JSON.stringify(res.data, null, 2), format };
    }
  } catch (err) {
    console.warn("[AuditAPI] exportAuditLogs error:", err);
  }
  return {
    data: "",
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
    console.warn(`[AuditAPI] fetchScreenshot(${path}) failed:`, err);
  }
  return "";
}
