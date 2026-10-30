import { useRef, useState } from "react";
import { t } from "../i18n";
import type { ApplicationWritingStyle, Settings, SettingsArguments, SettingsMethod, WritingStyle } from "./bridge";
import { settingsValuesEqual } from "./state";

type Runner = <M extends SettingsMethod>(method: M, ...args: SettingsArguments[M]) => Promise<Settings | false>;
type AppStyleDraft = { executable: string; style: WritingStyle; baseline: ApplicationWritingStyle; isNew: boolean; context: string };
const dirty = (value: AppStyleDraft | null) => !!value && !settingsValuesEqual({ executable: value.executable, style: value.style }, value.baseline);

export function applicationName(executable: string) {
  return executable.split(/[\\/]/).pop()?.replace(/\.exe$/i, "") || executable;
}

export function useAppStyleEditor(state: Settings | undefined, run: Runner) {
  const current = useRef(state); current.current = state;
  const [editor, render] = useState<AppStyleDraft | null>(null);
  const live = useRef(editor);
  const update = (value: AppStyleDraft | null) => { live.current = value; render(value); };
  const [saving, renderSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState("");
  const [discardRequested, setDiscardRequested] = useState(false);
  const open = (rule?: ApplicationWritingStyle) => {
    const value = rule ?? { executable: current.current?.applicationStyleTarget ?? "", style: "casual" };
    update({ ...value, baseline: value, isNew: !rule, context: current.current?.snippetContext ?? "" });
    setError(""); setDiscardRequested(false);
  };
  const change = (patch: Partial<ApplicationWritingStyle>) => {
    if (live.current) update({ ...live.current, ...patch });
    setError("");
  };
  const close = (force = false) => {
    if (savingRef.current) return;
    if (!force && dirty(live.current)) { setDiscardRequested(true); return; }
    update(null); setDiscardRequested(false); setError("");
  };
  const save = async () => {
    const captured = live.current;
    if (!captured || (!captured.isNew && !dirty(captured))) return true;
    if (savingRef.current || !captured.executable.trim()) return false;
    if (captured.context !== current.current?.snippetContext) {
      setError(t("A conta mudou. Abra a regra novamente antes de salvar.")); return false;
    }
    savingRef.current = true; renderSaving(true); setError("");
    try {
      const result = await run("setApplicationWritingStyle", captured.executable, captured.style);
      if (!result) { setError(t("Não foi possível salvar a regra. Suas alterações foram mantidas.")); return false; }
      if (live.current === captured) { update(null); setDiscardRequested(false); }
      else if (live.current?.context === captured.context) update({ ...live.current, baseline: { executable: captured.executable, style: captured.style }, isNew: false });
      return true;
    } finally { savingRef.current = false; renderSaving(false); }
  };
  return { editor, dirty: dirty(editor), isDirty: () => dirty(live.current), saving, error, discardRequested, setDiscardRequested, open, change, close, save };
}
