import { electron, nativeWindow, windowAction } from "../platform";
import { t } from "../i18n";
import { useEffect, useState, type ReactNode } from "react";
import { Minus, Square, Copy, X } from "lucide-react";
import { Button } from "./primitives/button";
import logo from "../../assets/clarify.png";

export function Titlebar({
  onClose,
  onError,
  pageLabel,
  showBrand = true,
  actions,
  navigation,
}: {
  onClose: () => void;
  onError: (message: string) => void;
  pageLabel?: string;
  showBrand?: boolean;
  actions?: ReactNode;
  navigation?: ReactNode;
}) {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!nativeWindow()) return;
    let live = true;
    const sync = async () => {
      try {
        const value = await windowAction("isMaximized");
        if (live) setMaximized(!!value);
      } catch (error) {
        if (live) onError(String(error));
      }
    };
    void sync();
    const unsubscribe = electron()?.onWindow(event => { if (event === 'resized') void sync(); });
    return () => {
      live = false;
      unsubscribe?.();
    };
  }, [onError]);
  const action = async (command: "minimize" | "toggleMaximize") => {
    if (!nativeWindow()) return;
    try {
      await windowAction(command);
      setMaximized(!!(await windowAction("isMaximized")));
    } catch (error) {
      onError(String(error));
    }
  };
  return (
    <div className={`titlebar${showBrand ? "" : " titlebar-standalone"}`} data-desktop-drag-region data-maximized={maximized}>
      {navigation}
      {showBrand && <div className="titlebar-brand" data-desktop-drag-region><img
        className="titlebar-logo"
        src={logo}
        alt="Clarify"
        draggable={false}
      /><span data-desktop-drag-region>Clarify</span></div>}
      {pageLabel && <div className="titlebar-context" data-desktop-drag-region><span data-desktop-drag-region>{pageLabel}</span></div>}
      <div className="titlebar-actions">{actions}</div>
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
          aria-label={t("Fechar janela")}
          onClick={onClose}
        >
          <X className="size-4" size={16} />
        </Button>
      </div>
    </div>
  );
}
