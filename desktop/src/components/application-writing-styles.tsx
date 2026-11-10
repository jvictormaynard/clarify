import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { applicationName } from "../settings/display-labels";
import { writingStyleNames as names, writingStyleOptions } from "../settings/writing-style-options";
import type { WritingStyle } from "../settings/bridge";
import { Button, Picker, Row, Section } from "./ui";

export function ApplicationWritingStyles({ controller, rulesOnly = false }: SettingsPageProps & { rulesOnly?: boolean }) {
  const { state, run, appStyleEditor } = controller;
  const rules = state.applicationWritingStyles ?? [];
  const unavailable = state.applicationStyleRefinementAllowed === false;
  const style = state.dictationWritingStyle ?? "";
  return <>
  {!rulesOnly && !unavailable && <>
    <Row title={t("Tom")}>
      <Picker label={t("Tom")} value={style} options={writingStyleOptions(style)} onChange={value => void run("setDictationWritingStyle", value as WritingStyle | "")} />
    </Row>
    {style === "" && <p className="hint">{t("Mantém as instruções atuais, sem um tom explícito.")}</p>}
  </>}
  {rulesOnly && <Section title={t("Estilos por aplicativo")}>
    <p className="hint">{t("Sem regra, usa o estilo geral. A regra vale para o próximo ditado.")}</p>
    {unavailable && <p className="hint" role="status">{t("Estilo não aplicado nesta rota. A regra não ativa revisão nem processamento na nuvem.")}</p>}
    {rules.length === 0 && <p className="hint">{t("Todos os aplicativos usam o estilo geral.")}</p>}
    {rules.map(rule => <Row key={rule.executable} title={applicationName(rule.executable)} hint={t(names[rule.style])}>
      <Button aria-label={t("Editar estilo de {name}", { name: applicationName(rule.executable) })}
        onClick={() => appStyleEditor.open(rule)}>{t("Editar estilo")}</Button>
      <Button onClick={() => void run("setApplicationWritingStyle", rule.executable, "")}>{t("Remover regra")}</Button>
    </Row>)}
    <div className="inline-actions"><Button onClick={() => appStyleEditor.open()}>{t("Adicionar aplicativo")}</Button></div>
  </Section>}
  </>;
}
