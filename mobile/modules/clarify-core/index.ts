import { requireNativeModule } from 'expo';
import type { RecordingAction } from '../../src/press-to-talk';
import type { ContractOutputLanguage, ContractOutputStyle } from '../../../shared/processing-contract';

export interface Snapshot {
  sessionActive: boolean;
  heartbeat: number;
  phase: 'idle' | 'recording' | 'locked' | 'transcribing' | 'rewriting' | 'ready' | 'error';
  operationID?: string;
  text?: string;
  message?: string;
  errorCode?: string;
  errorRecovery?: string;
  configured: boolean;
  computerMode?: boolean;
  processingContext?: string;
  libraryRevision?: number;
  textOperation?: boolean;
}

export interface VocabularyEntry {
  term: string;
  pronunciation: string;
  aliases: string[];
  enabled: boolean;
}
export interface Snippet { trigger: string; replacement: string; enabled: boolean; case_sensitive: boolean }
export interface HistoryEntry {
  id: string;
  createdAt: number;
  transcript: string;
  text: string;
  rewritten: boolean;
  sourceDevice: 'mobile' | 'desktop';
  localOnly: boolean;
  context: string;
}
export interface HistoryPage { entries: HistoryEntry[]; nextCursor?: string; context: string }
export interface MicrophoneActivation { active: boolean; message?: string }
export interface ComputerActionReadiness { dictate: boolean; rewrite: boolean; translate: boolean }
export type OutputLanguage = ContractOutputLanguage;
export type OutputStyle = 'default' | ContractOutputStyle;
export interface OutputPreferences { language: OutputLanguage; style: OutputStyle }
export interface DictationPolicy { mode: 'legacy' | 'natural' | 'preserve' | 'light' | 'clarity' | 'action'; actionID: string; actionRevision: string; language: OutputLanguage }
export interface ProcessingCapabilities {
  schema_version: 1; output_languages: OutputLanguage[]; writing_styles: ContractOutputStyle[];
  cleanup_levels: string[]; dictation_actions: boolean; explicit_dictation_policy: boolean;
  text_input_bytes: number; text_output_bytes: number;
}
export interface ComputerTextAction {
  id: string; revision: string; name: string;
  kind: 'rewrite' | 'translation' | 'custom'; enabled: boolean; ready: boolean;
}
export interface TextActionCatalog {
  textActionsSupported: boolean;
  textActions: ComputerTextAction[];
  textActionsStatus: 'unavailable' | 'loading' | 'ready' | 'unsupported';
  outputPreferencesSupported: boolean;
  processingContract?: ProcessingCapabilities;
}
export interface ComputerSnapshot extends TextActionCatalog { paired: boolean; computerID: string; computerName: string; status: string; ready: boolean; busy: boolean; actionReadiness?: ComputerActionReadiness; remoteStatus?: string; remoteAvailable?: boolean }
export interface AccountSnapshot extends TextActionCatalog {
  mode?: 'hosted' | 'computer'; processingConfigured?: boolean; computer?: ComputerSnapshot;
  endpoint: string; endpointRecovery?: string; managed?: boolean; signedIn: boolean; email: string; pending: string;
  hosted: boolean; syncEnabled: boolean; busy: boolean; error: string;
  dictionaryConflict?: boolean;
  historyAccount?: boolean;
  historyContext: string;
  // Native and cached servers can return an empty or legacy snapshot.
  usage: unknown;
}

export interface AccountTextActionDefinition {
  id: string; name: string; prompt: string; kind: 'rewrite' | 'translation' | 'custom'; enabled: boolean;
}
export interface AccountTextActionLibrary {
  revision: string; lease: string; context: string;
  actions: (AccountTextActionDefinition & { revision: string })[];
}

export default requireNativeModule<{
  readonly uiLanguage: string;
  readonly keyboardDiagnosticAvailable: boolean;
  newOperationID(): string;
  openKeyboardDiagnostic(): Promise<void>;
  onboardingRequired(): Promise<boolean>;
  markOnboardingPresented(): Promise<void>;
  completeOnboarding(): Promise<void>;
  getSnapshot(): Promise<Snapshot>;
  getAccountTextActions(context: string): Promise<AccountTextActionLibrary>;
  saveAccountTextActions(actions: AccountTextActionDefinition[], revision: string, lease: string, context: string): Promise<AccountTextActionLibrary>;
  getAccount(): Promise<AccountSnapshot>;
  accountCommand(action: string, value: string): Promise<AccountSnapshot>;
  computerCommand(action: 'computer' | 'hosted' | 'scan' | 'refresh' | 'disconnect'): Promise<AccountSnapshot>;
  processText(action: 'rewrite' | 'translate', text: string, language: string, context: string): Promise<string>;
  processTextAction(actionID: string, actionRevision: string, text: string, language: string, context: string): Promise<string>;
  getOutputPreferences(): Promise<OutputPreferences>;
  setOutputPreference(key: 'language' | 'style', value: string): Promise<OutputPreferences>;
  getDictationPolicy(): Promise<DictationPolicy>;
  setDictationPolicy(mode: DictationPolicy['mode'], actionID: string, revision: string, language: OutputLanguage, context: string): Promise<DictationPolicy>;
  activate(): Promise<MicrophoneActivation>;
  deactivate(): Promise<void>;
  returnToSource(token: string): Promise<boolean>;
  command(action: RecordingAction, operationID: string, context: string): Promise<void>;
  copyResult(): Promise<void>;
  copyText(text: string): Promise<void>;
  copyTextOperationResult(operationID: string, context: string): Promise<boolean>;
  getHistory(before: string): Promise<HistoryPage>;
  deleteHistory(id: string, localOnly: boolean, context: string): Promise<void>;
  clearHistory(context: string): Promise<void>;
  getSnippets(): Promise<Snippet[]>;
  saveSnippets(entries: Snippet[], base: Snippet[], context: string): Promise<void>;
  getDictionary(): Promise<VocabularyEntry[]>;
  saveDictionary(entries: VocabularyEntry[], base: VocabularyEntry[]): Promise<void>;
}>('ClarifyCore');
