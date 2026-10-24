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
  libraryRevision?: number;
}

export interface VocabularyEntry {
  term: string;
  pronunciation: string;
  aliases: string[];
  enabled: boolean;
}
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
export interface AccountSnapshot {
  endpoint: string; managed?: boolean; signedIn: boolean; email: string; pending: string;
  hosted: boolean; syncEnabled: boolean; busy: boolean; error: string;
  dictionaryConflict?: boolean;
  historyAccount?: boolean;
  historyContext: string;
  usage: { month?: string; limit_ms?: number; used_ms?: number; reserved_ms?: number; hosted_available?: boolean };
}

export default requireNativeModule<{
  readonly uiLanguage: string;
  readonly keyboardDiagnosticAvailable: boolean;
  openKeyboardDiagnostic(): Promise<void>;
  onboardingRequired(): Promise<boolean>;
  completeOnboarding(): Promise<void>;
  getSnapshot(): Promise<Snapshot>;
  getAccount(): Promise<AccountSnapshot>;
  accountCommand(action: string, value: string): Promise<AccountSnapshot>;
  activate(): Promise<MicrophoneActivation>;
  deactivate(): Promise<void>;
  returnToSource(token: string): Promise<boolean>;
  command(action: RecordingAction, operationID: string): Promise<void>;
  copyResult(): Promise<void>;
  copyText(text: string): Promise<void>;
  getHistory(before: string): Promise<HistoryPage>;
  deleteHistory(id: string, localOnly: boolean, context: string): Promise<void>;
  clearHistory(context: string): Promise<void>;
  getDictionary(): Promise<VocabularyEntry[]>;
  saveDictionary(entries: VocabularyEntry[], base: VocabularyEntry[]): Promise<void>;
}>('ClarifyCore');
