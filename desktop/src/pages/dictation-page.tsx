import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import {
  Button,
  Picker,
  Row,
  Section,
  SettingsDisclosure,
  TextArea,
  Toggle,
} from "../components/ui";
import { WorkflowRoute } from "../components/workflow-route";
import { RecordingOptions } from "../components/recording-options";
import { recordingDraft } from "../settings/recording";

export function DictationPage({ controller }: SettingsPageProps) {
  const { state, run, prompt, setPrompt, recording, setRecording } = controller;
  const managedProcessing = state.accountState?.managed || state.accountState?.signedIn;
  return (
    <>
      <Section title={t("Entrada de áudio")}>
        <Row title={t("Microfone")}>
          <Picker
            label={t("Microfone")}
            value={state.selectedMicrophoneId || ""}
            options={state.microphoneDevices.map((device) =>
              device.id ? device : { ...device, label: t("Padrão do sistema") },
            )}
            onChange={(v) => void run("selectMicrophone", v)}
            onRefresh={() => void run("refreshMicrophones")}
            busy={state.microphoneInventoryBusy}
          />
        </Row>
        <div className="mic-test">
          <div className="wave" aria-label={t("Nível do microfone")}>
            {Array.from({ length: 36 }, (_, i) => (
              <i
                key={i}
                style={{
                  height: `${3 + (state.microphoneTestBusy ? state.microphoneTestLevel * (10 + 25 * Math.abs(Math.sin(i * 1.9))) : 0)}px`,
                }}
              />
            ))}
          </div>
          <Button
            disabled={state.microphoneInventoryBusy}
            onClick={() =>
              void run(
                state.microphoneTestBusy
                  ? "stopMicrophoneTest"
                  : "testMicrophone",
              )
            }
          >
            {state.microphoneTestBusy ? t("Parar teste") : t("Testar microfone")}
          </Button>
        </div>
        {state.microphoneInventoryBusy && <p className="hint" role="status">{t("Carregando…")}</p>}
        {state.microphoneTestStatus && (
          <p className="hint" role="status">
            {state.microphoneTestStatus === "Test stopped."
              ? t("Teste encerrado.")
              : t(state.microphoneTestStatus)}
          </p>
        )}
      </Section>
      <Section title={t("Modo de gravação")}>
        <Row title={t("Modo de gravação")}>
          <Picker
            label={t("Modo de gravação")}
            value={state.hotkeyActivationMode}
            options={[
              { id: "toggle", label: t("Pressionar para iniciar e parar") },
              ...(state.hotkeyPushToTalkSupported
                ? [{ id: "push_to_talk", label: t("Segurar para gravar") }]
                : []),
            ]}
            onChange={(v) => void run("setHotkeyActivationMode", v)}
          />
        </Row>
        <RecordingOptions
          value={{ ...(recording ?? recordingDraft(state.recordingControls)), enabled: state.recordingControls.vad.enabled }}
          onChange={setRecording}
          onEnabledChange={(enabled) => void run("setRecordingVadEnabled", enabled)}
        />
      </Section>
      {managedProcessing && <p className="hint">{t("O Clarify gerencia os modelos de transcrição e reescrita da sua conta.")}</p>}
      {!managedProcessing && <Section title={t("Transcrição")}>
        <Toggle
          title={t("Ativar ditado")}
          checked={state.routeEnabled}
          onChange={(v) => void run("setRouteEnabled", v)}
        />
        <WorkflowRoute controller={controller} />
        <SettingsDisclosure title={t("Instruções da transcrição")}>
          <TextArea
            className="prompt"
            aria-label={t("Instruções da transcrição")}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </SettingsDisclosure>
      </Section>}
    </>
  );
}
