import { useState } from "react";
import { X } from "lucide-react";
import { t } from "../i18n";
import { Button as IconButton } from "./primitives/button";
import { IPhoneDemo } from "./iphone-demo";
import downloadQr from "../assets/clarify-iphone-qr.svg";
import "../styles/mobile-app-card.css";

const dismissalKey = "clarify.mobile-app-card.dismissed.v1";

export function MobileAppDownload({ compact = false }: { compact?: boolean }) {
  return <div className={`mobile-download${compact ? " compact" : ""}`}>
    <img src={downloadQr} width="112" height="112" alt={t("QR para baixar o Clarify na App Store")} />
    <div><strong>{t(compact ? "Leia com a câmera do iPhone para baixar" : "Leia com a câmera do iPhone")}</strong><p>{t(compact ? "Disponível para iOS" : "Baixe o Clarify na App Store.")}</p></div>
  </div>;
}

export function MobileAppCard({ paired }: { paired: boolean }) {
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(dismissalKey) === "true"; } catch { return false; }
  });
  if (dismissed || paired) return null;
  const dismiss = () => {
    try { localStorage.setItem(dismissalKey, "true"); } catch { /* Still dismiss for this session. */ }
    setDismissed(true);
  };
  return <aside className="mobile-app-card" aria-labelledby="mobile-app-title">
    <IPhoneDemo />
    <div className="mobile-app-content">
      <h2 id="mobile-app-title">{t("O Clarify agora também está no iPhone!")}</h2>
      <p>{t("Dite onde estiver, em qualquer app no seu iPhone.")}</p>
      <MobileAppDownload compact />
    </div>
    <IconButton size="icon" variant="ghost" className="absolute end-2 top-2" onClick={dismiss} aria-label={t("Fechar sugestão do aplicativo")}><X aria-hidden /></IconButton>
  </aside>;
}
