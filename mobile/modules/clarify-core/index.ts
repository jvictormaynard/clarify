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
}
export interface HistoryPage { entries: HistoryEntry[]; nextCursor?: number }
export interface MicrophoneActivation { active: boolean; message?: string }
export interface AccountSnapshot {
  hasGroqKey?: boolean;
  endpoint: string; managed?: boolean; signedIn: boolean; email: string; pending: string;
  hosted: boolean; syncEnabled: boolean; busy: boolean; error: string;
  dictionaryConflict?: boolean;
  usage: { month?: string; limit_ms?: number; used_ms?: number; reserved_ms?: number; hosted_available?: boolean };
}

export default requireNativeModule<{
  readonly uiLanguage: string;
  onboardingRequired(): Promise<boolean>;
  completeOnboarding(mode: 'account' | 'byok'): Promise<void>;
  getSnapshot(): Promise<Snapshot>;
  getAccount(): Promise<AccountSnapshot>;
  accountCommand(action: string, value: string): Promise<AccountSnapshot>;
  setKey(key: string): Promise<void>;
  activate(): Promise<MicrophoneActivation>;
  deactivate(): Promise<void>;
  returnToSource(token: string): Promise<boolean>;
  command(action: RecordingAction, operationID: string): Promise<void>;
  copyResult(): Promise<void>;
  copyText(text: string): Promise<void>;
  getHistory(before: number): Promise<HistoryPage>;
  deleteHistory(id: string): Promise<void>;
  clearHistory(): Promise<void>;
  getDictionary(): Promise<VocabularyEntry[]>;
  saveDictionary(entries: VocabularyEntry[]): Promise<void>;
}>('ClarifyCore');
