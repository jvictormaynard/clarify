import { requireNativeModule } from 'expo';
import type { RecordingAction } from '../../src/press-to-talk';

export interface Snapshot {
  sessionActive: boolean;
  heartbeat: number;
  phase: 'idle' | 'recording' | 'locked' | 'transcribing' | 'rewriting' | 'ready' | 'error';
  operationID?: string;
  text?: string;
  message?: string;
  configured: boolean;
  computerMode?: boolean;
  processingContext?: string;
  libraryRevision?: number;
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
export interface ComputerSnapshot { paired: boolean; computerID: string; computerName: string; status: string; ready: boolean; busy: boolean; actionReadiness?: ComputerActionReadiness }
export interface AccountSnapshot {
  mode?: 'hosted' | 'computer'; processingConfigured?: boolean; computer?: ComputerSnapshot;
  endpoint: string; managed?: boolean; signedIn: boolean; email: string; pending: string;
  hosted: boolean; syncEnabled: boolean; busy: boolean; error: string;
  dictionaryConflict?: boolean;
  historyAccount?: boolean;
  historyContext: string;
  // Native and cached servers can return an empty or legacy snapshot.
  usage: unknown;
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
  getAccount(): Promise<AccountSnapshot>;
  accountCommand(action: string, value: string): Promise<AccountSnapshot>;
  computerCommand(action: 'computer' | 'hosted' | 'scan' | 'refresh' | 'disconnect'): Promise<AccountSnapshot>;
  processComputerText(action: 'rewrite' | 'translate', text: string, language: string, context: string): Promise<void>;
  activate(): Promise<MicrophoneActivation>;
  deactivate(): Promise<void>;
  returnToSource(token: string): Promise<boolean>;
  command(action: RecordingAction, operationID: string, context: string): Promise<void>;
  copyResult(): Promise<void>;
  copyText(text: string): Promise<void>;
  getHistory(before: string): Promise<HistoryPage>;
  deleteHistory(id: string, localOnly: boolean, context: string): Promise<void>;
  clearHistory(context: string): Promise<void>;
  getSnippets(): Promise<Snippet[]>;
  saveSnippets(entries: Snippet[], base: Snippet[], context: string): Promise<void>;
  getDictionary(): Promise<VocabularyEntry[]>;
  saveDictionary(entries: VocabularyEntry[], base: VocabularyEntry[]): Promise<void>;
}>('ClarifyCore');
