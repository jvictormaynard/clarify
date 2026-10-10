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

export default requireNativeModule<{
  getSnapshot(): Promise<Snapshot>;
  setKey(key: string): Promise<void>;
  activate(): Promise<void>;
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
