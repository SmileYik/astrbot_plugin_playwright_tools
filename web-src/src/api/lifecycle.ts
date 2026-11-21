import { apiGet, apiPost } from "./client";
import { fetchScreenshot } from "./audit";
import type {
  ActiveContextItem,
  ActiveContextsResponseData,
  LifecycleLogsResponseData,
  ApiResponse,
} from "../types";

export async function fetchActiveContexts(
  includeAll: boolean = false
): Promise<ActiveContextItem[]> {
  const endpoint = includeAll ? "lifecycle/contexts/all" : "lifecycle/contexts";
  try {
    const res = await apiGet<ApiResponse<ActiveContextsResponseData>>(endpoint);
    if (res && res.code === 0 && res.data?.items) {
      return res.data.items;
    }
    if (res && Array.isArray((res as any).items)) {
      return (res as any).items;
    }
  } catch (err) {
    console.warn(`[LifecycleAPI] ${endpoint} error:`, err);
  }
  return [];
}

export async function fetchLifecycleLogs(params: {
  page?: number;
  page_size?: number;
  keyword?: string;
  event_type?: string;
}): Promise<LifecycleLogsResponseData> {
  const query = {
    page: params.page ?? 1,
    page_size: params.page_size ?? 10,
    keyword: params.keyword ?? "",
    event_type: params.event_type ?? "all",
  };

  try {
    const res = await apiGet<ApiResponse<LifecycleLogsResponseData>>("lifecycle/logs", query);
    if (res && res.code === 0 && res.data) {
      return res.data;
    }
    if (res && "items" in (res as any)) {
      return res as unknown as LifecycleLogsResponseData;
    }
  } catch (err) {
    console.warn("[LifecycleAPI] fetchLifecycleLogs error:", err);
  }

  return {
    total: 0,
    items: [],
    page: query.page,
    page_size: query.page_size,
  };
}

export async function killContext(
  contextKey: string,
  force: boolean = false
): Promise<boolean> {
  try {
    const res = await apiPost<ApiResponse<any>>("lifecycle/kill", {
      context_key: contextKey,
      force,
    });
    return res?.code === 0;
  } catch (err) {
    console.error(`[LifecycleAPI] killContext(${contextKey}) failed:`, err);
    throw err;
  }
}

export async function triggerManualScreenshot(
  contextKey: string,
  tabIndex?: number
): Promise<string> {
  try {
    const payload: { context_key: string; tab_index?: number } = {
      context_key: contextKey,
    };
    if (typeof tabIndex === "number") {
      payload.tab_index = tabIndex;
    }
    const res = await apiPost<ApiResponse<{ screenshot_path: string }>>(
      "lifecycle/screenshot",
      payload
    );
    const data = (res as any)?.data || res;
    const shotPath = data?.screenshot_path;
    if (shotPath) {
      return await fetchScreenshot(shotPath);
    }
  } catch (err) {
    console.warn(`[LifecycleAPI] triggerManualScreenshot(${contextKey}) failed:`, err);
  }

  return "";
}
