import { useRef, useState } from "react";
import { t } from "../i18n";
import type { Settings, SettingsArguments, SettingsMethod, TextActionProfile, TextActionProfileWrite, TextActionProfileModels } from "./bridge";
import { settingsValuesEqual } from "./state";

type Runner = <M extends SettingsMethod>(method: M, ...args: SettingsArguments[M]) => Promise<Settings | false>;
type ProfileDraft = { value: TextActionProfileWrite; baseline: TextActionProfileWrite; context: string; revision: string; instance: string };
type ModelRequest = { id: string; generation?: number; profileId: string; providerId: string; endpoint: string; context: string; revision: string; instance: string };
const profileDirty = (draft: ProfileDraft | null) => !!draft && !settingsValuesEqual(draft.value, draft.baseline);
export const profileName = (id: string) => t(id === "default" ? "Serviço de texto" : id === "legacy-rewrite" ? "Reescrita" : id === "legacy-translation" ? "Tradução" : id);
const profileValue = ({ id, providerId, modelId, customEndpoint, enabled }: TextActionProfile): TextActionProfileWrite => ({ id, providerId, modelId, customEndpoint, enabled });

export function useTextProfileEditor(state: Settings | undefined, run: Runner) {
  const current = useRef(state); current.current = state;
  const [editor, render] = useState<ProfileDraft | null>(null);
  const live = useRef(editor);
  const update = (value: ProfileDraft | null) => { live.current = value; render(value); };
  const [saving, renderSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState("");
  const [discardRequested, setDiscardRequested] = useState(false);
  const [modelRequest, renderModelRequest] = useState<ModelRequest | null>(null);
  const modelRequestRef = useRef(modelRequest);
  const setModelRequest = (request: ModelRequest | null) => { modelRequestRef.current = request; renderModelRequest(request); };
  const cancelModels = () => {
    if (modelRequestRef.current) void run("cancelTextActionProfileModels");
    setModelRequest(null);
  };
  const loadModels = async (refresh = false) => {
    const draft = live.current;
    if (!draft || draft.context !== current.current?.textActionContext) return;
    const request: ModelRequest = { id: crypto.randomUUID(), profileId: draft.value.id,
      providerId: draft.value.providerId, endpoint: draft.value.customEndpoint.trim().replace(/\/+$/, ""),
      context: draft.context, revision: draft.revision, instance: draft.instance };
    setModelRequest(request); setError("");
    const result = await run(refresh ? "refreshTextActionProfileModels" : "loadTextActionProfileModels",
      request.profileId, request.providerId, request.endpoint, request.context, request.revision, request.id);
    if (modelRequestRef.current !== request) return;
    if (!result || result.textActionProfileModels?.requestId !== request.id) {
      setModelRequest(null); setError(t("Não foi possível carregar os modelos deste perfil.")); return;
    }
    setModelRequest({ ...request, generation: result.textActionProfileModels.generation });
  };
  const open = (profile: TextActionProfile) => {
    if (profile.managed || !current.current?.textActionContext || savingRef.current) return;
    const value = profileValue(profile);
    update({ value, baseline: value, context: current.current.textActionContext, revision: current.current.textActionsRevision ?? "", instance: crypto.randomUUID() });
    setError(""); setDiscardRequested(false);
    void loadModels();
  };
  const change = (patch: Partial<TextActionProfileWrite>) => {
    const before = live.current;
    if (before) update({ ...before, value: { ...before.value, ...patch } });
    setError("");
    if (patch.providerId !== undefined && patch.providerId !== before?.value.providerId) void loadModels();
    else if (patch.customEndpoint !== undefined && patch.customEndpoint !== before?.value.customEndpoint) cancelModels();
  };
  const close = (force = false) => {
    if (savingRef.current) return;
    if (!force && profileDirty(live.current)) { setDiscardRequested(true); return; }
    update(null); cancelModels(); setDiscardRequested(false); setError("");
  };
  const activeCatalog = (): TextActionProfileModels | null => {
    const request = modelRequestRef.current, draft = live.current, catalog = current.current?.textActionProfileModels;
    if (!request || !draft || !catalog || request.generation === undefined || catalog.generation !== request.generation ||
      catalog.requestId !== request.id || request.instance !== draft.instance || catalog.profileId !== draft.value.id ||
      catalog.providerId !== draft.value.providerId || catalog.customEndpoint !== draft.value.customEndpoint.trim().replace(/\/+$/, "") ||
      catalog.context !== draft.context || catalog.revision !== draft.revision || draft.context !== current.current?.textActionContext) return null;
    return catalog;
  };
  const needsVerifiedModel = (draft: ProfileDraft) => draft.value.providerId === "chatgpt" &&
    (draft.baseline.providerId !== "chatgpt" || draft.value.modelId !== draft.baseline.modelId);
  const save = async () => {
    const captured = live.current;
    if (!captured || !profileDirty(captured)) return true;
    if (savingRef.current) return false;
    if (captured.context !== current.current?.textActionContext) {
      setError(t("A conta mudou. Abra o perfil novamente antes de salvar.")); return false;
    }
    const catalog = activeCatalog();
    if (needsVerifiedModel(captured) && (catalog?.status !== "ready" || !catalog.models.some(model => model.id === captured.value.modelId))) {
      setError(t("Escolha um modelo do catálogo atual antes de salvar.")); return false;
    }
    savingRef.current = true; renderSaving(true); setError("");
    try {
      const result = await run("saveTextActionProfile", captured.value, captured.context, captured.revision,
        needsVerifiedModel(captured) ? catalog?.requestKey ?? "" : "");
      if (!result || result.textActionContext !== captured.context) {
        setError(t("Não foi possível salvar o perfil. Suas alterações foram mantidas.")); return false;
      }
      const saved = result.textActionProfiles?.find(profile => profile.id === captured.value.id);
      if (!saved) { setError(t("Não foi possível confirmar o perfil salvo.")); return false; }
      if (live.current === captured) { update(null); cancelModels(); setDiscardRequested(false); }
      else if (live.current?.context === captured.context) {
        update({ ...live.current, baseline: profileValue(saved), revision: result.textActionsRevision ?? "" });
        void loadModels();
      }
      return true;
    } finally { savingRef.current = false; renderSaving(false); }
  };
  const catalog = activeCatalog();
  const models = catalog?.models ?? [];
  const status = catalog?.status ?? (modelRequest && modelRequest.generation === undefined ? "loading" : modelRequest ? "stale" : "idle");
  const canSaveModel = !editor || !needsVerifiedModel(editor) || (catalog?.status === "ready" && models.some(model => model.id === editor.value.modelId));
  return { editor, dirty: profileDirty(editor), isDirty: () => profileDirty(live.current), saving, error, models, modelStatus: status, canSaveModel, loadModels,
    discardRequested, setDiscardRequested, open, change, close, save };
}
