import { useRef, useState } from "react";
import { t } from "../i18n";
import type { Settings } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";
import { actionDisplayName } from "../settings/display-labels";
import { Button, Picker, Row } from "./ui";

export const textActionLanguages = [{ id: "pt", label: "Português" }, { id: "en", label: "English" },
  { id: "es", label: "Español" }, { id: "de", label: "Deutsch" }, { id: "ru", label: "Русский" }];

type EditingMode = "natural" | "preserve" | "light" | "clarity" | "action";

function editingMode(state: Settings): EditingMode {
  const level = state.dictationCleanupLevel;
  if (level === "preserve" || level === "light") return level;
  if (state.afterDictationTextActionId && !state.afterDictationActionPaused) return "action";
  return level === "clarity" ? "clarity" : "natural";
}

const reviewMessages = {
  disabled: "A revisão do ditado está desativada. O Clarify vai inserir a transcrição.",
  missing_model: "Escolha um modelo para revisar o ditado.",
  not_configured: "Conecte o serviço de revisão para melhorar a clareza.",
  unavailable: "O serviço de revisão está indisponível. Confira a configuração.",
};

function reviewIssue(state: Settings, mode: EditingMode) {
  if (mode !== "clarity" && mode !== "action") return undefined;
  if (state.dictationCleanupRefinementAllowed === false) return "disabled";
  const status = state.dictationReviewStatus;
  if (mode === "clarity" && status && status !== "ready") return status;
}

export function dictationOutputEditingAllowed(state: Settings) {
  const mode = editingMode(state);
  if (state.writingStyleRefinementAllowed === false || reviewIssue(state, mode)) return false;
  if (mode !== "action") return true;
  const action = state.textActions?.find(item => item.id === state.afterDictationTextActionId && item.enabled);
  const profile = state.textActionProfiles?.find(item => item.id === action?.processingProfileId);
  return !!action && profile?.available !== false;
}

export function TextEditing({ controller: c }: SettingsPageProps) {
  const modeTrigger = useRef<HTMLButtonElement>(null);
  const [choosing, setChoosing] = useState(false);
  const [saving, setSaving] = useState(false);
  const { state } = c;
  const mode = editingMode(state);
  const active = mode === "action";
  const showActions = active || choosing;
  const actions = (state.textActions ?? []).filter(action => action.enabled);
  const action = actions.find(item => item.id === state.afterDictationTextActionId);
  const profile = state.textActionProfiles?.find(item => item.id === action?.processingProfileId);
  const issue = reviewIssue(state, mode);
  const needsOutputLanguage = state.language === "auto";
  const availableActions = actions.filter(item => !needsOutputLanguage || item.kind !== "translation" || item.id === action?.id);
  const disabled = saving || !!state.textActionMutation?.busy;
  const modeHint = mode === "light"
    ? t("Ajusta apenas espaços e tabulações. Mantém hesitações, repetições e autocorreções.")
    : mode === "preserve" ? t("Mantém as palavras reconhecidas, sem revisão por IA. Dicionário e snippets continuam ativos.") : undefined;

  async function chooseAction(id: string) {
    const selected = availableActions.find(item => item.id === id);
    if (disabled || !selected || !state.textActionContext || (id === action?.id && active)) return;
    const language = selected.kind === "translation" ? state.language : "auto";
    if (selected.kind === "translation" && language === "auto") return;
    setSaving(true);
    try {
      if (await c.run("setDictationPostProcessing", "action", id, language, state.textActionContext, state.textActionsRevision ?? "")) {
        setChoosing(false);
      }
    } finally { setSaving(false); }
  }

  return <>
    <Row title={t("Após o ditado")} hint={showActions ? undefined : modeHint}>
      <Picker triggerRef={modeTrigger} literalLabels label={t("Após o ditado")} value={showActions ? "action" : mode} disabled={disabled}
        options={[
          { id: "preserve", label: t("Manter minhas palavras") },
          { id: "clarity", label: t("Melhorar a clareza") },
          ...(!state.afterDictationActionPaused ? [{ id: "action", label: t("Aplicar uma ação salva") }] : []),
          ...(mode === "light" ? [{ id: "light", label: t("Ajustes mínimos") }] : []),
          ...(mode === "natural" ? [{ id: "natural", label: t("Instruções atuais") }] : []),
        ]}
        onChange={async value => {
          if (disabled) return;
          if (value === "action") { setChoosing(true); return; }
          if (value === mode) { setChoosing(false); return; }
          if (value !== "clarity" && value !== "preserve") return;
          setSaving(true);
          try {
            if (await c.run("setDictationCleanupLevel", value)) setChoosing(false);
          } finally { setSaving(false); }
        }} />
    </Row>
    {issue && <div>
      <p className="hint" role="status">{t(reviewMessages[issue])}</p>
      {!state.accountState?.managed && <Button variant="text" onClick={() => void c.openModelsTab("review")}>{t("Configurar revisão")}</Button>}
    </div>}
    {state.afterDictationActionPaused && <p className="hint" role="status">{t("apple_clarity_actions_paused")}</p>}
    {showActions && <>
      <Row title={t("Ação de texto")}>
        <Picker literalLabels label={t("Ação de texto")} value={active ? action?.id ?? "" : ""} disabled={disabled || !state.textActionContext || !availableActions.length}
          options={[{ id: "", label: t("Escolher ação") }, ...availableActions.map(item => ({ id: item.id, label: actionDisplayName(item) }))]}
          onChange={id => void chooseAction(id)} />
      </Row>
      {needsOutputLanguage && actions.some(item => item.kind === "translation") &&
        <p className="hint" role="status">{t("Para traduzir, escolha um idioma de saída.")}</p>}
      {!state.textActionContext ? <div>
        <p className="hint" role="status">{t("Não foi possível carregar as ações. Atualize para tentar novamente.")}</p>
        <Button disabled={disabled} onClick={() => void c.run("refreshTextActions")}>{t("Atualizar ações")}</Button>
      </div> : !actions.length && <div>
        <p className="hint" role="status">{t("Nenhuma ação salva. Crie uma em Ações de texto.")}</p>
        <Button variant="text" onClick={() => void c.navigate("actions")}>{t("Abrir Ações")}</Button>
      </div>}
      {active && !action && <p className="hint" role="status">{t("A ação selecionada está indisponível. Escolha outra ação.")}</p>}
      {active && !issue && profile?.available === false && <div>
        <p className="hint" role="status">{t("Configure o modelo usado por esta ação.")}</p>
        <Button variant="text" onClick={() => void (profile.sourceScope === "refinement"
          ? c.openModelsTab("review", "refinement") : c.openModelsTab("profiles"))}>{t("Configurar modelo")}</Button>
      </div>}
      {choosing && !active && <div>
        <p className="hint" role="status">{t("Escolha uma ação para salvar. Até lá, a configuração anterior continua ativa.")}</p>
        <Button variant="text" disabled={disabled} onClick={() => { setChoosing(false); modeTrigger.current?.focus(); }}>{t("Cancelar")}</Button>
      </div>}
    </>}
  </>;
}
