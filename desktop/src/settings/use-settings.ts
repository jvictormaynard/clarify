import { t, setUiLanguage } from "../i18n";
import {
  useCallback, useEffect, useMemo, useRef, useState,
  type KeyboardEvent, type MouseEvent, type SetStateAction,
} from "react";
import {
  call, pollSettings, preferenceMethods, settingsTransaction, historyCorrection,
  type DictionaryEntry, type Snippet, type Settings, type SettingsArguments,
  type SettingsMethod, type SettingsCall, type PreferenceMethod,
} from "./bridge";
import { recordingDraft, recordingValue, type RecordingDraft } from "./recording";
import type { PageId } from "./navigation";
import { useSettingsWindow } from "./use-settings-window";
import { mergeSettings, settingsValuesEqual } from "./state";
import { dictionaryIdentity } from "./dictionary-identity";

type RouteOverride = { model?: string; endpoint?: string };
type RouteDraft = { prompt?: string; override?: RouteOverride };
type RouteBaseline = { prompt: string; model: string; endpoint: string; provider?: string };
type LibraryField = "enabled" | "case_sensitive";
type LibraryIdentity<T> = {
  persisted: T | null;
  editedFields?: Set<string>;
  revisions?: Partial<Record<LibraryField, number>>;
  inFlight?: Partial<Record<LibraryField, boolean>>;
  // Flags changed before a new row had an identity survive a failed replay.
  pending?: Partial<Record<LibraryField, boolean>>;
};
type ConfirmationAction = "clearProvider" | "removeLocalAsr" | "resetAllHotkeys";
type LibraryBaseline<T> = { entry: T | null; identity: LibraryIdentity<T> };
type LibraryDraft<T> = { entries: T[]; identities: LibraryIdentity<T>[]; baseline: LibraryBaseline<T>[]; context: string };

// Update the ref at the input event, before React renders. An async completion
// can then clear its own revision without clearing a newer edit.
function useDraft<T>(initial: T) {
  const [value, update] = useState(initial);
  const ref = useRef(value);
  const set = useCallback((next: SetStateAction<T>) => {
    ref.current = typeof next === "function" ? (next as (previous: T) => T)(ref.current) : next;
    update(ref.current);
  }, []);
  return [value, set, ref] as const;
}

function libraryDraft<T extends DictionaryEntry | Snippet>(entries: T[], previous: LibraryDraft<T> | null, persisted: T[], context: string, identify: (entry: T) => LibraryIdentity<T>): LibraryDraft<T> {
  const before = previous?.entries ?? persisted;
  const identities = previous?.identities ?? persisted.map(entry => identify(entry));
  const nextIdentities = entries.map((entry, index) => {
    const oldIndex = before.indexOf(entry);
    if (oldIndex >= 0) return identities[oldIndex];
    // Page editors replace one row at a time; add/remove keep other references.
    if (entries.length !== before.length) return { persisted: null };
    const identity = identities[index];
    if (!identity.persisted && "term" in entry) {
      for (const field of Object.keys(entry) as (keyof T & string)[]) {
        if (!settingsValuesEqual(entry[field], before[index][field])) (identity.editedFields ??= new Set()).add(field);
      }
    }
    return identity;
  });
  const baseline = previous?.baseline ?? persisted.map((entry, index) => ({ entry, identity: identities[index] }));
  return {
    entries, identities: nextIdentities, context: previous?.context ?? context,
    // Keep removed tokens too, including new rows removed during a pending Save.
    baseline: [...baseline, ...nextIdentities.filter(identity => !baseline.some(row => row.identity === identity))
      .map(identity => ({ identity, entry: null }))],
  };
}

function rebaseSubmittedLibrary<T extends DictionaryEntry | Snippet>(
  live: LibraryDraft<T> | null, captured: LibraryDraft<T> | null,
  submittedDraft: LibraryDraft<T> | null, submitted: T[],
): LibraryDraft<T> | null {
  if (!live || !captured || !submittedDraft || live === captured || live.context !== captured.context) return live;
  const before = new Map(captured.identities.map((identity, index) => [identity, captured.entries[index]]));
  const sent = new Map(submittedDraft.identities.map((identity, index) => [identity, submitted[index]]));
  return {
    ...live,
    entries: live.entries.map((entry, index) => {
      const identity = live.identities[index], original = before.get(identity), saved = sent.get(identity);
      if (!original || !saved) return entry;
      const merged = { ...entry };
      // Untouched fields follow the submitted revision. Later edits, including
      // a return to the old persisted value, stay relative to that revision.
      for (const field of Object.keys(entry) as (keyof T)[]) {
        if (settingsValuesEqual(entry[field], original[field])) merged[field] = saved[field];
      }
      return settingsValuesEqual(entry, merged) ? entry : merged;
    }),
    baseline: live.baseline.map(row => sent.has(row.identity) ? { ...row, entry: sent.get(row.identity)! } : row),
  };
}

