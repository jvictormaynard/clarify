import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Picker, Row, Section, TextArea, Toggle } from "../components/ui";
import { WorkflowRoute } from "../components/workflow-route";

export function TextPage({ controller }: SettingsPageProps) {
  const { state, navigate, prompt, setPrompt, setTextRouteEnabled } =
    controller;
  const isReview = state.selectedScope === "refinement" ||
    state.selectedScope === "local_asr_refinement";
  const title = state.selectedScope === "rewrite"
    ? t("Reescrita")
    : state.selectedScope === "translation" ? t("Tradução") : t("Revisão");
  const description = state.selectedScope === "rewrite"
    ? t("Rewrite selected text while preserving its requirements.")
    : state.selectedScope === "translation"
      ? t("Translate selected text using the configured language model.")
      : state.selectedScope === "local_asr_refinement"
        ? t("Optional cleanup after on-device transcription. If enabled, the transcript is sent to the selected service. Audio stays on your computer.")
        : t("Improve dictated text while preserving its meaning.");

  if (state.accountState?.managed || state.accountState?.signedIn) {
    return (
      <Section title={title}>
        <p className="hint">{t("O Clarify gerencia os modelos e as instruções da sua conta.")}</p>
      </Section>
    );
  }
  return (
    <>
      <Section title={title}>
        <p className="hint">{description}</p>
        {isReview && (
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
        <Toggle
          title={t("Ativar este fluxo")}
          checked={
            state.routeEnabled &&
            (state.selectedScope !== "local_asr_refinement" ||
              state.localAsrCloudRefinement)
          }
          onChange={(value) => void setTextRouteEnabled(value)}
        />
        <WorkflowRoute controller={controller} />
      </Section>
      <Section title={t("Instruções")}>
        <p className="hint">{t("Defina o tom e as alterações que a IA deve aplicar.")}</p>
        <TextArea
          className="prompt min-h-35"
          shellClassName="my-3"
          aria-label={t("Instruções")}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={t("Optional instructions for this task")}
        />
      </Section>
    </>
  );
}
