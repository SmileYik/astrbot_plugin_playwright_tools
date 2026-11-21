import type { AstrBotPluginViewBridge } from "../astrbot-bridge";

export function getBridge(): AstrBotPluginViewBridge | null {
  if (typeof window !== "undefined") {
    return window.AstrBotPluginView || window.AstrBotPluginPage || null;
  }
  return null;
}

export function isBridgeAvailable(): boolean {
  return getBridge() !== null;
}

export async function apiGet<T = any>(
  endpoint: string,
  params?: Record<string, any>
): Promise<T | null> {
  const bridge = getBridge();
  if (!bridge) {
    return null;
  }
  try {
    return await bridge.apiGet<T>(endpoint, params);
  } catch (err) {
    console.warn(`[API] GET ${endpoint} failed, error:`, err);
    throw err;
  }
}

export async function apiPost<T = any>(
  endpoint: string,
  body?: any
): Promise<T | null> {
  const bridge = getBridge();
  if (!bridge) {
    return null;
  }
  try {
    return await bridge.apiPost<T>(endpoint, body);
  } catch (err) {
    console.warn(`[API] POST ${endpoint} failed, error:`, err);
    throw err;
  }
}
