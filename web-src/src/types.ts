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

export interface ApiResponse<T> {
  code: number;
  data: T;
  message?: string;
}

export interface LogsResponseData {
  total: number;
  items: AuditLogItem[];
  page: number;
  page_size: number;
}
