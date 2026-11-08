import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Field, Section, Toggle } from "../components/ui";

export function PrivacyPage({ controller }: SettingsPageProps) {
  const { state, run, retention, setRetention, navigate } = controller;
  const managed = !!(state.accountState?.managed || state.accountState?.signedIn);
  return <Section title={t("Histórico")}>
    {managed ? <>
      <p className="hint">{t("O histórico está vinculado à sua conta. Gerencie os registros em Histórico.")}</p>
      <Button variant="text" onClick={() => void navigate("history")}>{t("Abrir histórico")}</Button>
    </> : <>
      <Toggle title={t("Salvar histórico")} hint={t("Mantenha suas transcrições neste computador.")}
        checked={state.historyEnabled} onChange={value => void run("setHistoryEnabled", value)} />
      {state.historyEnabled && <Field title={t("Retenção do histórico")}
        hint={t("Em dias. Deixe vazio para não definir um prazo.")} type="number" min="0" max="3650"
        value={retention} onChange={event => setRetention(event.target.value)} />}
    </>}
  </Section>;
}