function reconcileLibrary<T extends DictionaryEntry | Snippet>(
  draft: LibraryDraft<T> | null, incoming: T[], context: string,
  identify: (entry: T, identity?: LibraryIdentity<T>) => LibraryIdentity<T>,
): LibraryDraft<T> | null {
  if (!draft || draft.context !== context) return draft;
  const key = (entry: T) => "term" in entry ? dictionaryIdentity(entry.term) : entry.trigger.trim().normalize("NFC").toLowerCase();
  const originals = new Map(draft.baseline.map(row => [row.identity, row.entry]));
  const byKey = new Map(draft.baseline.flatMap(row => {
    const saved = row.identity.persisted ?? row.entry;
    return saved ? [[key(saved), row.identity] as const] : [];
  }));
  const newDictionaryRows = new Map<string, LibraryIdentity<T> | null>();
  draft.entries.forEach((entry, index) => {
    const identity = draft.identities[index];
    if ("term" in entry && !identity.persisted && !originals.get(identity)) {
      const name = key(entry);
      newDictionaryRows.set(name, newDictionaryRows.has(name) ? null : identity);
    }
  });
  for (const [name, identity] of newDictionaryRows) {
    if (identity && !byKey.has(name)) byKey.set(name, identity);
  }
  const baseline: LibraryBaseline<T>[] = incoming.map(entry => ({ entry, identity: identify(entry, byKey.get(key(entry))) }));
  const latest = new Map<LibraryIdentity<T>, T>(baseline.map(row => [row.identity, row.entry!]));
  const present = new Set(draft.identities);
  const entries: T[] = [], identities: LibraryIdentity<T>[] = [];
  draft.entries.forEach((entry, index) => {
    const identity = draft.identities[index], original = originals.get(identity), remote = latest.get(identity);
    if (!remote && original && settingsValuesEqual(entry, original) && !Object.keys(identity.pending ?? {}).length) return;
    let merged = entry;
    if (remote && !original && "term" in entry && "term" in remote) {
      // A correction can persist a row that was still new in this draft.
      // Adopt untouched metadata; explicit edits and clearings stay local.
      merged = { ...entry,
        pronunciation: !entry.pronunciation && !identity.editedFields?.has("pronunciation") ? remote.pronunciation : entry.pronunciation,
        aliases: !entry.aliases.length && !identity.editedFields?.has("aliases") ? remote.aliases : entry.aliases,
        enabled: identity.pending?.enabled ?? (identity.editedFields?.has("enabled") || !entry.enabled ? entry.enabled : remote.enabled),
      };
    }
    if (remote && original) {
      merged = { ...entry };
      // Only fields changed locally override the incoming saved row.
      for (const field of Object.keys(entry) as (keyof T)[]) {
        if (settingsValuesEqual(entry[field], original[field])) merged[field] = remote[field];
      }
      if (settingsValuesEqual(entry, merged)) merged = entry;
    }
    for (const field of ["enabled", "case_sensitive"] as const) {
      if (identity.inFlight?.[field] !== undefined && field in merged) merged = { ...merged, [field]: identity.inFlight[field] };
    }
    entries.push(merged);
    identities.push(identity);
    if (!remote) {
      identity.persisted = null;
      baseline.push({ identity, entry: null });
    }
  });
  for (const row of baseline) {
    if (row.entry) {
      row.identity.persisted = row.entry;
      // Known missing tokens are local deletions; unknown tokens are imports.
      if (!originals.has(row.identity) && !present.has(row.identity)) {
        entries.push(row.entry);
        identities.push(row.identity);
      }
    }
  }
  for (const row of draft.baseline) {
    if (!present.has(row.identity) && !latest.has(row.identity)) baseline.push(row);
  }
  return { ...draft, entries, identities, baseline };
}

const routeMethods = new Set<SettingsMethod>([
  "setRouteProviderId", "setRouteModelId", "setRouteEnabled", "setRoutePrompt",
  "setRouteCustomEndpoint", "loadRouteModels", "refreshRouteModels",
]);
const autoPreferences = new Set<string>(preferenceMethods);

