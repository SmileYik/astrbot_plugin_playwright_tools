export interface AuditLogItem {
  id: number;
  timestamp: string;
  session_id: string;
  session_name: string;
  context_key: string;
  sender_id: string;
  sender_name: string;
  tool_name: string;
  url: string;
  input_args: string;
  output_result: string;
  is_permitted: boolean;
  deny_reason: string;
  is_error: boolean;
  error_message: string;
  screenshot_path?: string;
}

export interface AuditStats {
  total: number;
  allowed: number;
  denied: number;
  error: number;
  today_count: number;
}

export interface QueryParams {
  page: number;
  page_size: number;
  keyword: string;
  status: "all" | "allowed" | "denied" | "error";
  tool_name: string;
}

export type ApiResponse<T> = T & { code?: number; data?: T; message?: string };

export interface LogsResponseData {
  total: number;
  items: AuditLogItem[];
  page: number;
  page_size: number;
}

export interface ActiveTabItem {
  index: number;
  url: string;
  title: string;
  is_active: boolean;
}

export interface ActiveContextItem {
  context_key: string;
  session_id: string;
  session_name?: string;
  owner_id: string;
  allowed_users: string[];
  created_time?: number;
  last_active_time?: number;
  tab_count: number;
  active_tab_url: string;
  tabs: ActiveTabItem[];
}

export interface LifecycleLogItem {
  id: number;
  timestamp: string;
  event_type: "create" | "close" | "timeout" | "join" | "switch" | "force_kill" | string;
  session_id: string;
  session_name?: string;
  context_key: string;
  owner_id: string;
  operator_id: string;
  details: string;
}

export interface ActiveContextsResponseData {
  total: number;
  items: ActiveContextItem[];
}

export interface LifecycleLogsResponseData {
  total: number;
  items: LifecycleLogItem[];
  page: number;
  page_size: number;
}
