import { useState } from "react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { actionDisplayName } from "../settings/display-labels";
import { Button, Picker, Row, Section, SettingsDisclosure } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";

export const textActionLanguages = [{ id: "pt", label: "Português" }, { id: "en", label: "English" },
  { id: "es", label: "Español" }, { id: "de", label: "Deutsch" }, { id: "ru", label: "Русский" }];

type EditingMode = "natural" | "preserve" | "light" | "clarity" | "action";

function editingMode(state: SettingsPageProps["controller"]["state"]): EditingMode {
  const level = state.dictationCleanupLevel;
  if (level === "preserve" || level === "light") return level;
  if (state.afterDictationTextActionId) return "action";
  return level === "clarity" ? "clarity" : "natural";
}

export function TextEditing({ controller: c }: SettingsPageProps) {
  const [saving, setSaving] = useState(false);
  const mode = editingMode(c.state);
  const action = c.state.textActions?.find(item => item.enabled && item.id === c.state.afterDictationTextActionId);
  const help = {
    natural: "Mantém suas instruções atuais de ditado, sem uma ação adicional.",
    preserve: "Mantém as palavras reconhecidas, sem revisão por IA. Dicionário e snippets continuam ativos.",
    light: "Ajusta apenas espaços e tabulações. Mantém hesitações, repetições e autocorreções.",
    clarity: "Usa a revisão configurada para melhorar a clareza. Se ela falhar, mantém a transcrição com os snippets.",
    action: "Aplica a ação escolhida no lugar da revisão padrão, antes de inserir o texto.",
  }[mode];
  return <>
    <Row title={t("Edição do texto")}>
      <Picker literalLabels label={t("Edição do texto")} value={mode} disabled={saving || !!c.state.textActionMutation?.busy}
        options={[
          { id: "clarity", label: t("Melhorar a clareza") },
          { id: "preserve", label: t("Manter minhas palavras") },
          ...(mode === "light" ? [{ id: "light", label: t("Ajustes mínimos") }] : []),
          ...(mode === "natural" ? [{ id: "natural", label: t("Instruções atuais") }] : []),
          ...(mode === "action" ? [{ id: "action", label: action ? actionDisplayName(action) : t("Ação indisponível") }] : []),
        ]} onChange={async value => {
          if (saving || (value !== "clarity" && value !== "preserve")) return;
          setSaving(true);
          try { await c.run("setDictationCleanupLevel", value); }
          finally { setSaving(false); }
        }} />
    </Row>
    <p className="hint">{t(help)}</p>
    {(mode === "clarity" || mode === "action") && c.state.dictationCleanupRefinementAllowed === false && <div>
      <p className="hint" role="status">{t("Revisão indisponível nesta rota. As palavras serão preservadas.")}</p>
      {!(c.state.accountState?.managed || c.state.accountState?.signedIn) && <Button variant="text" onClick={() => void c.navigate("style", c.state.textActionDictationContext === "local_asr" ? "local_asr_refinement" : "refinement")}>{t("Configurar revisão")}</Button>}
    </div>}
  </>;
}

export function AutomaticSavedAction({ controller: c }: SettingsPageProps) {
  const [choosingContext, setChoosingContext] = useState<string | null>(null);
  const [target, setTarget] = useState<{ id: string; context: string; revision: string } | null>(null);
  const [language, setLanguage] = useState("");
  const [saving, setSaving] = useState(false);
  const actions = (c.state.textActions ?? []).filter(action => action.enabled);
  const selected = c.state.afterDictationTextActionId ?? "";
  const active = editingMode(c.state) === "action";
  const choosing = choosingContext !== null && choosingContext === c.state.textActionContext;
  const action = actions.find(item => item.id === selected);
  const disabled = saving || !!c.state.textActionMutation?.busy;
  const save = async (id: string, targetLanguage = "auto", context = c.state.textActionContext, revision = c.state.textActionsRevision ?? "") => {
    if (disabled || !context || context !== c.state.textActionContext) return false;
    setSaving(true);
    try {
      const result = await c.run("setDictationPostProcessing", "action", id, targetLanguage, context, revision);
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
    await save(id);
  };
  return <>
    <Section title={t("Ação automática salva")}>
      <Row title={t("Ação após o ditado")}>
        <Picker literalLabels label={t("Ação automática salva")} value={active || choosing ? "action" : "off"} disabled={disabled}
          options={[{ id: "off", label: t("Nenhuma") }, { id: "action", label: t("Aplicar ação de texto") }]}
          onChange={async value => {
            if (disabled) return;
            if (value === "action") { setChoosingContext(c.state.textActionContext ?? ""); return; }
            if (!selected) { setChoosingContext(null); return; }
            setSaving(true);
            try {
              if (await c.run("setDictationCleanupLevel", "clarity")) setChoosingContext(null);
            } finally { setSaving(false); }
          }} />
      </Row>
      {(active || choosing) && <>
        <Row title={t("Ação de texto")}>
          <Picker literalLabels label={t("Ação após o ditado")} value={selected} disabled={disabled || !c.state.textActionContext}
            options={[{ id: "", label: t("Escolher ação") }, ...actions.map(item => ({ id: item.id, label: actionDisplayName(item) }))]}
            onChange={id => { if (id) void setAction(id); }} />
        </Row>
        {!c.state.textActionContext ? <div>
          <p className="hint" role="status">{t("Não foi possível carregar as ações. Atualize para tentar novamente.")}</p>
          <Button disabled={disabled} onClick={() => void c.run("refreshTextActions")}>{t("Atualizar ações")}</Button>
        </div> : !actions.length && <p className="hint" role="status">{t("Nenhuma ação salva. Crie uma em Ações de texto.")}</p>}
        {selected && !action && <p className="hint" role="status">{t("A ação selecionada está indisponível. Escolha outra ação.")}</p>}
        {action && <SettingsDisclosure title={t("Instruções da ação")}><p className="hint whitespace-pre-wrap">{action.prompt}</p></SettingsDisclosure>}
        {choosing && !active && <p className="hint" role="status">{t("Escolha uma ação para salvar. Até lá, a configuração anterior continua ativa.")}</p>}
        {action?.kind === "translation" && <Row title={t("Idioma de destino")}>
          <Button disabled={disabled} onClick={() => void setAction(selected)}>{t(textActionLanguages.find(item => item.id === c.state.afterDictationTextActionLanguage)?.label ?? "Escolher idioma")}</Button>
        </Row>}
      </>}
    </Section>
    <Dialog open={!!target} onOpenChange={open => { if (!open && !saving) setTarget(null); }}>
      <DialogPopup bottomStickOnMobile={false}>
        <DialogHeader><DialogTitle>{t("Idioma da tradução")}</DialogTitle>
          <DialogDescription>{t("Escolha o idioma usado por esta ação após o ditado.")}</DialogDescription></DialogHeader>
        <Picker label={t("Idioma de destino")} value={language} options={textActionLanguages} onChange={setLanguage} />
        {c.error && <p role="alert" className="error">{t(c.error)}</p>}
        <DialogFooter><Button variant="ghost" disabled={saving} onClick={() => setTarget(null)}>{t("Cancelar")}</Button>
          <Button variant="primary" loading={saving} disabled={!language || target?.context !== c.state.textActionContext}
            onClick={async () => { if (target && await save(target.id, language, target.context, target.revision)) setTarget(null); }}>{t("Aplicar")}</Button></DialogFooter>
      </DialogPopup>
    </Dialog>
  </>;
}
