import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

/** Own native close intent; persistence and draft ownership stay in the controller. */
export function useSettingsWindow(
  dirty: RefObject<boolean>,
  onError: (message: string) => void,
  awaitAcceptedOperations: (isCurrent: () => boolean) => Promise<boolean>,
) {
  const [request, updateRequest] = useState<number | null>(null);
  const closeRequest = useRef<number | null>(null);
  const hasUnsavedChanges = dirty.current;
  const generation = useRef(0);
  const allowClose = useRef(false);
  const activeAttempt = useRef<{ request: number; promise: Promise<void> } | null>(null);
  const setClosing = useCallback((value: boolean) => {
    closeRequest.current = value ? ++generation.current : null;
    updateRequest(closeRequest.current);
  }, []);

  const closeWindow = useCallback(async (expected: number, canClose = () => !dirty.current) => {
    if (activeAttempt.current?.request === expected) return activeAttempt.current.promise;
    const attempt = (async () => {
      try {
        const succeeded = await awaitAcceptedOperations(() => closeRequest.current === expected);
        if (closeRequest.current !== expected) return;
        if (!succeeded) {
          setClosing(false);
          return;
        }
        if (!canClose()) return;
        if (isTauri()) {
          allowClose.current = true;
          await getCurrentWindow().close();
        }
        setClosing(false);
      } catch (error) {
        allowClose.current = false;
        if (closeRequest.current === expected) setClosing(false);
        onError(String(error));
      }
    })();
    activeAttempt.current = { request: expected, promise: attempt };
    try { await attempt; }
    finally { if (activeAttempt.current?.promise === attempt) activeAttempt.current = null; }
  }, [awaitAcceptedOperations, dirty, onError, setClosing]);

  useEffect(() => {
    if (!isTauri()) return;
    let live = true;
    const listener = getCurrentWindow().onCloseRequested((event) => {
      if (allowClose.current) return;
      event.preventDefault();
      setClosing(true);
    });
    void listener.catch((error) => {
      if (live) onError(String(error));
    });
    return () => {
      live = false;
      closeRequest.current = null;
      void listener.then((unlisten) => unlisten()).catch(() => {});
    };
  }, [onError, setClosing]);

  useEffect(() => {
    if (request !== null && !dirty.current) void closeWindow(request);
  }, [request, closeWindow, hasUnsavedChanges]);

  return { closing: request !== null, setClosing, closeWindow, closeRequest };
}
