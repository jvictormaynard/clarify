import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Picker, Row, Section, TextArea, Toggle } from "../components/ui";
import { WorkflowRoute } from "../components/workflow-route";

export function TextPage({ controller }: SettingsPageProps) {
  const { state, navigate, prompt, setPrompt, setTextRouteEnabled } =
    controller;
  if ((state.accountState?.managed || state.accountState?.signedIn)) return <p className="hint">{t("O Clarify gerencia os modelos e as instruções da sua conta.")}</p>;
  return (
    <>
      <div className="segmented" aria-label={t("Fluxo de texto")}>
        {[
          { id: "refinement", label: t("Revisão") },
          { id: "rewrite", label: t("Reescrita") },
          { id: "translation", label: t("Tradução") },
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
        <Row title={t("Revisar transcrições de")}>
          <Picker
            label={t("Contexto da revisão")}
            value={state.selectedScope}
            options={[
              { id: "refinement", label: t("Ditado na nuvem") },
              { id: "local_asr_refinement", label: t("Transcrição local") },
            ]}
            onChange={(v) => void navigate("text", v)}
          />
        </Row>
      )}
      <Section>
        <WorkflowRoute controller={controller} />
        <Toggle
          title={t("Ativar este fluxo")}
          checked={
            state.routeEnabled &&
            (state.selectedScope !== "local_asr_refinement" ||
              state.localAsrCloudRefinement)
          }
          onChange={(value) => void setTextRouteEnabled(value)}
        />
      </Section>
      <Section title={t("Instruções")}>
        <p className="hint">{t("Defina o tom e as alterações que a IA deve aplicar.")}</p>
        <TextArea
          className="prompt"
          aria-label={t("Instruções")}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={t("Como o texto deve ser revisado?")}
        />
      </Section>
    </>
  );
}
