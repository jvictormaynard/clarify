import { t, setUiLanguage } from "../i18n";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import {
  call,
  type DictionaryEntry,
  type Settings,
  type SettingsArguments,
  type SettingsMethod,
} from "./bridge";
import { recordingValue, type RecordingDraft } from "./recording";
import type { PageId } from "./navigation";
import { useSettingsWindow } from "./use-settings-window";

export function useSettings() {
  const [state, setState] = useState<Settings>();
  const [dictionary, setDictionary] = useState<DictionaryEntry[] | null>(null);
  const [page, setPage] = useState<PageId>("dictation");
  const [error, setError] = useState("");
  const [callBusy, setBusy] = useState(false);
  const busy = callBusy || !!state?.accountState?.busy;
  const [navigating, setNavigating] = useState(false);
  const [saved, setSaved] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [prompt, setPrompt] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const capture = state?.hotkeyCaptureAction || undefined;
  const [retention, setRetention] = useState("");
  const [recording, setRecording] = useState<RecordingDraft | null>(null);
  const [routeOverride, setRouteOverride] = useState<{
    model: string;
    endpoint: string;
  } | null>(null);
  const [confirmAction, setConfirmAction] = useState<
    "clearProvider" | "removeLocalAsr" | "resetAllHotkeys" | null
  >(null);
  const current = useRef(state);
  current.current = state;
  const pending = useRef(false);
  const localDirty =
    !!state &&
    (recording !== null ||
      routeOverride !== null ||
      prompt !== state.routePrompt ||
      endpoint !== state.providerBaseUrl ||
      apiKey !== "" ||
      retention !== String(state.historyRetentionDays ?? ""));
  const dirtyRef = useRef(false);
  dirtyRef.current =
    !!state?.dirty ||
    !!state?.providerDirty ||
    localDirty ||
    (dictionary !== null &&
      JSON.stringify(dictionary) !== JSON.stringify(state?.dictionaryEntries));
  const { closing, setClosing, closeWindow } = useSettingsWindow(
    dirtyRef,
    setError,
  );

  // Every user operation has one busy/error boundary. Multi-step operations stay
  // busy until all commands finish; navigation commits its page and data together.
  const execute = useCallback(
    async (
      operation: () => Promise<Settings>,
      navigation = false,
    ): Promise<Settings | false> => {
      pending.current = true;
      setBusy(true);
      setNavigating(navigation);
      setError("");
      setSaved(false);
      try {
        const value = await operation();
        setState(value);
        return value;
      } catch (error) {
        setError(String(error));
        return false;
      } finally {
        pending.current = false;
        setBusy(false);
        setNavigating(false);
      }
    },
    [],
  );
  const run = useCallback(
    <M extends SettingsMethod>(method: M, ...args: SettingsArguments[M]) =>
      execute(() => call(method, ...args)),
    [execute],
  );

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      if (!pending.current && !document.hidden) {
        pending.current = true;
        try {
          let s = await call("snapshot");
          if (!current.current) {
            await call("selectWorkflow", "transcription");
            s = await call("loadRouteModels");
          }
          if (live) { setUiLanguage(s.uiLanguage); setState(s); }
        } catch (e) {
          if (live) setError(String(e));
        } finally {
          pending.current = false;
        }
      }
      if (live)
        timer = setTimeout(
          refresh,
          current.current?.microphoneTestBusy ? 100 : 1000,
        );
    };
    const visibility = () => {
      if (document.hidden && current.current?.hotkeyCaptureAction)
        void call("cancelHotkeyCapture").catch((error) => {
          if (live) setError(String(error));
        });
      if (document.hidden && current.current?.microphoneTestBusy)
        void call("stopMicrophoneTest").catch((error) => {
          if (live) setError(String(error));
        });
    };
    document.addEventListener("visibilitychange", visibility);
    refresh();
    return () => {
      live = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  useEffect(() => {
    if (state) setRetention(String(state.historyRetentionDays ?? ""));
  }, [state?.historyRetentionDays]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const refreshAccount = () => {
      clearTimeout(timer);
      const account = current.current?.accountState;
      if (!account?.signedIn) return;
      const blocked = document.hidden || pending.current || dirtyRef.current || account.busy;
      if (!blocked) void call("accountCommand", "auto", "").catch(() => undefined);
      // Startup model loading can briefly block the first account refresh.
      // Retry when it clears instead of waiting a full minute with no quota.
      timer = setTimeout(refreshAccount, blocked ? 1000 : 60000);
    };
    refreshAccount();
    document.addEventListener("visibilitychange", refreshAccount);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", refreshAccount); };
  }, [state?.accountState?.signedIn]);
  useEffect(() => {
    if (state) setPrompt(state.routePrompt);
  }, [state?.routePrompt, state?.selectedScope]);
  useEffect(() => {
    if (state) setEndpoint(state.providerBaseUrl);
  }, [state?.providerBaseUrl, state?.selectedProviderId]);
  const clearDrafts = (snapshot: Settings) => {
    setDictionary(null);
    setPrompt(snapshot.routePrompt);
    setEndpoint(snapshot.providerBaseUrl);
    setRetention(String(snapshot.historyRetentionDays ?? ""));
    setApiKey("");
    setRecording(null);
    setRouteOverride(null);
  };
  const reset = async () => {
    const snapshot = await run("load");
    if (!snapshot) return false;
    clearDrafts(snapshot);
    setDiscarding(false);
    return true;
  };
  const stageRouteDraft = async (snapshot: Settings) => {
    let next = snapshot;
    if (prompt !== next.routePrompt)
      next = await call("setRoutePrompt", prompt);
    if (routeOverride) {
      next = await call("setRouteModelId", routeOverride.model);
      next = await call("setRouteCustomEndpoint", routeOverride.endpoint);
    }
    return next;
  };
  const save = async () => {
    if (!state || busy) return false;
    if (
      retention !== "" &&
      (!/^\d+$/.test(retention) || Number(retention) > 3650)
    ) {
      setError(t("A retenção deve ser um número inteiro entre 0 e 3650 dias."));
      return false;
    }
    if (apiKey || endpoint !== state.providerBaseUrl || state.providerDirty) {
      setError(t("Valide ou descarte as alterações do serviço antes de salvar."));
      return false;
    }
    const next = await execute(async () => {
      if (dictionary !== null)
        await call(
          "setDictionaryEntries",
          dictionary.map((entry) => ({
            ...entry,
            term: entry.term.trim(),
            pronunciation: entry.pronunciation.trim(),
            aliases: entry.aliases.map((alias) => alias.trim()).filter(Boolean),
          })),
        );
      if (recording)
        await call("setRecordingControls", recordingValue(recording));
      await stageRouteDraft(state);
      if (retention !== String(state.historyRetentionDays ?? "")) {
        await call(
          "setHistoryRetentionDays",
          retention === "" ? null : Number(retention),
        );
      }
      const snapshot = await call("save");
      clearDrafts(snapshot);
      setSaved(true);
      return snapshot;
    });
    return !!next;
  };
  const navigate = async (
    id: PageId,
    scope = id === "dictation" ? "transcription" : "refinement",
  ) => {
    if (
      !state ||
      busy ||
      (id === page && (id !== "text" || scope === state.selectedScope))
    )
      return;
    await execute(async () => {
      let next = await stageRouteDraft(state);
      if (next.microphoneTestBusy) next = await call("stopMicrophoneTest");
      if (id === "dictation" || id === "text") {
        next = await call("selectWorkflow", scope);
        next = await call("loadRouteModels");
      }
      if (id === "models" && next.selectedProviderId === "local_asr") {
        const provider = next.providers.find(
          (provider) => provider.id !== "local_asr",
        );
        if (provider) next = await call("selectProvider", provider.id);
      }
      setRouteOverride(null);
      setPrompt(next.routePrompt);
      setPage(id);
      return next;
    }, true);
  };

  const cancelDiscard = () => {
    setClosing(false);
    setDiscarding(false);
  };
  const discardAndClose = async () => {
    if (await reset()) {
      if (closing) await closeWindow();
      else setClosing(false);
    }
  };
  const saveAndClose = async () => {
    if (await save()) {
      if (closing) await closeWindow();
      setDiscarding(false);
    }
  };
  const confirmMutation = async () => {
    if (confirmAction && (await run(confirmAction))) {
      if (confirmAction === "clearProvider") setApiKey("");
      setConfirmAction(null);
    }
  };
  const captureModifier = useRef<string | null>(null);
  const setCapture = (action?: string) => {
    if (action) void run("beginHotkeyCapture", action);
    else void run("cancelHotkeyCapture");
  };
  useEffect(() => { captureModifier.current = null; }, [capture]);
  const captureHotkey = async (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape" || !capture) return;
    event.preventDefault();
    if (event.repeat) return;
    const modifierKey = ({ Control: "CTRL", Alt: "ALT", Shift: "SHIFT", Meta: "WIN" } as Record<string, string>)[event.key];
    if (event.type === "keydown" && modifierKey) {
      captureModifier.current = event.key;
      return;
    }
    if (event.type === "keyup" && (!modifierKey || captureModifier.current !== event.key)) return;
    captureModifier.current = null;
    const modifiers = [
      ...(event.ctrlKey ? ["ctrl"] : []),
      ...(event.altKey ? ["alt"] : []),
      ...(event.shiftKey ? ["shift"] : []),
      ...(event.metaKey ? ["win"] : []),
    ];
    await run("setHotkey", capture, {
      modifiers: modifiers.filter(name => name.toUpperCase() !== modifierKey),
      key: modifierKey || (event.key === " " ? "SPACE" : event.key.toUpperCase()),
    });
  };
  const captureMouseHotkey = async (event: MouseEvent<HTMLInputElement>) => {
    if (!capture || ![3, 4].includes(event.button)) return;
    event.preventDefault();
    captureModifier.current = null;
    await run("setHotkey", capture, {
      key: event.button === 3 ? "XBUTTON1" : "XBUTTON2",
      modifiers: [...(event.ctrlKey ? ["ctrl"] : []), ...(event.altKey ? ["alt"] : []),
        ...(event.shiftKey ? ["shift"] : []), ...(event.metaKey ? ["win"] : [])],
    });
  };
  const selectProvider = async (id: string) => {
    if (!state) return;
    if (apiKey || state.providerDirty || endpoint !== state.providerBaseUrl) {
      setError(t("Valide ou descarte as alterações antes de trocar de serviço."));
      return;
    }
    await run("selectProvider", id);
  };
  const validateProvider = async () => {
    if (!state) return;
    await execute(async () => {
      if (apiKey) await call("setProviderApiKey", apiKey);
      if (endpoint !== state.providerBaseUrl)
        await call("setProviderBaseUrl", endpoint);
      const snapshot = await call("validateProvider");
      setApiKey("");
      return snapshot;
    });
  };
  const selectRouteProvider = (id: string) =>
    execute(async () => {
      await call("setRouteProviderId", id);
      return call("loadRouteModels");
    });
  const setTextRouteEnabled = (enabled: boolean) =>
    execute(async () => {
      if (state?.selectedScope === "local_asr_refinement") {
        await call("setLocalAsrCloudRefinement", enabled);
      }
      return call("setRouteEnabled", enabled);
    });
  const useLocalModel = async () => {
    if (await run("useLocalAsr")) await navigate("dictation");
  };

  return {
    state,
    page,
    error,
    busy,
    navigating,
    saved,
    dirty: dirtyRef.current,
    dictionary,
    setDictionary,
    prompt,
    setPrompt,
    retention,
    setRetention,
    apiKey,
    setApiKey,
    endpoint,
    setEndpoint,
    recording,
    setRecording,
    routeOverride,
    setRouteOverride,
    closing,
    setClosing,
    discarding,
    setDiscarding,
    capture,
    setCapture,
    confirmAction,
    setConfirmAction,
    setError,
    run,
    save,
    navigate,
    cancelDiscard,
    discardAndClose,
    saveAndClose,
    confirmMutation,
    captureHotkey,
    captureMouseHotkey,
    selectProvider,
    validateProvider,
    selectRouteProvider,
    setTextRouteEnabled,
    useLocalModel,
  };
}

export type SettingsController = ReturnType<typeof useSettings>;
export type SettingsPageProps = {
  controller: SettingsController & { state: Settings };
};
