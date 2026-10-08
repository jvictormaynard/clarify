import { invoke } from "@tauri-apps/api/core";
import type { RecordingControls } from "./recording";

export type Option = { id: string; label: string };
export type DictionaryEntry = {
  term: string;
  pronunciation: string;
  aliases: string[];
  enabled: boolean;
};
export interface Settings {
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
  snapshot: [];
  setLanguage: [value: string];
  setDictionaryEntries: [entries: DictionaryEntry[]];
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
  setHotkeyActivationMode: [value: string];
  resetHotkey: [action: string];
  resetAllHotkeys: [];
  clearProvider: [];
  removeLocalAsr: [];
  useLocalAsr: [];
  cancelLocalMeasurement: [];
  save: [];
  load: [];
};
export type SettingsMethod = keyof SettingsArguments;

let queue: Promise<unknown> = Promise.resolve();
export function call<M extends SettingsMethod>(
  method: M,
  ...args: SettingsArguments[M]
): Promise<Settings> {
  const next = queue.then(() =>
    invoke<Settings>("settings_call", { method, args }),
  );
  queue = next.catch(() => undefined);
  return next;
}
