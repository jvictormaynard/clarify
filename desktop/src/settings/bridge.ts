import { invoke } from "@tauri-apps/api/core";
import type { RecordingControls } from "./recording";

export type Option = { id: string; label: string };
export type DictionaryEntry = {
  term: string;
  pronunciation: string;
  aliases: string[];
  enabled: boolean;
};
export type HistoryEntry = { id: string; timestamp: number; text: string; truncated: boolean; sourceDevice: "desktop" | "mobile" };
type HistoryPageResult = { context: string; revision: string; entries: HistoryEntry[]; cursor: string; hasMore: boolean };
type HistoryTextPart = { context: string; id: string; text: string; nextOffset: number; hasMore: boolean };
export type Snippet = { trigger: string; replacement: string; enabled: boolean; case_sensitive: boolean };
export interface Settings {
  snippets: Snippet[];
  snippetContext: string;
  historyState?: { context: string; revision: string };
  uiLanguage?: string;
  onboardingRequired: boolean;
  accountState?: {
    socialPending?: boolean;
    endpoint: string; managed?: boolean; signedIn: boolean; email: string; pending: string;
    hosted: boolean; syncEnabled: boolean; busy: boolean; error: string;
    dictionaryConflict?: boolean; syncError?: string;
    // Validate at the display boundary: older servers can return a legacy shape.
    usage: unknown;
  };
  dictionaryEntries: DictionaryEntry[];
  dirty: boolean;
  lastError: string;
  language: string;
  languages: string[];
  mode: string;
  modes: string[];
  autostart: boolean;
  applicationVersion?: string;
  automaticUpdates?: boolean;
  updateStatus?: string;
  updateSupported?: boolean;
  updateBusy?: boolean;
  historyEnabled: boolean;
  historyRetentionDays: number | null;
  microphoneDevices: Option[];
  microphoneInventoryBusy: boolean;
  selectedMicrophoneId: string | null;
  microphoneStatus: string;
  microphoneTestBusy: boolean;
  microphoneTestLevel: number;
  microphoneTestStatus: string;
  recordingControls: RecordingControls;
  selectedScope: string;
  routeProviderId: string;
  routeModelId: string;
  routeModelOptions: Option[];
  routeModelStatus: string;
  routePrompt: string;
  routeEnabled: boolean;
  routeCustomEndpoint: string;
  providers: Option[];
  routeProviders: Option[];
  selectedProviderId: string;
  providerDisplayName: string;
  providerHasApiKey: boolean;
  providerBaseUrl: string;
  providerDirty: boolean;
  providerBusy: boolean;
  providerStatus: string;
  providerError: string;
  providerSupportsCustomEndpoint: boolean;
  localProfiles: string[];
  localProfileIndex: number;
  localDevices: string[];
  localDeviceIndex: number;
  localAsrStatus: string;
  localAsrDetail: string;
  localAsrProgress: number;
  localAsrBusy: boolean;
  localAsrCanInstall: boolean;
  localAsrRequirementsList: string[];
  localStreaming: boolean;
  localAsrCloudRefinement: boolean;
  localBenchmarkBusy: boolean;
  localBenchmarkDetail: string;
  hotkeyCaptureAction: string;
  hotkeyActions: {
    id: string;
    label: string;
    display: string;
    definition: { display: string };
  }[];
  hotkeyActivationMode: string;
  hotkeyPushToTalkSupported: boolean;
}

