import type { SettingsPageProps } from "../settings/use-settings";
import { Picker, Row, Section, TextArea, Toggle } from "../components/ui";
import { WorkflowRoute } from "../components/workflow-route";

export function TextPage({ controller }: SettingsPageProps) {
  const { state, navigate, prompt, setPrompt, setTextRouteEnabled } =
    controller;
  return (
    <>
      <div className="segmented" aria-label="Fluxo de texto">
        {[
          { id: "refinement", label: "Revisão" },
          { id: "rewrite", label: "Reescrita" },
          { id: "translation", label: "Tradução" },
        ].map((item) => (
          <button
            type="button"
            key={item.id}
            aria-pressed={
              state.selectedScope === item.id ||
              (item.id === "refinement" &&
                state.selectedScope === "local_asr_refinement")
            }
            onClick={() => void navigate("text", item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {(state.selectedScope === "refinement" ||
        state.selectedScope === "local_asr_refinement") && (
        <Row title="Revisar transcrições de">
          <Picker
            label="Contexto da revisão"
            value={state.selectedScope}
            options={[
              { id: "refinement", label: "Ditado na nuvem" },
              { id: "local_asr_refinement", label: "Transcrição local" },
            ]}
            onChange={(v) => void navigate("text", v)}
          />
        </Row>
      )}
      <Section>
        <WorkflowRoute controller={controller} />
        <Toggle
          title="Ativar este fluxo"
          checked={
            state.routeEnabled &&
            (state.selectedScope !== "local_asr_refinement" ||
              state.localAsrCloudRefinement)
          }
          onChange={(value) => void setTextRouteEnabled(value)}
        />
      </Section>
      <Section title="Instruções">
        <p className="hint">
          Defina o tom e as alterações que a IA deve aplicar.
        </p>
        <TextArea
          className="prompt"
          aria-label="Instruções"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Como o texto deve ser revisado?"
        />
      </Section>
    </>
  );
}
