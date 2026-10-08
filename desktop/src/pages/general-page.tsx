import type { SettingsPageProps } from "../settings/use-settings";
import { Field, Picker, Row, Section, Toggle } from "../components/ui";
const languageNames: Record<string, string> = {
  en: "English",
  pt: "Português",
  es: "Español",
  de: "Deutsch",
  ru: "Русский",
};

export function GeneralPage({ controller }: SettingsPageProps) {
  const { state, run, retention, setRetention } = controller;
  return (
    <>
      <Section title="Preferências">
        <Row title="Idioma do texto">
          <Picker
            label="Idioma"
            value={state.language}
            options={state.languages.map((id) => ({
              id,
              label: languageNames[id] || id,
            }))}
            onChange={(v) => void run("setLanguage", v)}
          />
        </Row>
        <Toggle
          title="Iniciar com o Windows"
          hint="Deixe o Clarify pronto quando você precisar."
          checked={state.autostart}
          onChange={(v) => void run("setAutostart", v)}
        />
      </Section>
      {state.applicationVersion && (
        <Section title="Atualizações">
          <Toggle
            title="Atualização automática"
            hint="Baixe e instale novas versões em segundo plano. O Clarify reinicia após concluir suas tarefas e fechar os Settings."
            checked={!!state.automaticUpdates}
            onChange={(value) => void run("setAutomaticUpdates", value)}
          />
          <Row
            title={`Versão ${state.applicationVersion}`}
            hint={
              state.updateStatus ||
              "Com a atualização automática desativada, o menu do Clarify avisa quando há uma nova versão."
            }
          >
            <button
              type="button"
              className="control"
              disabled={!state.updateSupported || state.updateBusy}
              onClick={() => void run("checkForUpdates")}
            >
              Verificar atualizações
            </button>
          </Row>
        </Section>
      )}
      <Section title="Privacidade">
        <Toggle
          title="Salvar histórico"
          hint="Mantenha suas transcrições neste computador."
          checked={state.historyEnabled}
          onChange={(v) => void run("setHistoryEnabled", v)}
        />
        {state.historyEnabled && (
          <Field
            title="Retenção do histórico"
            hint="Em dias. Deixe vazio para não definir um prazo."
            type="number"
            min="0"
            max="3650"
            value={retention}
            onChange={(e) => setRetention(e.target.value)}
          />
        )}
      </Section>
    </>
  );
}
