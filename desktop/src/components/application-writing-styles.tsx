import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { applicationName } from "../settings/use-app-style-editor";
import { Button, Row, Section } from "./ui";

const names = { formal: "Formal", casual: "Casual", very_casual: "Muito casual", natural: "Natural", informal: "Informal", organized: "Organizado" };

export function ApplicationWritingStyles({ controller }: SettingsPageProps) {
  const { state, run, appStyleEditor } = controller;
  const rules = state.applicationWritingStyles ?? [];
  const unavailable = state.applicationStyleRefinementAllowed === false;
  return <Section title={t("Estilos por aplicativo")}>
    <p className="hint">{t("Sem regra, usa Padrão e mantém suas instruções atuais. A regra vale para o próximo ditado.")}</p>
    {unavailable && <p className="hint" role="status">{t("Estilo não aplicado nesta rota. A regra não ativa revisão nem processamento na nuvem.")}</p>}
    {rules.length === 0 && <p className="hint">{t("Padrão para todos os aplicativos.")}</p>}
    {rules.map(rule => <Row key={rule.executable} title={applicationName(rule.executable)} hint={t(names[rule.style])}>
      <Button aria-label={t("Editar estilo de {name}", { name: applicationName(rule.executable) })}
        onClick={() => appStyleEditor.open(rule)}>{t("Editar estilo")}</Button>
      <Button onClick={() => void run("setApplicationWritingStyle", rule.executable, "")}>{t("Remover regra")}</Button>
    </Row>)}
    <div className="inline-actions"><Button onClick={() => appStyleEditor.open()}>{t("Adicionar aplicativo")}</Button></div>
  </Section>;
}