// Argument tuples keep every frontend call checked without changing the pipe protocol.
export type SettingsArguments = {
  completeOnboarding: [mode: "account" | "byok" | "local", key: string];
  accountCommand: [action: string, value: string];
  deleteHistoryEntry: [id: string, context: string];
  clearHistory: [context: string];
  snapshot: [];
  setLanguage: [value: string];
  setSnippets: [entries: Snippet[], context: string, expectedEntries?: Snippet[]];
  setDictionaryEntries: [entries: DictionaryEntry[], context?: string, expectedEntries?: DictionaryEntry[]];
  setMode: [value: string];
  setAutostart: [value: boolean];
  setAutomaticUpdates: [value: boolean];
  checkForUpdates: [];
  setHistoryEnabled: [value: boolean];
  setHistoryRetentionDays: [value: number | null];
  selectMicrophone: [id: string];
  refreshMicrophones: [];
  testMicrophone: [];
  stopMicrophoneTest: [];
  setRecordingControls: [value: RecordingControls];
  setRecordingVadEnabled: [value: boolean];
  selectWorkflow: [scope: string];
  setRouteProviderId: [id: string];
  setRouteModelId: [id: string];
  loadRouteModels: [];
  refreshRouteModels: [];
  setRoutePrompt: [value: string];
  setRouteEnabled: [value: boolean];
  setRouteCustomEndpoint: [value: string];
  selectProvider: [id: string];
  setProviderApiKey: [value: string];
  setProviderBaseUrl: [value: string];
  validateProvider: [];
  selectLocalProfile: [index: number];
  selectLocalDevice: [index: number];
  installLocalAsr: [];
  cancelLocalAsr: [];
  refreshLocalAsr: [];
  setLocalStreaming: [value: boolean];
  setLocalAsrCloudRefinement: [value: boolean];
  setHotkey: [action: string, definition: { modifiers: string[]; key: string }];
  beginHotkeyCapture: [action: string];
  cancelHotkeyCapture: [];
  setHotkeyActivationMode: [value: string];
  resetHotkey: [action: string];
  resetAllHotkeys: [];
  clearProvider: [];
  removeLocalAsr: [];
  useLocalAsr: [];
  cancelLocalMeasurement: [];
  save: [context?: string];
  load: [];
  savePreference: [method: PreferenceMethod, args: unknown[]];
  saveLibraryPreference: [library: "dictionary" | "snippets", identity: DictionaryEntry | Snippet, field: "enabled" | "case_sensitive", value: boolean, context: string];
};
export type SettingsMethod = keyof SettingsArguments;

export const preferenceMethods = [
  "setMode", "setLanguage", "setAutostart", "setHistoryEnabled", "setAutomaticUpdates",
  "selectMicrophone", "setRouteProviderId", "setRouteModelId", "setRouteEnabled",
  "setLocalStreaming", "setLocalAsrCloudRefinement", "setHotkey", "setHotkeyActivationMode",
  "resetHotkey", "resetAllHotkeys", "useLocalAsr", "setRecordingVadEnabled",
] as const;
export type PreferenceMethod = typeof preferenceMethods[number];
export type SettingsCall = <M extends SettingsMethod>(method: M, ...args: SettingsArguments[M]) => Promise<Settings>;

let queue: Promise<unknown> = Promise.resolve();
function enqueue<T>(operation: () => Promise<T>): Promise<T> {
  const next = queue.then(operation);
  queue = next.catch(() => undefined);
  return next;
}
function queuedCall<T>(method: string, args: unknown[]): Promise<T> {
  return enqueue(() => invoke<T>("settings_call", { method, args }));
}
// Reserve the connection for the complete operation. A poll or another action
// cannot change workflow/account scope between staging and persistence.
export function settingsTransaction<T>(operation: (call: SettingsCall) => Promise<T>): Promise<T> {
  return enqueue(() => operation((method, ...args) => invoke<Settings>("settings_call", { method, args })));
}
export const getHistoryPage = (context: string, cursor = "") => queuedCall<HistoryPageResult>("getHistoryPage", [context, cursor]);
export const getHistoryTextPart = (context: string, id: string, offset: number) => queuedCall<HistoryTextPart>("getHistoryTextPart", [context, id, offset, "text"]);
// Only periodic polls advance the Python baseline. Commands still return full state.
export const pollSettings = () => queuedCall<Partial<Settings>>("poll", []);
export function call<M extends SettingsMethod>(
  method: M,
  ...args: SettingsArguments[M]
): Promise<Settings> {
  return queuedCall<Settings>(method, args);
}
