import { useEffect, useRef, useState } from "react";

export interface AutoStreamOptions {
  enabled: boolean;
  intervalMs?: number;
  canStream?: boolean;
  onStreamUpdate: () => void | Promise<void>;
  onBackgroundSync?: () => void | Promise<void>;
}

export function useAutoStream({
  enabled,
  intervalMs = 2500,
  canStream = true,
  onStreamUpdate,
  onBackgroundSync,
}: AutoStreamOptions) {
  const [isLiveActive, setIsLiveActive] = useState<boolean>(enabled);
  const isUpdatingRef = useRef<boolean>(false);
  const onStreamUpdateRef = useRef(onStreamUpdate);
  const onBackgroundSyncRef = useRef(onBackgroundSync);

  useEffect(() => {
    onStreamUpdateRef.current = onStreamUpdate;
    onBackgroundSyncRef.current = onBackgroundSync;
  });

  useEffect(() => {
    setIsLiveActive(enabled);
    if (!enabled) {
      return;
    }

    const timer = window.setInterval(async () => {
      if (isUpdatingRef.current) return;
      isUpdatingRef.current = true;
      try {
        if (canStream) {
          await onStreamUpdateRef.current();
        } else if (onBackgroundSyncRef.current) {
          await onBackgroundSyncRef.current();
        }
      } catch (err) {
        console.warn("[AutoStream] Poll failed:", err);
      } finally {
        isUpdatingRef.current = false;
      }
    }, intervalMs);

    return () => {
      window.clearInterval(timer);
    };
  }, [enabled, intervalMs, canStream]);

  return { isLiveActive };
}
