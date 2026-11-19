export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonArray;
export type JsonObject = { [key: string]: JsonValue };
export type JsonArray = JsonValue[];

export type QueryParams = Record<
  string,
  string | number | boolean | Array<string | number | boolean> | undefined | null
>;

export interface AstrBotPluginViewBridge<TViewData = JsonObject> {
  ready(): Promise<{
    pluginName?: string;
    viewName?: string;
    isDark?: boolean;
    data?: TViewData;
  }>;
  apiGet<TResult = unknown>(
    endpoint: string,
    params?: QueryParams,
  ): Promise<TResult>;
  apiPost<TResult = unknown>(
    endpoint: string,
    body?: JsonValue,
  ): Promise<TResult>;
}

declare global {
  interface Window {
    AstrBotPluginView?: AstrBotPluginViewBridge;
    AstrBotPluginPage?: AstrBotPluginViewBridge;
  }
}
