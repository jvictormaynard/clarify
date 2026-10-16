import { useState } from "react";
import { Monitor, Smartphone, Trash2 } from "lucide-react";
import { t, uiLanguage } from "../i18n";
import { Button, Confirm } from "../components/ui";
import type { SettingsPageProps } from "../settings/use-settings";

export function HistoryPage({ controller }: SettingsPageProps) {
  const { state, run, busy } = controller;
  const [deletion, setDeletion] = useState<string | null>(null);
  const entries = state.historyEntries || [];
  const confirm = async () => {
    const ok = deletion === "all" ? await run("clearHistory")
      : deletion && await run("deleteHistoryEntry", deletion);
    if (ok) setDeletion(null);
  };
  return <>
    <p className="hint">{t(state.accountState?.signedIn
      ? "As novas transcrições da conta são sincronizadas automaticamente. Os registros antigos permanecem neste dispositivo."
      : "Seu histórico permanece somente neste computador.")}</p>
    {entries.length ? <>
      <div className="history-actions"><Button variant="text" onClick={() => setDeletion("all")}>{t("Limpar histórico")}</Button></div>
      <div className="history-list" role="list" aria-label={t("Histórico")}>
        {entries.map(entry => {
          const Device = entry.sourceDevice === "mobile" ? Smartphone : Monitor;
          return <article className="history-row" role="listitem" key={entry.id}>
            <div className="history-meta">
              <time dateTime={new Date(entry.timestamp * 1000).toISOString()}>
                {new Intl.DateTimeFormat(uiLanguage, { dateStyle: "medium", timeStyle: "short" }).format(entry.timestamp * 1000)}
              </time>
              <span><Device size={12} aria-hidden="true" />{entry.sourceDevice === "mobile" ? "Mobile" : "Desktop"}</span>
            </div>
            <p className="history-text">{entry.text || t("Sem texto")}</p>
            <Button variant="text" aria-label={t("Excluir transcrição")} onClick={() => setDeletion(entry.id)}><Trash2 size={16} /></Button>
          </article>;
        })}
      </div>
    </> : <p className="hint">{t("Nenhuma transcrição ainda.")}</p>}
    <Confirm open={deletion !== null} onOpenChange={open => { if (!open) setDeletion(null); }}
      title={t(deletion === "all" ? "Limpar histórico" : "Excluir transcrição")}
      description={t(state.accountState?.signedIn
        ? "A exclusão das transcrições da conta será sincronizada nos seus dispositivos. Os registros locais serão removidos apenas deste computador."
        : "Esta ação remove os registros deste computador.")}>
      <Button autoFocus disabled={busy} onClick={() => setDeletion(null)}>{t("Cancelar")}</Button>
      <Button className="destructive" disabled={busy} onClick={() => void confirm()}>{t("Excluir")}</Button>
    </Confirm>
  </>;
}