export function useSettings() {
  const [state, setState] = useState<Settings>();
  const current = useRef(state);
  const routeBaselines = useRef<Record<string, RouteBaseline>>({});
  const libraryIdentities = useRef(new WeakMap<object, LibraryIdentity<DictionaryEntry | Snippet>>());
  const identify = <T extends DictionaryEntry | Snippet>(entry: T, known?: LibraryIdentity<T>): LibraryIdentity<T> => {
    let identity = known ?? libraryIdentities.current.get(entry);
    if (!identity) {
      identity = { persisted: entry };
    }
    libraryIdentities.current.set(entry, identity);
    return identity as LibraryIdentity<T>;
  };
  const [dictionaryDraft, setDictionaryDraft, dictionaryRef] = useDraft<LibraryDraft<DictionaryEntry> | null>(null);
  const [snippetDraft, setSnippetDraft, snippetsRef] = useDraft<LibraryDraft<Snippet> | null>(null);
  const dictionary = dictionaryDraft?.entries ?? null;
  const snippets = snippetDraft?.entries ?? null;
  const setDictionary = (entries: DictionaryEntry[]) => {
    const snapshot = current.current;
    if (snapshot) setDictionaryDraft(libraryDraft(entries, dictionaryRef.current, snapshot.dictionaryEntries, snapshot.snippetContext, identify));
    setSaved(false);
  };
  const setSnippets = (entries: Snippet[]) => {
    const snapshot = current.current;
    if (snapshot) setSnippetDraft(libraryDraft(entries, snippetsRef.current, snapshot.snippets, snapshot.snippetContext, identify));
    setSaved(false);
  };
  const [page, setPage, pageRef] = useDraft<PageId>("dictation");
  const [error, setError] = useState("");
  const [callBusy, setBusy] = useState(false);
  const busy = callBusy || !!state?.accountState?.busy;
  const [routeLoading, setRouteLoading, routeLoadingRef] = useDraft(false);
  const navigationEpoch = useRef(0);
  const [saving, setSaving, savingRef] = useDraft(false);
  const [discardingDrafts, setDiscardingDrafts, resettingRef] = useDraft(false);
  const [validatingProvider, setValidatingProvider, validatingRef] = useDraft(false);
  const [selectingProvider, setSelectingProvider, selectingProviderRef] = useDraft(false);
  const [confirming, setConfirming, confirmingRef] = useDraft(false);
  const [saved, setSaved] = useState(false);
  const [accountPending, setAccountPending, accountPendingRef] = useDraft(false);
  const [discarding, setDiscarding] = useState(false);
  const [apiKey, setApiKeyDraft, apiKeyRef] = useDraft("");
  const [endpointDraft, setEndpointDraft, endpointRef] = useDraft<string | null>(null);
  const endpoint = endpointDraft ?? state?.providerBaseUrl ?? "";
  const [retentionDraft, setRetentionDraft, retentionRef] = useDraft<string | null>(null);
  const retention = retentionDraft ?? String(state?.historyRetentionDays ?? "");
  const [recording, setRecordingDraft, recordingRef] = useDraft<RecordingDraft | null>(null);
  const [routes, setRoutes, routesRef] = useDraft<Record<string, RouteDraft>>({});
  const scope = state?.selectedScope ?? "transcription";
  const prompt = routes[scope]?.prompt ?? state?.routePrompt ?? "";
  const routeOverride = routes[scope]?.override ?? null;
  const setPrompt = (value: string) => {
    const snapshot = current.current;
    if (snapshot) setRoutes(before => ({ ...before, [snapshot.selectedScope]: { ...before[snapshot.selectedScope], prompt: value } }));
    setSaved(false);
  };
  const setRouteOverride = (value: RouteOverride | null) => {
    const snapshot = current.current;
    if (snapshot) setRoutes(before => ({ ...before, [snapshot.selectedScope]: { ...before[snapshot.selectedScope], override: value ?? undefined } }));
    setSaved(false);
  };
  const setRetention = (value: string) => { setRetentionDraft(value); setSaved(false); };
  const setEndpoint = (value: string) => { if (selectingProviderRef.current) return; setEndpointDraft(value); setSaved(false); };
  const setApiKey = (value: string) => { if (selectingProviderRef.current) return; setApiKeyDraft(value); setSaved(false); };
  const setRecording = (value: RecordingDraft | null) => { setRecordingDraft(value); setSaved(false); };
  const capture = state?.hotkeyCaptureAction || undefined;
  const localProduct = (snapshot: Settings | undefined) => snapshot ? [
    snapshot.localProfileIndex, snapshot.localDeviceIndex,
    snapshot.localProfiles?.[snapshot.localProfileIndex], snapshot.localDevices?.[snapshot.localDeviceIndex],
  ] : null;
  const [confirmation, setConfirmation, confirmationRef] = useDraft<{
    action: ConfirmationAction; provider?: string; local?: ReturnType<typeof localProduct>;
  } | null>(null);
  const confirmAction = confirmation?.action ?? null;
  const setConfirmAction = (action: ConfirmationAction | null, provider = current.current?.selectedProviderId, localSnapshot = current.current) =>
    setConfirmation(action ? { action, provider: action === "clearProvider" ? provider : undefined,
      local: action === "removeLocalAsr" ? localProduct(localSnapshot) : undefined } : null);
  const pending = useRef(0);
  const pendingOperations = useRef(0);
  const needsDraftRecovery = useRef(false);
  const lifetime = useRef(0);
  const acceptState = useCallback((update: Partial<Settings>) => {
    const previous = current.current;
    const next = previous ? mergeSettings(previous, update) : update as Settings;
    if (next === previous) return;
    if (previous?.chatgptState && next.chatgptState &&
      (previous.chatgptState.generation !== next.chatgptState.generation ||
       previous.chatgptState.accountId !== next.chatgptState.accountId)) {
      // Account-scoped model overrides must not survive a session transition.
      setRoutes(before => Object.fromEntries(Object.entries(before).map(([scope, draft]) => [scope,
        routeBaselines.current[scope]?.provider === "chatgpt" ? { ...draft, override: undefined } : draft])));
    }
    if (next.dictionaryEntries !== previous?.dictionaryEntries && dictionaryRef.current)
      setDictionaryDraft(reconcileLibrary(dictionaryRef.current, next.dictionaryEntries, next.snippetContext, identify));
    if (next.snippets !== previous?.snippets && snippetsRef.current)
      setSnippetDraft(reconcileLibrary(snippetsRef.current, next.snippets, next.snippetContext, identify));
    current.current = next;
    routeBaselines.current[next.selectedScope] = {
      prompt: next.routePrompt, model: next.routeModelId, endpoint: next.routeCustomEndpoint, provider: next.routeProviderId,
    };
    setUiLanguage(next.uiLanguage);
    setState(previous => previous ? mergeSettings(previous, update) : next);
  }, []);
  const snippetsDirty = useMemo(() => snippets !== null && !settingsValuesEqual(snippets, state?.snippets), [snippets, state?.snippets]);
  const dictionaryDirty = useMemo(() => dictionary !== null && !settingsValuesEqual(dictionary, state?.dictionaryEntries), [dictionary, state?.dictionaryEntries]);
  const routeDirty = (routeScope: string) => {
    const draft = routes[routeScope];
    if (!draft) return false;
    const baseline = routeScope === state?.selectedScope ? {
      prompt: state.routePrompt, model: state.routeModelId, endpoint: state.routeCustomEndpoint,
    } : routeBaselines.current[routeScope];
    return (draft.prompt !== undefined && draft.prompt !== baseline?.prompt) ||
      (draft.override?.model !== undefined && draft.override.model !== baseline?.model) ||
      (draft.override?.endpoint !== undefined && draft.override.endpoint !== baseline?.endpoint);
  };
  const recordingDirty = !!recording && !!state && !settingsValuesEqual(
    { ...recording, enabled: state.recordingControls.vad.enabled }, recordingDraft(state.recordingControls),
  );
  const retentionDirty = !!state && retention !== String(state.historyRetentionDays ?? "");
  const providerDirty = !!apiKey || (!!state && endpoint !== state.providerBaseUrl) || !!state?.providerDirty;
  const dirtyRef = useRef(false);
  dirtyRef.current = !!state?.dirty || providerDirty || recordingDirty || retentionDirty ||
    Object.keys(routes).some(routeDirty) || snippetsDirty || dictionaryDirty;
  const pageDirty = !!state?.dirty || ({
    dictation: routeDirty("transcription") || recordingDirty,
    text: routeDirty(scope), general: retentionDirty, models: providerDirty,
    dictionary: dictionaryDirty, snippets: snippetsDirty,
  } as Partial<Record<PageId, boolean>>)[page] === true;
  const acceptedOperations = useRef(new Set<Promise<unknown>>());
  const failedOperation = useRef(false);
  const awaitAcceptedOperations = useCallback(async (isCurrent: () => boolean) => {
    // New writes can arrive while a previous batch drains. Keep inputs live and
    // include every accepted operation before allowing the native close.
    while (acceptedOperations.current.size) await Promise.all([...acceptedOperations.current]);
    const succeeded = !failedOperation.current;
    if (isCurrent()) failedOperation.current = false; // Only the active close attempt acknowledges a failure.
    return succeeded;
  }, []);
  const { closing, setClosing, closeWindow, closeRequest } = useSettingsWindow(dirtyRef, setError, awaitAcceptedOperations);
  const runHistoryCorrection = useCallback((...args: Parameters<typeof historyCorrection>) => {
    const result = historyCorrection(...args);
    if (args[0] === "confirm" || args[0] === "undo") {
      acceptedOperations.current.add(result);
      void result.then(value => {
        if (value?.error) failedOperation.current = true;
        acceptedOperations.current.delete(result);
      }, () => {
        failedOperation.current = true;
        acceptedOperations.current.delete(result);
      });
    }
    return result;
  }, []);

  // The bridge reserves the pipe for an entire operation, including accepting
  // its snapshot. Local navigation and input events never wait for that queue.
  const execute = useCallback((operation: (call: SettingsCall) => Promise<Settings | undefined>): Promise<Settings | false> => {
    const generation = lifetime.current;
    pending.current += 1;
    pendingOperations.current += 1;
    setBusy(true);
    setError("");
    setSaved(false);
    const result = (async () => {
      try {
        return await settingsTransaction(async call => {
          if (generation !== lifetime.current) return false;
          const value = await operation(call);
          if (generation !== lifetime.current) return false;
          if (value) acceptState(value);
          return value ?? current.current ?? false;
        });
      } catch (error) {
        failedOperation.current = true;
        if (generation === lifetime.current) setError(String(error));
        return false as const;
      } finally {
        pending.current -= 1;
        pendingOperations.current -= 1;
        if (generation === lifetime.current) setBusy(pendingOperations.current > 0);
      }
    })();
    acceptedOperations.current.add(result);
    void result.then(() => acceptedOperations.current.delete(result));
    return result;
  }, [acceptState]);
  const run = useCallback(<M extends SettingsMethod>(method: M, ...args: SettingsArguments[M]) => {
    const targetScope = current.current?.selectedScope;
    const accountOperation = method === "accountCommand";
    const cancellingSocial = accountOperation && args[0] === "cancel-social" && current.current?.accountState?.socialPending;
    if (accountOperation) {
      if (accountPendingRef.current || (!cancellingSocial && (current.current?.accountState?.busy || dirtyRef.current))) return Promise.resolve(false as const);
      setAccountPending(true);
    }
    const result = execute(async call => {
      if (targetScope && routeMethods.has(method) && current.current?.selectedScope !== targetScope)
        await call("selectWorkflow", targetScope);
      return autoPreferences.has(method)
        ? call("savePreference", method as PreferenceMethod, args)
        : call(method, ...args);
    });
    return accountOperation ? result.finally(() => setAccountPending(false)) : result;
  }, [execute, setAccountPending]);

  useEffect(() => {
    let live = true;
    let needsSnapshot = false;
    lifetime.current += 1;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      if (!pending.current && !document.hidden) {
        pending.current += 1;
        try {
          if (!current.current) {
            await settingsTransaction(async call => {
              await call("snapshot");
              if (!live) return;
              await call("selectWorkflow", "transcription");
              if (!live) return;
              const snapshot = await call("loadRouteModels");
              if (live) acceptState(snapshot);
            });
            needsSnapshot = false;
          } else if (needsSnapshot) {
            const snapshot = await call("snapshot");
            if (live) acceptState(snapshot);
            needsSnapshot = false;
          } else {
            const delta = await pollSettings();
            if (live) acceptState(delta);
          }
        } catch (e) {
          needsSnapshot = true;
          if (live) setError(String(e));
        } finally { pending.current -= 1; }
      }
      if (live) timer = setTimeout(refresh, current.current?.microphoneTestBusy ? 100 : 1000);
    };
    const visibility = () => {
      if (document.hidden && current.current?.hotkeyCaptureAction) void run("cancelHotkeyCapture");
      if (document.hidden && current.current?.microphoneTestBusy) void run("stopMicrophoneTest");
    };
    document.addEventListener("visibilitychange", visibility);
    void refresh();
    return () => {
      live = false;
      lifetime.current += 1;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [acceptState, run]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const refreshAccount = () => {
      clearTimeout(timer);
      const account = current.current?.accountState;
      if (!account?.signedIn) return;
      const blocked = document.hidden || pending.current || dirtyRef.current || account.busy;
      if (!blocked) void run("accountCommand", "auto", "");
      timer = setTimeout(refreshAccount, blocked ? 1000 : 60000);
    };
    refreshAccount();
    document.addEventListener("visibilitychange", refreshAccount);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", refreshAccount); };
  }, [state?.accountState?.signedIn, run]);

  const captureDrafts = (all = false) => {
    const activePage = pageRef.current;
    const activeScope = current.current?.selectedScope ?? "transcription";
    const captureRoutes = all ? routesRef.current :
      (activePage === "dictation" || activePage === "text") && routesRef.current[activeScope]
        ? { [activeScope]: routesRef.current[activeScope] } : {};
    return {
      dictionary: all || activePage === "dictionary" ? dictionaryRef.current : null,
      snippets: all || activePage === "snippets" ? snippetsRef.current : null,
      routes: captureRoutes,
      recording: all || activePage === "dictation" ? recordingRef.current : null,
      retention: all || activePage === "general" ? retentionRef.current : null,
      endpoint: all || activePage === "models" ? endpointRef.current : null,
      apiKey: all || activePage === "models" ? apiKeyRef.current : "",
    };
  };
  const hasLocalDrafts = () => !!dictionaryRef.current || !!snippetsRef.current || !!recordingRef.current ||
    retentionRef.current !== null || endpointRef.current !== null || !!apiKeyRef.current ||
    Object.keys(routesRef.current).length > 0;
  const waitingForDraftRoute = () => routeLoadingRef.current && (pageRef.current === "dictation" || pageRef.current === "text");
  const clearCapturedDrafts = (captured: ReturnType<typeof captureDrafts>) => {
    if (dictionaryRef.current === captured.dictionary) setDictionaryDraft(null);
    if (snippetsRef.current === captured.snippets) setSnippetDraft(null);
    if (recordingRef.current === captured.recording) setRecordingDraft(null);
    if (retentionRef.current === captured.retention) setRetentionDraft(null);
    if (endpointRef.current === captured.endpoint) setEndpointDraft(null);
    if (apiKeyRef.current === captured.apiKey) setApiKeyDraft("");
    setRoutes(before => Object.fromEntries(Object.entries(before).filter(([key, value]) => captured.routes[key] !== value)));
  };
  const reset = async (all = false) => {
    if (resettingRef.current || savingRef.current || (!all && waitingForDraftRoute())) return false;
    const captured = captureDrafts(all);
    setDiscardingDrafts(true);
    try {
      return !!await execute(async call => {
        const snapshot = await call("load");
        needsDraftRecovery.current = false;
        clearCapturedDrafts(captured);
        setDiscarding(false);
        return snapshot;
      });
    } finally { setDiscardingDrafts(false); }
  };
  const save = async (all = false) => {
    const snapshot = current.current;
    if (!snapshot || savingRef.current || resettingRef.current || validatingRef.current || (!all && waitingForDraftRoute())) return false;
    const captured = captureDrafts(all);
    const retained = captured.retention ?? String(snapshot.historyRetentionDays ?? "");
    if (retained !== "" && (!/^\d+$/.test(retained) || Number(retained) > 3650)) {
      setError(t("A retenção deve ser um número inteiro entre 0 e 3650 dias."));
      return false;
    }
    if (snapshot.accountState?.signedIn && captured.snippets &&
      new TextEncoder().encode(JSON.stringify(captured.snippets.entries.map(entry => ({ ...entry,
        trigger: entry.trigger.trim().normalize("NFC"), replacement: entry.replacement.normalize("NFC"),
      })))).length > 262144) {
      setError(t("Os snippets da conta excedem o limite total de 256 KiB. Reduza os textos antes de salvar."));
      return false;
    }
    if (snapshot.providerDirty || captured.apiKey || (captured.endpoint !== null && captured.endpoint !== snapshot.providerBaseUrl)) {
      setError(t("Valide ou descarte as alterações do serviço antes de salvar."));
      return false;
    }
    setSaving(true);
    try {
      return !!await execute(async call => {
        let restoreScope = current.current?.selectedScope ?? snapshot.selectedScope;
        try {
          if (needsDraftRecovery.current) {
            const restored = await call("load");
            needsDraftRecovery.current = false;
            acceptState(restored);
          }
          // Sync can advance the backend library before React receives a poll.
          // Read inside the reserved transaction before replacing either list.
          const latest = await call("snapshot");
          restoreScope = latest.selectedScope;
          // Validate the captured numeric form before sending any setter.
          const controls = captured.recording ? recordingValue({ ...captured.recording,
            enabled: current.current?.recordingControls.vad.enabled ?? captured.recording.enabled }) : null;
          if ((captured.dictionary && captured.dictionary.context !== latest.snippetContext) ||
            (captured.snippets && captured.snippets.context !== latest.snippetContext))
            throw new Error(t("A conta mudou. Descarte as alterações e tente novamente."));
          const dictionaryToSave = reconcileLibrary(captured.dictionary, latest.dictionaryEntries, latest.snippetContext, identify);
          const snippetsToSave = reconcileLibrary(captured.snippets, latest.snippets, latest.snippetContext, identify);
          needsDraftRecovery.current = true;
          const submittedSnippets = snippetsToSave?.entries.map((entry, index) => ({
            ...entry, trigger: entry.trigger.trim().normalize("NFC"), replacement: entry.replacement.normalize("NFC"),
            enabled: snippetsToSave.identities[index].pending?.enabled ?? snippetsToSave.identities[index].persisted?.enabled ?? entry.enabled,
            case_sensitive: snippetsToSave.identities[index].pending?.case_sensitive ?? snippetsToSave.identities[index].persisted?.case_sensitive ?? entry.case_sensitive,
          })) ?? [];
          if (snippetsToSave) await call("setSnippets", submittedSnippets, snippetsToSave.context, latest.snippets);
          const submittedDictionary = dictionaryToSave?.entries.map((entry, index) => ({
            ...entry, enabled: dictionaryToSave.identities[index].pending?.enabled ?? dictionaryToSave.identities[index].persisted?.enabled ?? entry.enabled,
            term: entry.term.trim().normalize("NFC"), pronunciation: entry.pronunciation.trim().normalize("NFC"),
            aliases: entry.aliases.map(alias => alias.trim().normalize("NFC")).filter(Boolean),
          })) ?? [];
          if (dictionaryToSave) await call("setDictionaryEntries", submittedDictionary, dictionaryToSave.context, latest.dictionaryEntries);
          if (controls) await call("setRecordingControls", controls);
          const savedRoutes: Record<string, RouteBaseline> = {};
          for (const [routeScope, draft] of Object.entries(captured.routes)) {
            let route = await call("selectWorkflow", routeScope);
            if (draft.prompt !== undefined) route = await call("setRoutePrompt", draft.prompt);
            if (draft.override?.model !== undefined) route = await call("setRouteModelId", draft.override.model);
            if (draft.override?.endpoint !== undefined) route = await call("setRouteCustomEndpoint", draft.override.endpoint);
            savedRoutes[routeScope] = { prompt: route.routePrompt, model: route.routeModelId, endpoint: route.routeCustomEndpoint, provider: route.routeProviderId };
          }
          if (captured.retention !== null) await call("setHistoryRetentionDays", retained === "" ? null : Number(retained));
          await call("selectWorkflow", restoreScope);
          const next = await call("save", snapshot.snippetContext);
          needsDraftRecovery.current = false;
          Object.assign(routeBaselines.current, savedRoutes);
          const bindSaved = <T extends DictionaryEntry | Snippet>(draft: LibraryDraft<T> | null, submitted: T[], entries: T[]) => {
            if (!draft) return;
            const key = (entry: T) => ("term" in entry ? entry.term : entry.trigger).trim().normalize("NFC").toLowerCase();
            const savedByKey = new Map(entries.map(entry => [key(entry), entry]));
            draft.identities.forEach((identity, index) => {
              // Sync can remove or reorder rows after staging. Match the sent
              // row, never its response position or text edited after the click.
              const entry = submitted[index] ? savedByKey.get(key(submitted[index])) : undefined;
              identity.persisted = entry ?? null;
              if (!entry) return;
              if (identity.pending?.enabled === entry.enabled) delete identity.pending.enabled;
              if ("case_sensitive" in entry && identity.pending?.case_sensitive === entry.case_sensitive) delete identity.pending.case_sensitive;
              libraryIdentities.current.set(entry, identity as LibraryIdentity<DictionaryEntry | Snippet>);
            });
          };
          bindSaved(dictionaryToSave, submittedDictionary, next.dictionaryEntries);
          bindSaved(snippetsToSave, submittedSnippets, next.snippets);
          if (dictionaryRef.current !== captured.dictionary)
            setDictionaryDraft(rebaseSubmittedLibrary(dictionaryRef.current, captured.dictionary, dictionaryToSave, submittedDictionary));
          if (snippetsRef.current !== captured.snippets)
            setSnippetDraft(rebaseSubmittedLibrary(snippetsRef.current, captured.snippets, snippetsToSave, submittedSnippets));
          clearCapturedDrafts(captured);
          setSaved(true);
          return next;
        } catch (error) {
          // Staging is private to this transaction. Restore its backend draft
          // after failure so another page cannot persist these partial setters.
          // Frontend revisions and the original error remain available to retry.
          try {
            if (needsDraftRecovery.current) {
              const restored = await call("load");
              needsDraftRecovery.current = false;
              acceptState(restored.selectedScope === restoreScope
                ? restored : await call("selectWorkflow", restoreScope));
            }
          } catch { /* Keep the original failure. */ }
          throw error;
        }
      });
    } finally { setSaving(false); }
  };
  const navigate = async (id: PageId, targetScope = id === "dictation" ? "transcription" : "refinement") => {
    const snapshot = current.current;
    if (!snapshot) return;
    const epoch = ++navigationEpoch.current;
    setPage(id);
    setSaved(false);
    const needsRoute = (id === "dictation" || id === "text") && (targetScope !== snapshot.selectedScope || pendingOperations.current > 0);
    setRouteLoading(needsRoute);
    // A local page transition has no snapshot to publish and needs no pipe call.
    const needsProvider = id === "models" && snapshot.selectedProviderId === "local_asr";
    if (!needsRoute && !needsProvider && !snapshot.microphoneTestBusy && !pendingOperations.current) return;
    await execute(async call => {
      if (epoch !== navigationEpoch.current) return;
      let next: Settings | undefined;
      if (current.current?.microphoneTestBusy) next = await call("stopMicrophoneTest");
      if (needsRoute) {
        next = await call("selectWorkflow", targetScope);
        next = await call("loadRouteModels");
      }
      if (needsProvider) {
        const provider = (next ?? current.current)?.providers.find(provider => provider.id !== "local_asr");
        if (provider) next = await call("selectProvider", provider.id);
      }
      return next;
    });
    if (epoch === navigationEpoch.current) setRouteLoading(false);
  };

  const cancelDiscard = () => { setClosing(false); setDiscarding(false); };
  const discardAndClose = async () => {
    const request = closeRequest.current;
    if (await reset(request !== null)) {
      if (request !== null && request === closeRequest.current) {
        if (!hasLocalDrafts()) await closeWindow(request, () => !hasLocalDrafts());
        else setClosing(false);
      }
    }
  };
  const saveAndClose = async () => {
    const request = closeRequest.current;
    if (await save(request !== null)) {
      // Continue editing revokes this close request, including after the click.
      if (request !== null && request === closeRequest.current) {
        if (!hasLocalDrafts()) await closeWindow(request, () => !hasLocalDrafts());
        else setClosing(false);
      }
      setDiscarding(false);
    }
  };
  const confirmMutation = async () => {
    const target = confirmationRef.current;
    if (!target || confirmingRef.current) return;
    const key = apiKeyRef.current;
    setConfirming(true);
    try {
      if (await execute(call => {
        if (target.action === "clearProvider" && (!target.provider || target.provider !== current.current?.selectedProviderId))
          throw new Error(t("O serviço mudou. Tente novamente."));
        if (target.action === "removeLocalAsr" && (!target.local || !settingsValuesEqual(target.local, localProduct(current.current))))
          throw new Error(t("O modelo local mudou. Tente novamente."));
        return autoPreferences.has(target.action)
          ? call("savePreference", target.action as PreferenceMethod, []) : call(target.action);
      })) {
        if (target.action === "clearProvider" && apiKeyRef.current === key) setApiKeyDraft("");
        if (confirmationRef.current === target) setConfirmAction(null);
      }
    } finally { setConfirming(false); }
  };
  const captureModifier = useRef<string | null>(null);
  const captureEpoch = useRef(0);
  const captureCancelled = useRef(false);
  const renderedCaptureEpoch = captureEpoch.current;
  const setCapture = (action?: string) => {
    captureEpoch.current += 1;
    captureCancelled.current = !action;
    if (action) void run("beginHotkeyCapture", action);
    else void run("cancelHotkeyCapture");
  };
  useEffect(() => {
    captureModifier.current = null;
    if (!capture) captureCancelled.current = false;
  }, [capture]);
  const activeCapture = () => !captureCancelled.current &&
    renderedCaptureEpoch === captureEpoch.current &&
    current.current?.hotkeyCaptureAction === capture ? capture : undefined;
  const captureHotkey = async (event: KeyboardEvent<HTMLInputElement>) => {
    const action = activeCapture();
    if (event.key === "Escape" || !action) return;
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
    await run("setHotkey", action, {
      modifiers: modifiers.filter(name => name.toUpperCase() !== modifierKey),
      key: modifierKey || (event.key === " " ? "SPACE" : event.key.toUpperCase()),
    });
  };
  const captureMouseHotkey = async (event: MouseEvent<HTMLInputElement>) => {
    const action = activeCapture();
    if (!action || ![3, 4].includes(event.button)) return;
    event.preventDefault();
    captureModifier.current = null;
    await run("setHotkey", action, {
      key: event.button === 3 ? "XBUTTON1" : "XBUTTON2",
      modifiers: [...(event.ctrlKey ? ["ctrl"] : []), ...(event.altKey ? ["alt"] : []),
        ...(event.shiftKey ? ["shift"] : []), ...(event.metaKey ? ["win"] : [])],
    });
  };
  const selectProvider = async (id: string) => {
    const snapshot = current.current;
    if (!snapshot || selectingProviderRef.current || validatingRef.current) return;
    if (apiKeyRef.current || snapshot.providerDirty || (endpointRef.current ?? snapshot.providerBaseUrl) !== snapshot.providerBaseUrl) {
      setError(t("Valide ou descarte as alterações antes de trocar de serviço."));
      return;
    }
    setSelectingProvider(true);
    try { await run("selectProvider", id); }
    finally { setSelectingProvider(false); }
  };
  const validateProvider = async () => {
    const snapshot = current.current;
    if (!snapshot || validatingRef.current || resettingRef.current || selectingProviderRef.current) return;
    const key = apiKeyRef.current;
    const url = endpointRef.current;
    setValidatingProvider(true);
    try {
      await execute(async call => {
        if (snapshot.selectedProviderId !== current.current?.selectedProviderId)
          throw new Error(t("O serviço mudou. Tente novamente."));
        if (key) await call("setProviderApiKey", key);
        if (url !== null && url !== snapshot.providerBaseUrl) await call("setProviderBaseUrl", url);
        const next = await call("validateProvider");
        if (apiKeyRef.current === key) setApiKeyDraft("");
        if (endpointRef.current === url) setEndpointDraft(null);
        return next;
      });
    } finally { setValidatingProvider(false); }
  };
  const selectRouteProvider = (id: string) => {
    const targetScope = current.current?.selectedScope;
    return execute(async call => {
      if (targetScope && targetScope !== current.current?.selectedScope) await call("selectWorkflow", targetScope);
      await call("savePreference", "setRouteProviderId", [id]);
      return call("loadRouteModels");
    });
  };
  const setTextRouteEnabled = (enabled: boolean) => {
    const targetScope = current.current?.selectedScope;
    return execute(async call => {
      if (targetScope && targetScope !== current.current?.selectedScope) await call("selectWorkflow", targetScope);
      if (targetScope === "local_asr_refinement") await call("savePreference", "setLocalAsrCloudRefinement", [enabled]);
      return call("savePreference", "setRouteEnabled", [enabled]);
    });
  };
  const useLocalModel = async () => {
    const epoch = navigationEpoch.current;
    if (await run("useLocalAsr") && epoch === navigationEpoch.current) await navigate("dictation");
  };

  const setLibraryPreference = async (library: "dictionary" | "snippets", index: number, field: "enabled" | "case_sensitive", value: boolean) => {
    const snapshot = current.current;
    if (!snapshot) return;
    const draft = library === "dictionary" ? dictionaryRef.current : snippetsRef.current;
    const entries = draft?.entries ?? (library === "dictionary" ? snapshot.dictionaryEntries : snapshot.snippets);
    const identity = draft ? draft.identities[index] : entries[index] ? identify(entries[index]) : undefined;
    if (!entries[index]) return;
    if (!identity) return;
    const context = draft?.context ?? snapshot.snippetContext;
    identity.revisions ??= {};
    const revision = (identity.revisions[field] ?? 0) + 1;
    identity.revisions[field] = revision;
    if (!identity.persisted || identity.pending?.[field] !== undefined) {
      identity.pending ??= {};
      identity.pending[field] = value;
      if (library === "dictionary") setDictionary((entries as DictionaryEntry[]).map((entry, i) => i === index ? { ...entry, enabled: value } : entry));
      else setSnippets((entries as Snippet[]).map((entry, i) => i === index ? { ...entry, [field]: value } : entry));
      // A Save in flight will bind this token to its saved row. Queue the flag
      // behind that Save; a row outside the captured Save stays a local draft.
      if (!identity.persisted && !savingRef.current) return;
    }
    identity.inFlight ??= {};
    identity.inFlight[field] = value;
    try { await execute(async call => {
      const live = library === "dictionary" ? dictionaryRef.current : snippetsRef.current;
      if (!identity.persisted || (live && !live.identities.some(token => token === identity))) return;
      const next = await call("saveLibraryPreference", library, identity.persisted, field, value, context);
      // Merge the saved flag into the live row, preserving text typed meanwhile.
      // The identity token follows the row through edits and deletions.
      if (library === "dictionary") {
        const live = dictionaryRef.current;
        if (live && live.context === context && identity.revisions?.[field] === revision) {
          const row = live.identities.indexOf(identity as LibraryIdentity<DictionaryEntry>);
          if (row >= 0) setDictionaryDraft({ ...live, entries: live.entries.map((entry, i) => i === row ? { ...entry, enabled: value } : entry) });
        }
      } else {
        const live = snippetsRef.current;
        if (live && live.context === context && identity.revisions?.[field] === revision) {
          const row = live.identities.indexOf(identity as LibraryIdentity<Snippet>);
          if (row >= 0) setSnippetDraft({ ...live, entries: live.entries.map((entry, i) => i === row ? { ...entry, [field]: value } : entry) });
        }
      }
      identity.persisted = { ...identity.persisted, [field]: value };
      if (identity.revisions?.[field] === revision) {
        if (identity.pending) delete identity.pending[field];
        delete identity.inFlight?.[field];
      }
      const savedEntries = library === "dictionary" ? next.dictionaryEntries : next.snippets;
      const savedEntry = savedEntries.find(entry => settingsValuesEqual(entry, identity.persisted));
      if (savedEntry) libraryIdentities.current.set(savedEntry, identity);
      return next;
    }); } finally {
      if (identity.revisions?.[field] === revision) delete identity.inFlight?.[field];
    }
  };

  return {
    state, page, error, busy, accountPending, navigating: routeLoading, routeLoading,
    saving, discardingDrafts, validatingProvider, selectingProvider, confirming, saved,
    dirty: dirtyRef.current, pageDirty,
    dictionary, setDictionary, snippets, setSnippets, setLibraryPreference,
    prompt, setPrompt, retention, setRetention, apiKey, setApiKey, endpoint, setEndpoint,
    recording, setRecording, routeOverride, setRouteOverride,
    closing, setClosing, discarding, setDiscarding, capture, setCapture,
    confirmAction, setConfirmAction, setError, run, runHistoryCorrection, save, navigate,
    cancelDiscard, discardAndClose, saveAndClose, confirmMutation,
    captureHotkey, captureMouseHotkey, selectProvider, validateProvider,
    selectRouteProvider, setTextRouteEnabled, useLocalModel,
  };
}

export type SettingsController = ReturnType<typeof useSettings>;
export type SettingsPageProps = { controller: SettingsController & { state: Settings } };
