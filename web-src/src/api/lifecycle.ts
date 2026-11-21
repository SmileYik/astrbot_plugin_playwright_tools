import { apiGet, apiPost } from "./client";
import { fetchScreenshot } from "./audit";
import type {
  ActiveContextItem,
  ActiveContextsResponseData,
  LifecycleLogsResponseData,
  ApiResponse,
} from "../types";

export async function fetchActiveContexts(
  _includeAll: boolean = false
): Promise<ActiveContextItem[]> {
  const endpoint = "lifecycle/active";
  try {
    const res = await apiGet<ApiResponse<ActiveContextsResponseData> | any>(endpoint);
    if (res && Array.isArray(res.items)) {
      return res.items;
    }
    if (res && res.data && Array.isArray(res.data.items)) {
      return res.data.items;
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
