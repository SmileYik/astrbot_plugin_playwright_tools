import { apiGet, apiPost } from "./client";
import { fetchScreenshot } from "./audit";
import type {
  ActiveContextItem,
  ActiveContextsResponseData,
  LifecycleLogItem,
  LifecycleLogsResponseData,
  ApiResponse,
} from "../types";

export const MOCK_ACTIVE_CONTEXTS: ActiveContextItem[] = [
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

export const MOCK_LIFECYCLE_LOGS: LifecycleLogItem[] = [
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
    details: JSON.stringify({ mode: "personal", init_url: "about:blank" }),
  },
];

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
    console.warn(`[LifecycleAPI] ${endpoint} failed, falling back to mock:`, err);
  }
  return MOCK_ACTIVE_CONTEXTS;
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
    console.warn("[LifecycleAPI] fetchLifecycleLogs failed, falling back to mock:", err);
  }

  let filtered = [...MOCK_LIFECYCLE_LOGS];
  if (query.keyword) {
    const kw = query.keyword.toLowerCase();
    filtered = filtered.filter(
      (item) =>
        item.context_key.toLowerCase().includes(kw) ||
        item.session_id.toLowerCase().includes(kw) ||
        item.operator_id.toLowerCase().includes(kw)
    );
  }
  if (query.event_type && query.event_type !== "all") {
    filtered = filtered.filter((item) => item.event_type === query.event_type);
  }

  return {
    total: filtered.length,
    items: filtered,
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

  // 回退至 SVG 截图预览
  return await fetchScreenshot(`data/screenshots/manual_${contextKey}_tab${tabIndex ?? 0}.png`);
}
