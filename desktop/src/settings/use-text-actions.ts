import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { t } from "../i18n";
import type { Settings, SettingsArguments, SettingsMethod, TextAction, TextActionWrite, HotkeyDefinition } from "./bridge";
import { settingsValuesEqual } from "./state";

type Runner = <M extends SettingsMethod>(method: M, ...args: SettingsArguments[M]) => Promise<Settings | false>;
type Editor = {
  action: TextActionWrite; baseline: TextActionWrite | null; context: string; revision: string;
  savedRevision: number; isNew: boolean;
};
type ActionConflict = { action: TextAction | null; context: string; revision: string; actionId: string };
const writable = ({ revision: _revision, ...action }: TextAction): TextActionWrite => action;
const isDirty = (editor: Editor | null) => !!editor && !settingsValuesEqual(editor.action, editor.baseline);
export const actionDisplayName = (action: Pick<TextAction, "id" | "name">) =>
  (action.id === "rewrite" && action.name === "Rewrite") || (action.id === "translation" && action.name === "Translation") ? t(action.name) : action.name;

export function hotkeyLabel(value: HotkeyDefinition | null | undefined) {
  if (!value) return "";
  const names: Record<string, string> = { ctrl: "Ctrl", alt: "Alt", shift: "Shift", win: "Win" };
  return [...value.modifiers.map(modifier => names[modifier] ?? modifier), value.key].join("+");
}

