import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, Copy, X } from "lucide-react";
import logo from "../src-tauri/icons/clarify.png";

export function Titlebar({ onClose, onError }: { onClose: () => void; onError: (message: string) => void }) {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    const window = getCurrentWindow();
    let live = true;
    const sync = async () => {
      try { const value = await window.isMaximized(); if (live) setMaximized(value); }
      catch (error) { if (live) onError(String(error)); }
    };
    void sync();
    const listener = window.onResized(() => void sync());
    return () => { live = false; void listener.then(unlisten => unlisten()).catch(() => {}); };
  }, [onError]);
  const action = async (command: "minimize" | "toggleMaximize") => {
    if (!isTauri()) return;
    try { await getCurrentWindow()[command](); }
    catch (error) { onError(String(error)); }
  };
  return <div className="titlebar" data-tauri-drag-region>
    <img className="titlebar-logo" src={logo} alt="Clarify" draggable={false} />
    <div className="window-controls">
      <button aria-label="Minimizar" onClick={() => void action("minimize")}><Minus size={14} /></button>
      <button aria-label={maximized ? "Restaurar janela" : "Maximizar"} onClick={() => void action("toggleMaximize")}>{maximized ? <Copy size={12} /> : <Square size={12} />}</button>
      <button className="window-close" aria-label="Fechar configurações" onClick={onClose}><X size={16} /></button>
    </div>
  </div>;
}
