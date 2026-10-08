import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
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
  const [busy, setBusy] = useState(false);
  const [navigating, setNavigating] = useState(false);
  const [saved, setSaved] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [prompt, setPrompt] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [capture, setCapture] = useState<string>();
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
          if (live) setState(s);
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
      setError("A retenção deve ser um número inteiro entre 0 e 3650 dias.");
      return false;
    }
    if (apiKey || endpoint !== state.providerBaseUrl || state.providerDirty) {
      setError("Valide ou descarte as alterações do serviço antes de salvar.");
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
  const captureHotkey = async (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape" || !capture) return;
    event.preventDefault();
    if (["Control", "Alt", "Shift", "Meta"].includes(event.key) || event.repeat)
      return;
    const modifiers = [
      ...(event.ctrlKey ? ["ctrl"] : []),
      ...(event.altKey ? ["alt"] : []),
      ...(event.shiftKey ? ["shift"] : []),
      ...(event.metaKey ? ["win"] : []),
    ];
    if (
      await run("setHotkey", capture, {
        modifiers,
        key: event.key === " " ? "SPACE" : event.key.toUpperCase(),
      })
    )
      setCapture(undefined);
  };
  const selectProvider = async (id: string) => {
    if (!state) return;
    if (apiKey || state.providerDirty || endpoint !== state.providerBaseUrl) {
      setError("Valide ou descarte as alterações antes de trocar de serviço.");
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
