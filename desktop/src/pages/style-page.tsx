import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { ApplicationWritingStyles } from "../components/application-writing-styles";
import { Picker, Row, Section, SettingsDisclosure, TextArea, Toggle } from "../components/ui";
import { WorkflowRoute } from "../components/workflow-route";
import { textActionLanguages, TextEditing, AutomaticSavedAction } from "../components/after-dictation-action";

export function StylePage({ controller: c }: SettingsPageProps) {
  const managed = !!(c.state.accountState?.managed || c.state.accountState?.signedIn);
  return <>
    <Section title={t("Seu texto")}>
    <TextEditing controller={c} />
    <ApplicationWritingStyles controller={c} />
    <SettingsDisclosure title={t("Mais opções")}>
      <Section title={t("Idioma de saída")}>
        <Row title={t("Idioma de saída")}>
          <Picker label={t("Idioma de saída")} value={c.state.language}
            options={[{ id: "auto", label: t("Manter idioma de origem") }, ...textActionLanguages]}
            onChange={value => void c.run("setLanguage", value)} />
        </Row>
        {c.state.language !== "auto" && c.state.applicationStyleRefinementAllowed === false &&
          <p className="hint" role="status">{t("O idioma fica salvo. Sem revisão, o ditado não é traduzido.")}</p>}
      </Section>
      <ApplicationWritingStyles controller={c} rulesOnly />
      <AutomaticSavedAction key={c.state.textActionContext} controller={c} />
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
    </SettingsDisclosure>
    </Section>
    <p className="hint">{t("A escolha vale para o próximo ditado. Ela não ativa serviços na nuvem.")}</p>
  </>;
}
