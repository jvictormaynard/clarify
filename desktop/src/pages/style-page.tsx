import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { DictationCleanup } from "../components/dictation-cleanup";
import { ApplicationWritingStyles } from "../components/application-writing-styles";
import { Picker, Row, Section, SettingsDisclosure, TextArea, Toggle } from "../components/ui";
import { WorkflowRoute } from "../components/workflow-route";
import { AfterDictationAction } from "../components/after-dictation-action";

export function StylePage({ controller: c }: SettingsPageProps) {
  const managed = !!(c.state.accountState?.managed || c.state.accountState?.signedIn);
  return <>
    <DictationCleanup controller={c} />
    <AfterDictationAction controller={c} />
    <ApplicationWritingStyles controller={c} />
    {!managed && <Section title={t("Revisão com IA")}>
      <SettingsDisclosure title={t("Modelo e instruções da revisão")}>
        <Row title={t("Revisar transcrições de")}>
          <Picker label={t("Contexto da revisão")} value={c.state.selectedScope}
            options={[{ id: "refinement", label: t("Ditado na nuvem") }, { id: "local_asr_refinement", label: t("Transcrição local") }]}
            onChange={scope => void c.navigate("style", scope)} />
        </Row>
        <Toggle title={t("Ativar revisão por IA")}
          hint={c.state.selectedScope === "local_asr_refinement"
            ? t("Após a transcrição local, envie o texto ao serviço de revisão configurado.")
            : t("Melhore o texto do ditado com o serviço configurado.")}
          checked={c.state.routeEnabled && (c.state.selectedScope !== "local_asr_refinement" || c.state.localAsrCloudRefinement)}
          onChange={value => void c.setTextRouteEnabled(value)} />
        <WorkflowRoute controller={c} />
        <Row title={t("Instruções")}><TextArea aria-label={t("Instruções")} className="prompt min-h-35"
          value={c.prompt} onChange={event => c.setPrompt(event.target.value)} /></Row>
      </SettingsDisclosure>
    </Section>}
  </>;
}
