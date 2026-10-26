import { useState } from "react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import type { WritingStyle } from "../settings/bridge";
import { Button, Field, Picker, Row, Section } from "./ui";

const names = { natural: "Natural", informal: "Informal", organized: "Organizado" };

export function ApplicationWritingStyles({ controller }: SettingsPageProps) {
  const { state, run } = controller;
  const [executable, setExecutable] = useState("");
  const [style, setStyle] = useState<WritingStyle>("natural");
  const [saving, setSaving] = useState(false);
  const rules = state.applicationWritingStyles ?? [];
  const unavailable = state.applicationStyleRefinementAllowed === false;
  const save = async () => {
    setSaving(true);
    try { await run("setApplicationWritingStyle", executable, style); }
    finally { setSaving(false); }
  };
  return <Section title={t("Estilos por aplicativo")}>
    <p className="hint">{t("Sem regra, usa Padrão e mantém suas instruções atuais. A regra vale para o próximo ditado.")}</p>
    <Field title={t("Caminho do aplicativo")} value={executable}
      onChange={event => setExecutable(event.target.value)}
      hint={t("Informe o caminho completo do arquivo .exe. O arquivo não será aberto nem executado.")} />
    <Button disabled={!state.applicationStyleTarget} onClick={() => setExecutable(state.applicationStyleTarget ?? "")}>{t("Usar último aplicativo")}</Button>
    <Row title={t("Estilo de escrita")}>
      <Picker label={t("Estilo de escrita")} value={style}
        options={Object.entries(names).map(([id, name]) => ({ id, label: t(name) }))}
        onChange={value => setStyle(value as WritingStyle)} />
    </Row>
    <p className="hint">{t({
      natural: "Mantém seu vocabulário e tom, com frases naturais.",
      informal: "Usa linguagem cotidiana, sem acrescentar gírias ou emojis.",
      organized: "Organiza os pontos em parágrafos e as enumerações em listas, sem acrescentar conteúdo.",
    }[style])}</p>
    <Button loading={saving} disabled={!executable}
      onClick={() => void save()}>{t("Salvar regra")}</Button>
    {unavailable && <p className="hint" role="status">{t("Estilo não aplicado nesta rota. A regra não ativa revisão nem processamento na nuvem.")}</p>}
    {rules.length === 0 && <p className="hint">{t("Padrão para todos os aplicativos.")}</p>}
    {rules.map(rule => <Row key={rule.executable} title={rule.executable} hint={t(names[rule.style])}>
      <Picker label={t("Estilo para {app}", { app: rule.executable })} value={rule.style}
        options={Object.entries(names).map(([id, name]) => ({ id, label: t(name) }))}
        onChange={value => void run("setApplicationWritingStyle", rule.executable, value as WritingStyle)} />
      <Button onClick={() => void run("setApplicationWritingStyle", rule.executable, "")}>{t("Remover regra")}</Button>
    </Row>)}
  </Section>;
}
