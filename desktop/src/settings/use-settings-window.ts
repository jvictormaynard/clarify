import { useEffect, useRef, useState, type RefObject } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

/** Own native close requests without moving drafts or persistence into the window. */
export function useSettingsWindow(
  dirty: RefObject<boolean>,
  onError: (message: string) => void,
) {
  const [closing, setClosing] = useState(false);
  const allowClose = useRef(false);

  const closeWindow = async () => {
    if (isTauri()) {
      allowClose.current = true;
      try {
        await getCurrentWindow().close();
      } catch (error) {
        allowClose.current = false;
        onError(String(error));
      }
    }
    setClosing(false);
  };

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
      void listener.then((unlisten) => unlisten()).catch(() => {});
    };
  }, [onError]);

  useEffect(() => {
    if (closing && !dirty.current) void closeWindow();
  }, [closing]);

  return { closing, setClosing, closeWindow };
}
