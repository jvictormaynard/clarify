import { useLayoutEffect, useState, type ReactNode } from "react";
import { t } from "../i18n";
import { Button } from "./ui";
import { Dialog, DialogPopup, DialogTitle, DialogDescription } from "./primitives/dialog";

export function LibraryEditor({ open, title, snippet = false, valid, error, dirty, registerCloseGuard, onClose, onApply, children }: {
  open: boolean; title: string; snippet?: boolean; valid: boolean; error: string; dirty: boolean;
  registerCloseGuard: (guard: () => boolean) => () => void;
  onClose: () => void; onApply: () => void; children: ReactNode;
}) {
  const [closeBlocked, setCloseBlocked] = useState(false);
  useLayoutEffect(() => {
    setCloseBlocked(false);
    if (!open || !dirty) return;
    return registerCloseGuard(() => { setCloseBlocked(true); return true; });
  }, [open, dirty, registerCloseGuard]);
  return <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
    <DialogPopup bottomStickOnMobile={false} showCloseButton={false}
      className={`library-editor${snippet ? " library-editor-snippet" : ""}`}>
      <form onSubmit={event => { event.preventDefault(); if (valid) onApply(); }}
        onKeyDown={event => {
          if (snippet && event.key === "Enter" && !event.ctrlKey && !event.metaKey && event.target instanceof HTMLInputElement) {
            event.preventDefault();
          }
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
            event.preventDefault(); if (valid) onApply();
          }
        }}>
        <div><DialogTitle className="library-editor-title">{title}</DialogTitle>
          <DialogDescription className="library-editor-description">{t("Use Salvar para aplicar ou Descartar para cancelar.")}</DialogDescription></div>
        <div className="library-editor-fields">{children}</div>
        {(error || closeBlocked) && <p className="error" role="alert">{error || t("Aplique ou cancele o editor antes de fechar.")}</p>}
        <div className="library-editor-actions">
          <Button onClick={onClose}>{t("Cancelar")}</Button>
          <Button type="submit" variant="primary" disabled={!valid}>{t("Aplicar")}</Button>
        </div>
      </form>
    </DialogPopup>
  </Dialog>;
}
