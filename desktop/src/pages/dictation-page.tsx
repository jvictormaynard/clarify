import type { SettingsPageProps } from "../settings/use-settings";
import {
  Button,
  Picker,
  Row,
  Section,
  TextArea,
  Toggle,
} from "../components/ui";
import { WorkflowRoute } from "../components/workflow-route";
import { RecordingOptions } from "../components/recording-options";
import { recordingDraft } from "../settings/recording";

export function DictationPage({ controller }: SettingsPageProps) {
  const { state, run, prompt, setPrompt, recording, setRecording } = controller;
  return (
    <>
      <Section title="Entrada de áudio">
        <Row title="Microfone">
          <Picker
            label="Microfone"
            value={state.selectedMicrophoneId || ""}
            options={state.microphoneDevices.map((device) =>
              device.id ? device : { ...device, label: "Padrão do sistema" },
            )}
            onChange={(v) => void run("selectMicrophone", v)}
            onRefresh={() => void run("refreshMicrophones")}
          />
        </Row>
        <div className="mic-test">
          <div className="wave" aria-label="Nível do microfone">
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
            onClick={() =>
              void run(
                state.microphoneTestBusy
                  ? "stopMicrophoneTest"
                  : "testMicrophone",
              )
            }
          >
            {state.microphoneTestBusy ? "Parar teste" : "Testar microfone"}
          </Button>
        </div>
        {state.microphoneTestStatus && (
          <p className="hint" role="status">
            {state.microphoneTestStatus === "Test stopped."
              ? "Teste encerrado."
              : state.microphoneTestStatus}
          </p>
        )}
      </Section>
      <Section title="Transcrição">
        <WorkflowRoute controller={controller} />
        <Toggle
          title="Ativar ditado"
          checked={state.routeEnabled}
          onChange={(v) => void run("setRouteEnabled", v)}
        />
        <details>
          <summary>Instruções da transcrição</summary>
          <TextArea
            className="prompt"
            aria-label="Instruções da transcrição"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </details>
      </Section>
      <Section>
        <RecordingOptions
          value={recording ?? recordingDraft(state.recordingControls)}
          onChange={setRecording}
        />
      </Section>
      {state.routeProviderId === "local_asr" && (
        <Section title="Acabamento do texto">
          <Toggle
            title="Revisar com IA na nuvem"
            hint="Após a transcrição local, envie o texto ao serviço de revisão configurado."
            checked={state.localAsrCloudRefinement}
            onChange={(v) => void run("setLocalAsrCloudRefinement", v)}
          />
        </Section>
      )}
    </>
  );
}
