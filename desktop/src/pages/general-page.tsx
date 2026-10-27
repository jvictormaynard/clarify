import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Field, Picker, Row, Section, Toggle } from "../components/ui";
import { ComputerAccess } from "../components/computer-access";
const languageNames: Record<string, string> = {
  en: "English",
  pt: "Portuguese",
  es: "Spanish",
  de: "German",
  ru: "Russian",
};

export function GeneralPage({ controller }: SettingsPageProps) {
  const { state, run, retention, setRetention } = controller;
  return (
    <>
      <Section title={t("Preferências")}>
        <Row title={t("Idioma do texto")}>
          <Picker
            label={t("Idioma")}
            value={state.language}
            options={state.languages.map((id) => ({
              id,
              label: languageNames[id] || id,
            }))}
            onChange={(v) => void run("setLanguage", v)}
          />
        </Row>
        <Toggle
          title={t("Iniciar com o Windows")}
          hint={t("Deixe o Clarify pronto quando você precisar.")}
          checked={state.autostart}
          onChange={(v) => void run("setAutostart", v)}
        />
      </Section>
      <ComputerAccess controller={controller} />
      {state.applicationVersion && (
        <Section title={t("Atualizações")}>
          <Toggle
            title={t("Atualização automática")}
            hint={t("Baixe e instale novas versões em segundo plano. O Clarify reinicia após concluir suas tarefas e fechar os Settings.")}
            checked={!!state.automaticUpdates}
            onChange={(value) => void run("setAutomaticUpdates", value)}
          />
          <Row
            title={t("Versão {v0}", { v0: state.applicationVersion })}
            hint={
              (state.updateStatus && t(state.updateStatus)) ||
              t("Com a atualização automática desativada, o menu do Clarify avisa quando há uma nova versão.")
            }
          >
            <Button
              type="button"
              className="w-full"
              disabled={!state.updateSupported || state.updateBusy}
              onClick={() => void run("checkForUpdates")}
            >{t("Verificar atualizações")}</Button>
          </Row>
        </Section>
      )}
      {!state.accountState?.managed && !state.accountState?.signedIn && <Section title={t("Privacidade")}>
        <Toggle
          title={t("Salvar histórico")}
          hint={t("Mantenha suas transcrições neste computador.")}
          checked={state.historyEnabled}
          onChange={(v) => void run("setHistoryEnabled", v)}
        />
        {state.historyEnabled && (
          <Field
            title={t("Retenção do histórico")}
            hint={t("Em dias. Deixe vazio para não definir um prazo.")}
            type="number"
            min="0"
            max="3650"
            value={retention}
            onChange={(e) => setRetention(e.target.value)}
          />
        )}
      </Section>}
    </>
  );
}
