import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Confirm, Field, Section, Toggle } from "../components/ui";

export function PrivacyPage({ controller }: SettingsPageProps) {
  const { state, run, retention, setRetention, navigate } = controller;
  const context = state.historyState?.context || "";
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const pending = useRef(false);
  useEffect(() => setConfirmation(null), [context]);
  const clear = async () => {
    if (!confirmation || confirmation !== context || pending.current) return;
    pending.current = true;
    setDeleting(true);
    try { if (await run("clearHistory", confirmation)) setConfirmation(value => value === confirmation ? null : value); }
    finally { pending.current = false; setDeleting(false); }
  };
  const managed = !!(state.accountState?.managed || state.accountState?.signedIn);
  return <Section title={t("Histórico")}>
    {managed ? <>
      <p className="hint">{t("O histórico está vinculado à sua conta.")}</p>
      <Button variant="text" onClick={() => void navigate("history")}>{t("Abrir histórico")}</Button>
    </> : <>
      <Toggle title={t("Salvar histórico")} hint={t("Mantenha suas transcrições neste computador.")}
        checked={state.historyEnabled} onChange={value => void run("setHistoryEnabled", value)} />
      {state.historyEnabled && <Field title={t("Retenção do histórico")}
        hint={t("Em dias. Deixe vazio para não definir um prazo.")} type="number" min="0" max="3650"
        value={retention} onChange={event => setRetention(event.target.value)} />}
    </>}
    <div className="privacy-history-actions"><Button className="destructive" disabled={!context || deleting} onClick={() => setConfirmation(context)}>{t("Limpar histórico")}</Button></div>
    <Confirm open={confirmation !== null && confirmation === context} onOpenChange={open => { if (!open && !pending.current) setConfirmation(null); }}
      title={t("Limpar histórico")} description={t(managed
        ? "A exclusão das transcrições da conta será sincronizada nos seus dispositivos. Os registros locais serão removidos apenas deste computador."
        : "Esta ação remove os registros deste computador.")}>
      <Button autoFocus disabled={deleting} onClick={() => setConfirmation(null)}>{t("Cancelar")}</Button>
      <Button className="destructive" disabled={deleting || confirmation !== context} onClick={() => void clear()}>{t("Excluir")}</Button>
    </Confirm>
  </Section>;
}
