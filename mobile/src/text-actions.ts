import type { AccountSnapshot, Snapshot, ComputerTextAction } from '../modules/clarify-core';
import { errorMessage } from './errors.ts';

export const targetLanguages = [
  { value: 'pt', label: '🇧🇷 Português' }, { value: 'en', label: '🇺🇸 English' },
  { value: 'es', label: '🇪🇸 Español' }, { value: 'de', label: '🇩🇪 Deutsch' },
  { value: 'ru', label: '🇷🇺 Русский' },
] as const;
export type TargetLanguage = typeof targetLanguages[number]['value'];
export interface ActionChoice {
  key: string; name: string; translation: boolean; enabled: boolean; ready: boolean;
  saved?: ComputerTextAction; legacy?: 'rewrite' | 'translate';
}
export function actionChoices(account?: AccountSnapshot): ActionChoice[] {
  if (!account) return [];
  const catalog = account.mode === 'computer' ? account.computer : account;
  if (catalog?.textActionsStatus === 'unsupported') {
    return (['rewrite', 'translate'] as const).map(action => ({
      key: `legacy:${action}`, name: action === 'rewrite' ? 'Reescrever' : 'Traduzir',
      translation: action === 'translate', enabled: true,
      ready: account.mode === 'computer' ? account.computer?.actionReadiness?.[action] === true : account.signedIn,
      legacy: action,
    }));
  }
  if (catalog?.textActionsStatus !== 'ready') return [];
  return catalog.textActions.map(saved => ({ key: `saved:${saved.id}:${saved.revision}`,
    name: saved.name, translation: saved.kind === 'translation', enabled: saved.enabled, ready: saved.ready, saved }));
}
export interface TextOperation { id: string; context: string; selection?: string; language?: TargetLanguage }
export function ownsTextOperation(operation: TextOperation | null, state: Snapshot, context: string): boolean {
  return !!operation && !!context && operation.context === context && state.processingContext === context &&
    state.textOperation === true && state.operationID === operation.id;
}
export function ownedTextResult(operation: TextOperation | null, state: Snapshot, context: string): string | null {
  return ownsTextOperation(operation, state, context) && state.phase === 'ready' && !!state.text?.trim() ? state.text : null;
}
export function composerResult(model: Pick<ComposerState, 'operation' | 'selected' | 'language'>, state: Snapshot, context: string): string | null {
  return model.operation?.selection === model.selected && model.operation?.language === model.language
    ? ownedTextResult(model.operation, state, context) : null;
}
interface TextGateway {
  processText(action: 'rewrite' | 'translate', text: string, language: string, context: string): Promise<string>;
  processTextAction(id: string, revision: string, text: string, language: string, context: string): Promise<string>;
  command(action: 'cancel', id: string, context: string): Promise<void>;
}
interface ComposerState {
  draft: string; selected: string; language: TargetLanguage; context: string;
  starting: boolean; cancelling: boolean; operation: TextOperation | null; error: string;
}
// The mounted Actions screen owns drafts. Native owns execution and its UUID.
export class TextComposerSession {
  private value: ComposerState;
  private generation = 0;
  private listeners = new Set<() => void>();
  private gateway: TextGateway;
  constructor(gateway: TextGateway, language: TargetLanguage) {
    this.gateway = gateway;
    this.value = { draft: '', selected: '', language, context: '', starting: false, cancelling: false, operation: null, error: '' };
  }
  getState = () => this.value;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(values: Partial<ComposerState>) { this.value = { ...this.value, ...values }; this.listeners.forEach(fn => fn()); }
  setDraft(draft: string) { this.update({ draft }); }
  select(selected: string) { this.update({ selected, error: '' }); }
  setLanguage(language: TargetLanguage) { this.update({ language }); }
  setContext(context: string) {
    if (context === this.value.context) return;
    ++this.generation;
    this.update({ context, selected: '', operation: null, starting: false, cancelling: false, error: '' });
  }
  async start(choice: ActionChoice) {
    const { draft, context, language, starting, cancelling } = this.value;
    if (starting || cancelling || !context || !draft.trim() || !choice.enabled || !choice.ready) return;
    const generation = ++this.generation;
    this.update({ starting: true, operation: null, error: '' });
    try {
      const target = choice.translation ? language : 'auto';
      const id = choice.saved
        ? await this.gateway.processTextAction(choice.saved.id, choice.saved.revision, draft, target, context)
        : await this.gateway.processText(choice.legacy!, draft, target, context);
      if (generation !== this.generation || context !== this.value.context) {
        await this.gateway.command('cancel', id, context); return;
      }
      this.update({ operation: { id, context, selection: choice.key, language } });
    } catch (error) {
      if (generation === this.generation) this.update({ error: errorMessage(error) });
    } finally { if (generation === this.generation) this.update({ starting: false }); }
  }
  async cancel() {
    const operation = this.value.operation;
    const generation = ++this.generation;
    this.update({ operation: null, starting: false, cancelling: !!operation, error: '' });
    try { if (operation) await this.gateway.command('cancel', operation.id, operation.context); }
    catch (error) { if (generation === this.generation) this.update({ error: errorMessage(error), operation }); }
    finally { if (generation === this.generation) this.update({ cancelling: false }); }
  }
}
