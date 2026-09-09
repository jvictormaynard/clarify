import { invoke } from "@tauri-apps/api/core";

export type Option = { id: string; label: string };
export interface Settings {
  dirty: boolean; lastError: string;
  language: string; languages: string[]; mode: string; modes: string[];
  autostart: boolean; historyEnabled: boolean; historyRetentionDays: number | null;
  microphoneDevices: Option[]; selectedMicrophoneId: string | null;
  microphoneStatus: string; microphoneTestBusy: boolean; microphoneTestLevel: number;
  microphoneTestStatus: string; recordingControls: Record<string, number | boolean | null>;
  selectedScope: string; routeProviderId: string; routeModelId: string;
  routeModelOptions: Option[]; routeModelStatus: string; routePrompt: string;
  routeEnabled: boolean; routeCustomEndpoint: string;
  providers: Option[]; routeProviders: Option[];
  selectedProviderId: string; providerDisplayName: string; providerHasApiKey: boolean;
  providerBaseUrl: string; providerDirty: boolean; providerBusy: boolean;
  providerStatus: string; providerError: string; providerSupportsCustomEndpoint: boolean;
  localProfiles: string[]; localProfileIndex: number; localDevices: string[];
  localDeviceIndex: number; localAsrStatus: string; localAsrDetail: string;
  localAsrProgress: number; localAsrBusy: boolean; localAsrCanInstall: boolean;
  localAsrRequirementsList: string[]; localStreaming: boolean; localAsrCloudRefinement: boolean;
  hotkeyActions: { id: string; label: string; display: string; definition: { display: string } }[];
  hotkeyActivationMode: string; hotkeyPushToTalkSupported: boolean;
}

let queue: Promise<unknown> = Promise.resolve();
export function call(method: string, ...args: unknown[]): Promise<Settings> {
  const next = queue.then(() => invoke<Settings>("settings_call", { method, args }));
  queue = next.catch(() => undefined);
  return next;
}
