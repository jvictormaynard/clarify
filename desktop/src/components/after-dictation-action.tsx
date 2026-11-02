import { useState } from "react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { actionDisplayName } from "../settings/use-text-actions";
import { Button, Picker, Row, Section, SettingsDisclosure } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";

export const textActionLanguages = [{ id: "pt", label: "Português" }, { id: "en", label: "English" },
  { id: "es", label: "Español" }, { id: "de", label: "Deutsch" }, { id: "ru", label: "Русский" }];

type Mode = "natural" | "preserve" | "light" | "clarity" | "action";
export function AfterDictationAction({ controller: c }: SettingsPageProps) {
  const [choosingContext, setChoosingContext] = useState<string | null>(null);
  const [target, setTarget] = useState<{ id: string; context: string; revision: string } | null>(null);
  const [language, setLanguage] = useState("");
  const [saving, setSaving] = useState(false);
  const actions = (c.state.textActions ?? []).filter(action => action.enabled);
  const selected = c.state.afterDictationTextActionId ?? "";
  const level = c.state.dictationCleanupLevel ?? "";
  const savedMode: Mode = level === "preserve" || level === "light" ? level : selected ? "action" : level === "clarity" ? "clarity" : "natural";
  const mode = choosingContext === c.state.textActionContext ? "action" : savedMode;
  const action = actions.find(item => item.id === selected);
  const disabled = saving || !!c.state.textActionMutation?.busy;
  const save = async (nextMode: Mode, id = "", targetLanguage = "auto", context = c.state.textActionContext, revision = c.state.textActionsRevision ?? "") => {
    if (saving || (nextMode === "action" && !context)) return false;
    setSaving(true);
    try {
      const result = nextMode === "action"
        ? await c.run("setDictationPostProcessing", nextMode, id, targetLanguage, context!, revision)
        : await c.run("setDictationCleanupLevel", nextMode === "natural" ? "" : nextMode);
      if (result) setChoosingContext(null);
      return !!result;
    } finally { setSaving(false); }
  };
  const setAction = async (id: string) => {
    if (!c.state.textActionContext) return;
    if (actions.find(item => item.id === id)?.kind === "translation") {
      setTarget({ id, context: c.state.textActionContext, revision: c.state.textActionsRevision ?? "" });
      setLanguage(""); return;
    }
    await save("action", id);
  };
  const help = {
    natural: "Mantém suas instruções atuais de ditado, sem uma ação adicional.",
    preserve: "Mantém as palavras reconhecidas, sem revisão por IA. Dicionário e snippets continuam ativos.",
    light: "Ajusta apenas espaços e tabulações. Mantém hesitações, repetições e autocorreções.",
    clarity: "Usa a revisão configurada para melhorar a clareza. Se ela falhar, mantém a transcrição com os snippets.",
    action: "Aplica a ação escolhida no lugar da revisão padrão, antes de inserir o texto.",
  }[mode];
  const needsReview = mode === "clarity" || mode === "action";
  return <>
    <Section title={t("Após o ditado")}>
      <Row title={t("Processamento do texto")}>
        <Picker label={t("Após o ditado")} value={mode} disabled={disabled} options={[
          { id: "natural", label: t("Natural") },
          { id: "preserve", label: t("Preservar palavras") },
          { id: "light", label: t("Ajustes mínimos") },
          { id: "clarity", label: t("Revisar clareza") },
          { id: "action", label: t("Aplicar ação de texto") },
        ]} onChange={value => {
          if (value === "action") setChoosingContext(c.state.textActionContext ?? null);
          else void save(value as Mode);
        }} />
      </Row>
      <p className="hint">{t(help)}</p>
      {mode === "action" && <>
        <Row title={t("Ação de texto")}>
          <Picker label={t("Ação após o ditado")} value={selected} disabled={disabled || !c.state.textActionContext}
            options={[{ id: "", label: t("Escolher ação") }, ...actions.map(item => ({ id: item.id, label: actionDisplayName(item) }))]}
            onChange={id => { if (id) void setAction(id); }} />
        </Row>
        {!c.state.textActionContext ? <div>
          <p className="hint" role="status">{t("Não foi possível carregar as ações. Atualize para tentar novamente.")}</p>
          <Button disabled={disabled} onClick={() => void c.run("refreshTextActions")}>{t("Atualizar ações")}</Button>
        </div> : !actions.length && <p className="hint" role="status">{t("Nenhuma ação salva. Crie uma em Ações de texto.")}</p>}
        {selected && !action && <p className="hint" role="status">{t("A ação selecionada está indisponível. Escolha outra ação.")}</p>}
        {action && <SettingsDisclosure title={t("Instruções da ação")}><p className="hint whitespace-pre-wrap">{action.prompt}</p></SettingsDisclosure>}
        {choosingContext && savedMode !== "action" && <p className="hint" role="status">{t("Escolha uma ação para salvar. Até lá, a configuração anterior continua ativa.")}</p>}
        {action?.kind === "translation" && <Row title={t("Idioma de destino")}>
          <Button disabled={disabled} onClick={() => void setAction(selected)}>{t(textActionLanguages.find(item => item.id === c.state.afterDictationTextActionLanguage)?.label ?? "Escolher idioma")}</Button>
        </Row>}
      </>}
      {needsReview && c.state.dictationCleanupRefinementAllowed === false && <div>
        <p className="hint" role="status">{t("Revisão indisponível nesta rota. As palavras serão preservadas.")}</p>
        {!(c.state.accountState?.managed || c.state.accountState?.signedIn) && <Button variant="text" onClick={() => void c.navigate("style", c.state.textActionDictationContext === "local_asr" ? "local_asr_refinement" : "refinement")}>{t("Configurar revisão")}</Button>}
      </div>}
      <p className="hint">{t("A escolha vale para o próximo ditado. Ela não ativa serviços na nuvem.")}</p>
      <p className="hint">{t("Snippets isolados inserem o texto salvo exatamente. Outros snippets são expandidos uma vez antes da revisão.")}</p>
    </Section>
    <Dialog open={!!target} onOpenChange={open => { if (!open && !saving) setTarget(null); }}>
      <DialogPopup bottomStickOnMobile={false}>
        <DialogHeader><DialogTitle>{t("Idioma da tradução")}</DialogTitle>
          <DialogDescription>{t("Escolha o idioma usado por esta ação após o ditado.")}</DialogDescription></DialogHeader>
        <Picker label={t("Idioma de destino")} value={language} options={textActionLanguages} onChange={setLanguage} />
        <DialogFooter><Button variant="ghost" disabled={saving} onClick={() => setTarget(null)}>{t("Cancelar")}</Button>
          <Button variant="primary" loading={saving} disabled={!language || target?.context !== c.state.textActionContext}
            onClick={async () => { if (target && await save("action", target.id, language, target.context, target.revision)) setTarget(null); }}>{t("Aplicar")}</Button></DialogFooter>
      </DialogPopup>
    </Dialog>
  </>;
}
