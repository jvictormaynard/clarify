import { invoke } from "@tauri-apps/api/core";
import type { RecordingControls } from "./recording";

export type Option = { id: string; label: string };
export type DictationCleanupLevel = "preserve" | "light" | "clarity";
export type WritingStyle = "natural" | "informal" | "organized";
export type ApplicationWritingStyle = { executable: string; style: WritingStyle };
export type DictionaryEntry = {
  term: string;
  pronunciation: string;
  aliases: string[];
  enabled: boolean;
};
export type HistoryEntry = { id: string; timestamp: number; text: string; truncated: boolean; hasOriginal: boolean; originalDiffers: boolean; owner: "local" | "account"; sourceDevice: "desktop" | "mobile" };
export type HistoryScope = Readonly<{ context: string; revision: string }>;
export type HistoryTextField = "text" | "transcript";
type HistoryPageResult = { context: string; revision: string; entries: HistoryEntry[]; cursor: string; hasMore: boolean };
type HistoryTextPart = HistoryScope & { id: string; owner: "local" | "account"; text: string; nextOffset: number; hasMore: boolean };
export type Snippet = { trigger: string; replacement: string; enabled: boolean; case_sensitive: boolean };
export type ChatGPTAction = "sign_in" | "add_account" | "select_account" | "sign_out" | "cancel" | "manage_usage" | "dismiss_notice";
export type ChatGPTState = {
  connected: boolean; planEnabled: boolean; email: string; accountId: string;
  accounts: Option[]; generation: number; planNoticeSeen: boolean;
  busy: boolean; error: string;
};
export interface Settings {
  chatgptState?: ChatGPTState;
  snippets: Snippet[];
  snippetContext: string;
  historyState?: { context: string; revision: string };
  uiLanguage?: string;
  onboardingRequired: boolean;
  practiceState?: {
    open: boolean; phase?: string; text?: string; source?: string; status?: string; blocked?: string;
  };
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
  dictationCleanupLevel?: DictationCleanupLevel | "";
  applicationWritingStyles?: ApplicationWritingStyle[];
  applicationStyleTarget?: string;
  applicationStyleRefinementAllowed?: boolean;
  dictationCleanupRefinementAllowed?: boolean;
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
  practiceCommand: [action: "open" | "close" | "start" | "stop" | "cancel"];
  completeOnboarding: [mode: "account" | "byok" | "local", key: string];
  accountCommand: [action: string, value: string];
  chatgptCommand: [action: ChatGPTAction, value: string];
  deleteHistoryEntry: [id: string, context: string];
  clearHistory: [context: string];
  snapshot: [];
  setLanguage: [value: string];
  setSnippets: [entries: Snippet[], context: string, expectedEntries?: Snippet[]];
  setDictionaryEntries: [entries: DictionaryEntry[], context?: string, expectedEntries?: DictionaryEntry[]];
  setMode: [value: string];
  setDictationCleanupLevel: [value: DictationCleanupLevel | ""];
  setApplicationWritingStyle: [executable: string, style: WritingStyle | ""];
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
  "setDictationCleanupLevel",
  "setApplicationWritingStyle",
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
export const getHistoryPage = (context: string, cursor = "", query = "") => queuedCall<HistoryPageResult>("getHistoryPage", [context, cursor, query]);
export const getHistoryTextPart = (context: string, id: string, offset: number, field: HistoryTextField = "text") => queuedCall<HistoryTextPart>("getHistoryTextPart", [context, id, offset, field]);
export type HistoryCorrectionReply = {
  status?: "preview" | "already_exists" | "saved" | "saved_without_undo" | "undone" | "undo_unavailable" | "cancelled";
  token?: string; heard?: string; entry?: DictionaryEntry; receipt?: string; canUndo?: boolean; error?: string;
};
export const historyCorrection = (action: "preview" | "confirm" | "undo" | "status" | "cancel", payload: Record<string, string>, isCurrent: () => boolean = () => true) => enqueue(async () => {
  if (!isCurrent()) return null;
  return invoke<HistoryCorrectionReply>("settings_call", { method: "historyCorrection", args: [action, payload] });
});
export const copyHistoryText = (scope: HistoryScope, id: string, field: HistoryTextField, isCurrent: () => boolean) => enqueue(async () => {
  // Navigation/search cancellation can happen while waiting for the pipe.
  if (!isCurrent()) return null;
  return invoke<HistoryScope & { id: string }>("settings_call", { method: "copyHistoryText", args: [scope.context, id, field, scope.revision] });
});
// Only periodic polls advance the Python baseline. Commands still return full state.
export const pollSettings = () => queuedCall<Partial<Settings>>("poll", []);
export function call<M extends SettingsMethod>(
  method: M,
  ...args: SettingsArguments[M]
): Promise<Settings> {
  return queuedCall<Settings>(method, args);
}
