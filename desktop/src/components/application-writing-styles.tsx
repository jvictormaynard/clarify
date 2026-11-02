import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { applicationName } from "../settings/use-app-style-editor";
import type { WritingStyle } from "../settings/bridge";
import { Button, Picker, Row, Section } from "./ui";

const names = { formal: "Formal", casual: "Casual", very_casual: "Muito casual", natural: "Natural", informal: "Informal", organized: "Organizado" };

export function ApplicationWritingStyles({ controller }: SettingsPageProps) {
  const { state, run, appStyleEditor } = controller;
  const rules = state.applicationWritingStyles ?? [];
  const unavailable = state.applicationStyleRefinementAllowed === false;
  const style = state.dictationWritingStyle ?? "";
  return <>
  <Section title={t("Estilo de escrita")}>
    <Row title={t("Estilo geral")} hint={t("Define o tom do texto. Regras por aplicativo têm prioridade.")}>
      <Picker label={t("Estilo geral")} value={style} options={[
        { id: "", label: t("Natural") }, { id: "formal", label: t("Formal") },
        { id: "casual", label: t("Casual") }, { id: "very_casual", label: t("Muito casual") },
        ...(["natural", "informal", "organized"].includes(style) ? [{ id: style, label: t(names[style as WritingStyle]) }] : []),
      ]} onChange={value => void run("setDictationWritingStyle", value as WritingStyle | "")} />
    </Row>
    {style === "" && <p className="hint">{t("Natural mantém suas instruções atuais, sem impor um tom.")}</p>}
    {unavailable && <p className="hint" role="status">{t("Estilo não aplicado")}</p>}
  </Section>
  <Section title={t("Estilos por aplicativo")}>
    <p className="hint">{t("Sem regra, usa o estilo geral. A regra vale para o próximo ditado.")}</p>
    {unavailable && <p className="hint" role="status">{t("Estilo não aplicado nesta rota. A regra não ativa revisão nem processamento na nuvem.")}</p>}
    {rules.length === 0 && <p className="hint">{t("Todos os aplicativos usam o estilo geral.")}</p>}
    {rules.map(rule => <Row key={rule.executable} title={applicationName(rule.executable)} hint={t(names[rule.style])}>
      <Button aria-label={t("Editar estilo de {name}", { name: applicationName(rule.executable) })}
        onClick={() => appStyleEditor.open(rule)}>{t("Editar estilo")}</Button>
      <Button onClick={() => void run("setApplicationWritingStyle", rule.executable, "")}>{t("Remover regra")}</Button>
    </Row>)}
    <div className="inline-actions"><Button onClick={() => appStyleEditor.open()}>{t("Adicionar aplicativo")}</Button></div>
  </Section>
  </>;
}
