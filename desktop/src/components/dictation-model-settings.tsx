import { LoaderCircle } from "lucide-react";
import { t } from "../i18n";
import { reviewScopes } from "../settings/navigation";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Picker, Row, Section, SettingsDisclosure, TextArea, Toggle } from "./ui";
import { WorkflowRoute } from "./workflow-route";

export function DictationModelSettings({ controller: c }: SettingsPageProps) {
  const { state, modelsView } = c;
  if (state.accountState?.managed) {
    return <p className="hint">{t("O Clarify gerencia os modelos de transcrição e reescrita da sua conta.")}</p>;
  }
  if (!("scope" in modelsView)) return null;
  const { tab, scope } = modelsView;
  return <Section>
    {tab === "review" && <Row title={t("Revisar transcrições de")}>
      <Picker label={t("Contexto da revisão")} value={scope}
        options={[{ id: "refinement", label: t("Ditado na nuvem") }, { id: "local_asr_refinement", label: t("Transcrição local") }]}
        onChange={value => {
          const next = reviewScopes.find(option => option === value);
          if (next) void c.openModelsTab("review", next);
        }} />
    </Row>}
    {c.routeLoading
      ? <div className="connection" role="status"><LoaderCircle size={22} className="spin" />{t("Carregando…")}</div>
      : state.selectedScope !== scope
        ? <Button onClick={() => void c.openModelsTab(tab, tab === "review" ? scope : undefined)}>{t("Tentar novamente")}</Button>
        : <RouteEditor controller={c} key={scope} review={tab === "review"} />}
  </Section>;
}

function RouteEditor({ controller: c, review }: SettingsPageProps & { review: boolean }) {
  const { state } = c;
  const localCloudReview = state.selectedScope === "local_asr_refinement" && state.routeProviderId !== "apple_clarity";

  return <>
    {review ? <Toggle title={t("Ativar revisão por IA")}
      hint={t(localCloudReview
        ? "Após a transcrição local, envie o texto ao serviço de revisão configurado."
        : "Melhore o texto do ditado com o serviço configurado.")}
      checked={state.routeEnabled && (!localCloudReview || state.localAsrCloudRefinement)}
      onChange={value => void c.setTextRouteEnabled(value)} />
    : <Toggle title={t("Ativar ditado")} checked={state.routeEnabled} onChange={value => void c.run("setRouteEnabled", value)} />}
    <WorkflowRoute controller={c} />
    <SettingsDisclosure title={t(review ? "Instruções da revisão" : "Instruções da transcrição")}>
      {review
        ? <Row title={t("Instruções")}><TextArea aria-label={t("Instruções")} className="prompt min-h-35"
          value={c.prompt} onChange={event => c.setPrompt(event.target.value)} /></Row>
        : <TextArea aria-label={t("Instruções da transcrição")} className="prompt"
          value={c.prompt} onChange={event => c.setPrompt(event.target.value)} />}
    </SettingsDisclosure>
  </>;
}
