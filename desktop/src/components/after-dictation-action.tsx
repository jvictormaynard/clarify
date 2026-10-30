import { useState } from "react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { actionDisplayName } from "../settings/use-text-actions";
import { Button, Picker, Row, Section } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";

export const textActionLanguages = [{ id: "pt", label: "Português" }, { id: "en", label: "English" },
  { id: "es", label: "Español" }, { id: "de", label: "Deutsch" }, { id: "ru", label: "Русский" }];

export function AfterDictationAction({ controller: c }: SettingsPageProps) {
  const [target, setTarget] = useState<{ id: string; context: string; revision: string } | null>(null);
  const [language, setLanguage] = useState("");
  const [saving, setSaving] = useState(false);
  const actions = (c.state.textActions ?? []).filter(action => action.enabled);
  const selected = c.state.afterDictationTextActionId ?? "";
  const setAction = async (id: string) => {
    if (!c.state.textActionContext) return;
    const action = actions.find(item => item.id === id);
    if (action?.kind === "translation") {
      setTarget({ id, context: c.state.textActionContext, revision: c.state.textActionsRevision ?? "" });
      setLanguage(""); return;
    }
    await c.run("setAfterDictationTextAction", id, "auto", c.state.textActionContext, c.state.textActionsRevision ?? "");
  };
  const saveTarget = async () => {
    if (!target || !language || saving) return;
    setSaving(true);
    try {
      if (await c.run("setAfterDictationTextAction", target.id, language, target.context, target.revision)) setTarget(null);
    } finally { setSaving(false); }
  };
  return <>
    <Section title={t("Após o ditado")}>
      <Row title={t("Ação automática")} hint={t("Usa uma ação na etapa de revisão, quando permitida por esta rota.")}>
        <Picker label={t("Ação após o ditado")} value={selected} disabled={!c.state.textActionContext}
          options={[{ id: "", label: t("Revisão padrão") }, ...actions.map(action => ({ id: action.id, label: actionDisplayName(action) }))]}
          onChange={id => void setAction(id)} />
      </Row>
      {actions.find(action => action.id === selected)?.kind === "translation" && <Row title={t("Idioma de destino")}>
        <Button onClick={() => void setAction(selected)}>{t(textActionLanguages.find(item => item.id === c.state.afterDictationTextActionLanguage)?.label ?? "Escolher idioma")}</Button>
      </Row>}
      <p className="hint">{t("A escolha vale para o próximo ditado. Ela não ativa serviços na nuvem.")}</p>
    </Section>
    <Dialog open={!!target} onOpenChange={open => { if (!open && !saving) setTarget(null); }}>
      <DialogPopup bottomStickOnMobile={false}>
        <DialogHeader><DialogTitle>{t("Idioma da tradução")}</DialogTitle>
          <DialogDescription>{t("Escolha o idioma usado por esta ação após o ditado.")}</DialogDescription></DialogHeader>
        <Picker label={t("Idioma de destino")} value={language} options={textActionLanguages} onChange={setLanguage} />
        <DialogFooter><Button variant="ghost" disabled={saving} onClick={() => setTarget(null)}>{t("Cancelar")}</Button>
          <Button variant="primary" loading={saving} disabled={!language || target?.context !== c.state.textActionContext} onClick={() => void saveTarget()}>{t("Aplicar")}</Button></DialogFooter>
      </DialogPopup>
    </Dialog>
  </>;
}