export function useTextActions(state: Settings | undefined, run: Runner) {
  const current = useRef(state); current.current = state;
  const [editor, renderEditor] = useState<Editor | null>(null);
  const editorRef = useRef(editor);
  const setEditor = (value: Editor | null) => { editorRef.current = value; renderEditor(value); };
  const [error, setError] = useState("");
  const [saving, renderSaving] = useState(false);
  const savingRef = useRef(false);
  const [refreshing, renderRefreshing] = useState(false);
  const refreshingRef = useRef(false);
  const [conflict, renderConflict] = useState<ActionConflict | null>(null);
  const conflictRef = useRef(conflict);
  const setConflict = (value: ActionConflict | null) => { conflictRef.current = value; renderConflict(value); };
  const [capturing, renderCapturing] = useState(false);
  const [captureStarting, setCaptureStarting] = useState(false);
  const capturingRef = useRef(false);
  const captureEpoch = useRef(0);
  const modifier = useRef<string | null>(null);
  const [discardRequested, renderDiscardRequested] = useState(false);
  const dismissEpoch = useRef(0);
  const setDiscardRequested = (value: boolean) => { dismissEpoch.current += 1; renderDiscardRequested(value); };
  const [deleting, setDeleting] = useState<{ action: TextAction; context: string; revision: string } | null>(null);
  const [sample, renderSample] = useState("");
  const sampleRef = useRef(sample);
  const [sampleLanguage, renderSampleLanguage] = useState("");
  const [preview, setPreview] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const previewRequest = useRef<{ actionId: string; revision: number; context: string; sample: string; generation?: number } | null>(null);
  const invalidatePreview = () => {
    const active = previewRequest.current;
    previewRequest.current = null; setPreview(""); setPreviewing(false);
    if (active) void run("cancelTextActionPreview");
  };

  const cancelCapture = useCallback(async () => {
    captureEpoch.current += 1; modifier.current = null;
    if (!capturingRef.current) return true;
    const result = await run("endTextActionHotkeyCapture");
    setCaptureStarting(false);
    if (!result) {
      renderCapturing(true); setError(t("Não foi possível restaurar os atalhos. Tente cancelar a captura novamente.")); return false;
    }
    capturingRef.current = false; renderCapturing(false);
    return true;
  }, [run]);
  useEffect(() => {
    const hidden = () => { if (document.hidden) void cancelCapture(); };
    document.addEventListener("visibilitychange", hidden);
    return () => { document.removeEventListener("visibilitychange", hidden); };
  }, [cancelCapture]);

  const open = (action?: TextAction, duplicate = false) => {
    const snapshot = current.current;
    if (!snapshot?.textActionContext || savingRef.current || refreshingRef.current) return;
    const value = action ? writable(action) : {
      id: crypto.randomUUID(), name: "", prompt: "", kind: "custom" as const,
      enabled: true, processingProfileId: "default", shortcut: null,
    };
    const draft = duplicate ? { ...value, id: crypto.randomUUID(), name: t("Cópia de {name}", { name: value.name }), shortcut: null } : value;
    setEditor({ action: draft, baseline: duplicate ? null : value, context: snapshot.textActionContext,
      revision: snapshot.textActionsRevision ?? "", savedRevision: !action || duplicate ? 0 : action.revision, isNew: !action || duplicate });
    setError(""); setDiscardRequested(false); renderSample(""); sampleRef.current = ""; renderSampleLanguage("");
    setConflict(null);
    setPreview(""); setPreviewing(false); previewRequest.current = null;
  };
  const change = (patch: Partial<TextActionWrite>) => {
    const value = editorRef.current;
    if (!value) return;
    setEditor({ ...value, action: { ...value.action, ...patch } });
    setError(""); invalidatePreview();
  };
  const close = async (force = false) => {
    if (savingRef.current) return false;
    if (!force && isDirty(editorRef.current)) { setDiscardRequested(true); return false; }
    if (!await cancelCapture()) return false;
    setEditor(null); setDiscardRequested(false); setError("");
    setConflict(null);
    invalidatePreview(); return true;
  };
  const save = async (closeAfter = false) => {
    const captured = editorRef.current;
    if (!captured || !isDirty(captured)) return true;
    if (savingRef.current || capturingRef.current || refreshingRef.current || conflictRef.current) return false;
    if (captured.context !== current.current?.textActionContext) {
      setError(t("A conta ou o servidor mudou. Copie suas instruções antes de fechar este editor.")); return false;
    }
    if (!captured.action.name.trim() || captured.action.name.length > 80 || !captured.action.prompt.trim() ||
      new TextEncoder().encode(captured.action.prompt).length > 8192) {
      setError(t("Informe um nome de até 80 caracteres e instruções de até 8 KiB.")); return false;
    }
    const dismiss = dismissEpoch.current;
    savingRef.current = true; renderSaving(true); setError("");
    try {
      const result = await run("saveTextAction", captured.action, captured.context, captured.revision);
      if (!result) { setError(t("Não foi possível salvar a ação. Suas alterações foram mantidas.")); return false; }
      const saved = result.textActions?.find(action => action.id === captured.action.id);
      if (!saved || result.textActionContext !== captured.context) {
        setError(t("Não foi possível confirmar a ação salva. Suas alterações foram mantidas.")); return false;
      }
      const live = editorRef.current;
      if (live?.context === captured.context && live.action.id === captured.action.id) {
        setEditor({ ...live, baseline: writable(saved), action: live === captured ? writable(saved) : live.action,
          revision: result.textActionsRevision ?? "", savedRevision: saved.revision, isNew: false });
      }
      if (closeAfter && dismiss === dismissEpoch.current && !isDirty(editorRef.current)) {
        setEditor(null); previewRequest.current = null; setPreview("");
      }
      setDiscardRequested(false);
      return true;
    } finally { savingRef.current = false; renderSaving(false); }
  };
  const beginCapture = async () => {
    const value = editorRef.current;
    if (!value || capturingRef.current || value.context !== current.current?.textActionContext) return;
    const epoch = ++captureEpoch.current;
    capturingRef.current = true; setCaptureStarting(true); modifier.current = null;
    const result = await run("beginTextActionHotkeyCapture", value.context);
    if (epoch === captureEpoch.current) {
      setCaptureStarting(false);
      if (result) renderCapturing(true);
      else {
        capturingRef.current = false; setError(t("Não foi possível iniciar a captura do atalho."));
      }
    }
  };
  const applyShortcut = async (shortcut: HotkeyDefinition) => {
    change({ shortcut }); await cancelCapture();
  };
  const captureKey = async (event: KeyboardEvent<HTMLInputElement>) => {
    if (!capturingRef.current) return;
    event.preventDefault(); event.stopPropagation();
    if (event.key === "Escape") { await cancelCapture(); return; }
    if (event.repeat) return;
    const key = ({ Control: "CTRL", Alt: "ALT", Shift: "SHIFT", Meta: "WIN" } as Record<string, string>)[event.key];
    if (event.type === "keydown" && key) { modifier.current = event.key; return; }
    if (event.type === "keyup" && (!key || modifier.current !== event.key)) return;
    modifier.current = null;
    const modifiers = [...(event.ctrlKey ? ["ctrl"] : []), ...(event.altKey ? ["alt"] : []),
      ...(event.shiftKey ? ["shift"] : []), ...(event.metaKey ? ["win"] : [])];
    await applyShortcut({ key: key || (event.key === " " ? "SPACE" : event.key.toUpperCase()),
      modifiers: modifiers.filter(value => value.toUpperCase() !== key) });
  };
  const captureMouse = async (event: MouseEvent<HTMLInputElement>) => {
    if (!capturingRef.current || ![3, 4].includes(event.button)) return;
    event.preventDefault(); event.stopPropagation();
    await applyShortcut({ key: event.button === 3 ? "XBUTTON1" : "XBUTTON2",
      modifiers: [...(event.ctrlKey ? ["ctrl"] : []), ...(event.altKey ? ["alt"] : []),
        ...(event.shiftKey ? ["shift"] : []), ...(event.metaKey ? ["win"] : [])] });
  };
  const toggle = async (action: TextAction, enabled: boolean) => {
    const snapshot = current.current;
    if (!snapshot?.textActionContext || savingRef.current || refreshingRef.current) return;
    savingRef.current = true; renderSaving(true);
    try { await run("saveTextAction", { ...writable(action), enabled }, snapshot.textActionContext, snapshot.textActionsRevision ?? ""); }
    finally { savingRef.current = false; renderSaving(false); }
  };
  const requestDelete = (action: TextAction) => {
    const snapshot = current.current;
    if (snapshot?.textActionContext && !savingRef.current && !refreshingRef.current) {
      setError(""); setDeleting({ action, context: snapshot.textActionContext, revision: snapshot.textActionsRevision ?? "" });
    }
  };
  const confirmDelete = async () => {
    if (!deleting || savingRef.current || refreshingRef.current) return;
    savingRef.current = true; renderSaving(true);
    try {
      const result = await run("deleteTextAction", deleting.action.id, deleting.context, deleting.revision);
      if (result) setDeleting(null);
      else setError(t("Não foi possível excluir a ação. Atualize a lista e tente novamente."));
    } finally { savingRef.current = false; renderSaving(false); }
  };
  const refresh = async () => {
    if (savingRef.current || refreshingRef.current || capturingRef.current) return false;
    const captured = editorRef.current;
    refreshingRef.current = true; renderRefreshing(true); setError(""); invalidatePreview();
    try {
      const result = await run("refreshTextActions");
      if (!result) { setError(t("Não foi possível atualizar as ações. Seu rascunho foi mantido.")); return false; }
      const live = editorRef.current;
      if (captured && live?.action.id === captured.action.id && live.context === captured.context) {
        if (result.textActionContext !== captured.context) {
          setError(t("A conta ou o servidor mudou. Copie suas instruções antes de fechar este editor.")); return false;
        }
        const saved = result.textActions?.find(action => action.id === live.action.id);
        if ((!saved && live.isNew) || (saved && (settingsValuesEqual(writable(saved), live.baseline) || settingsValuesEqual(writable(saved), live.action)))) {
          setEditor({ ...live, baseline: saved ? writable(saved) : live.baseline,
            revision: result.textActionsRevision ?? "", savedRevision: saved?.revision ?? 0, isNew: !saved });
          setConflict(null);
        } else setConflict({ action: saved ?? null, context: captured.context, revision: result.textActionsRevision ?? "", actionId: live.action.id });
      }
      setDeleting(null);
      return true;
    } finally { refreshingRef.current = false; renderRefreshing(false); }
  };
  const resolveConflict = (useSaved: boolean) => {
    const changed = conflictRef.current, live = editorRef.current;
    if (!changed || !live || changed.context !== current.current?.textActionContext || changed.actionId !== live.action.id) return;
    if (useSaved && !changed.action) return;
    const saved = changed.action ? writable(changed.action) : null;
    setEditor({ ...live, action: useSaved ? saved! : saved ? live.action : { ...live.action, id: crypto.randomUUID() },
      baseline: saved, revision: changed.revision, savedRevision: changed.action?.revision ?? 0, isNew: !saved });
    setConflict(null); setError(""); invalidatePreview();
  };
  const setSample = (value: string) => {
    sampleRef.current = value; renderSample(value); invalidatePreview();
  };
  const setSampleLanguage = (value: string) => { renderSampleLanguage(value); invalidatePreview(); };
  const test = async () => {
    const value = editorRef.current;
    if (!value || isDirty(value) || !sampleRef.current.trim() || previewing || current.current?.textActionPreview?.busy ||
      (value.action.kind === "translation" && !sampleLanguage)) return;
    const request: NonNullable<typeof previewRequest.current> = { actionId: value.action.id, revision: value.savedRevision, context: value.context, sample: sampleRef.current };
    previewRequest.current = request; setPreviewing(true); setError(""); setPreview("");
    const result = await run("previewTextAction", request.actionId, request.sample, request.context, request.revision, sampleLanguage || "auto");
    if (previewRequest.current !== request) return;
    if (!result) { setPreviewing(false); setError(t("Não foi possível testar a ação.")); return; }
    const outcome = result.textActionPreview;
    request.generation = outcome?.generation;
    if (!outcome?.busy) {
      setPreview(outcome?.text ?? ""); setError(outcome?.error ?? ""); setPreviewing(false);
    }
  };
  useEffect(() => {
    const request = previewRequest.current, outcome = state?.textActionPreview;
    if (!request || request.generation === undefined || !outcome || outcome.generation !== request.generation ||
      outcome.busy || request.context !== state?.textActionContext || request.sample !== sampleRef.current) return;
    setPreview(outcome.text ?? ""); setError(outcome.error ?? ""); setPreviewing(false);
  }, [state?.textActionPreview, state?.textActionContext]);

  return { editor, dirty: isDirty(editor), isDirty: () => isDirty(editorRef.current),
    error, saving, refreshing, refresh, conflict, resolveConflict, capturing, captureStarting, discardRequested, setDiscardRequested, open, change, close, save,
    beginCapture, cancelCapture, captureKey, captureMouse, toggle, deleting, requestDelete,
    cancelDelete: () => { if (!savingRef.current) { setDeleting(null); setError(""); } }, confirmDelete, sample, setSample, sampleLanguage, setSampleLanguage, preview, previewing, test };
}
