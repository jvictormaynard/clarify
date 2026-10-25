import { t } from "../i18n";
import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, Copy, X } from "lucide-react";
import { Button } from "./primitives/button";
import logo from "../../src-tauri/icons/clarify.png";

export function Titlebar({
  onClose,
  onError,
  pageLabel,
}: {
  onClose: () => void;
  onError: (message: string) => void;
  pageLabel?: string;
}) {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    const window = getCurrentWindow();
    let live = true;
    const sync = async () => {
      try {
        const value = await window.isMaximized();
        if (live) setMaximized(value);
      } catch (error) {
        if (live) onError(String(error));
      }
    };
    void sync();
    const listener = window.onResized(() => void sync());
    return () => {
      live = false;
      void listener.then((unlisten) => unlisten()).catch(() => {});
    };
  }, [onError]);
  const action = async (command: "minimize" | "toggleMaximize") => {
    if (!isTauri()) return;
    try {
      await getCurrentWindow()[command]();
    } catch (error) {
      onError(String(error));
    }
  };
  return (
    <div className="titlebar" data-tauri-drag-region>
      <div className="titlebar-brand" data-tauri-drag-region><img
        className="titlebar-logo"
        src={logo}
        alt="Clarify"
        draggable={false}
      /><span data-tauri-drag-region>Clarify</span></div>
      {pageLabel && <div className="titlebar-context" data-tauri-drag-region><span data-tauri-drag-region>{t("Configurações")}</span><span aria-hidden="true">/</span><span data-tauri-drag-region>{pageLabel}</span></div>}
      <div className="window-controls">
        <Button variant="ghost" size="icon" className="h-full w-11.5 sm:h-full sm:w-11.5 rounded-none border-0 p-0 hover:bg-white/5 [&:active:not([aria-haspopup])]:scale-100" aria-label={t("Minimizar")} onClick={() => void action("minimize")}>
          <Minus className="size-3.5" size={14} />
        </Button>
        <Button variant="ghost" size="icon"
          className="h-full w-11.5 sm:h-full sm:w-11.5 rounded-none border-0 p-0 hover:bg-white/5 [&:active:not([aria-haspopup])]:scale-100"
          aria-label={maximized ? t("Restaurar janela") : t("Maximizar")}
          onClick={() => void action("toggleMaximize")}
        >
          {maximized ? <Copy className="size-3" size={12} /> : <Square className="size-3" size={12} />}
        </Button>
        <Button variant="ghost" size="icon"
          className="window-close h-full w-11.5 sm:h-full sm:w-11.5 rounded-none border-0 p-0 hover:bg-[#b93640] hover:text-white [&:active:not([aria-haspopup])]:scale-100"
          aria-label={t("Fechar configurações")}
          onClick={onClose}
        >
          <X className="size-4" size={16} />
        </Button>
      </div>
    </div>
  );
}
