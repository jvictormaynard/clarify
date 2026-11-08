import type { AppleRewriteReport, OutputPreferences, OutputStyle } from '../modules/clarify-core';
import { errorMessage } from './errors.ts';

export const appleRewriteStyles = ['default', 'formal', 'casual'] as const;
const labStyles: Record<OutputStyle, typeof appleRewriteStyles[number]> = {
  default: 'default', formal: 'formal', casual: 'casual',
  very_casual: 'casual', natural: 'default', informal: 'casual', organized: 'default',
};

interface Gateway {
  newOperationID(): string;
  rewriteWithApple(id: string, source: string, language: string, style: string): Promise<string>;
  rewriteWithAppleReport?(id: string, source: string, language: string, style: string, deterministic: boolean): Promise<AppleRewriteReport>;
  cancelAppleRewrite(id: string): Promise<void>;
}
interface State {
  source: string;
  preferences: OutputPreferences;
  busy: boolean;
  result: string;
  error: string;
  elapsedMS: number | null;
  deterministic: boolean;
  report: AppleRewriteReport | null;
}

// This lab has no shared preferences, history, clipboard or dictation effects.
export class AppleRewriteSession {
  private operation: string | null = null;
  private generation = 0;
  private cancellation: Promise<void> | null = null;
  private listeners = new Set<() => void>();
  private state: State = { source: '', preferences: { language: 'auto', style: 'default' }, busy: false, result: '', error: '', elapsedMS: null, deterministic: true, report: null };
  private readonly gateway: Gateway;
  constructor(gateway: Gateway) { this.gateway = gateway; }
  getState = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(next: Partial<State>) { this.state = { ...this.state, ...next }; this.listeners.forEach(listener => listener()); }
  async cancel() {
    const id = this.operation;
    this.operation = null;
    ++this.generation;
    this.update({ busy: !!id || this.cancellation !== null, result: '', error: '', elapsedMS: null, report: null });
    if (id) {
      const pending = this.gateway.cancelAppleRewrite(id).catch(() => {});
      this.cancellation = pending;
      await pending;
      if (this.cancellation === pending) { this.cancellation = null; this.update({ busy: false }); }
    } else if (this.cancellation) await this.cancellation;
  }
  setSource(source: string) {
    void this.cancel();
    this.update({ source });
  }
  setPreferences(preferences: OutputPreferences) {
    void this.cancel();
    this.update({ preferences: { ...preferences, style: labStyles[preferences.style] } });
  }
  setDeterministic(deterministic: boolean) {
    void this.cancel();
    this.update({ deterministic });
  }
  async run() {
    if (this.state.busy || !this.state.source.trim()) return;
    const generation = ++this.generation;
    const id = this.gateway.newOperationID();
    this.operation = id;
    const { source, preferences, deterministic } = this.state;
    const started = Date.now();
    this.update({ busy: true, result: '', error: '', elapsedMS: null, report: null });
    try {
      if (this.gateway.rewriteWithAppleReport) {
        const report = await this.gateway.rewriteWithAppleReport(id, source, preferences.language, preferences.style, deterministic);
        if (generation === this.generation && this.operation === id) this.update({ report, result: report.result, error: report.error, elapsedMS: report.elapsedMS });
        return;
      }
      const result = await this.gateway.rewriteWithApple(id, source, preferences.language, preferences.style);
      if (generation === this.generation && this.operation === id) this.update({ result, elapsedMS: Date.now() - started });
    } catch (error) {
      if (generation === this.generation && this.operation === id) this.update({ error: errorMessage(error) });
    } finally {
      if (generation === this.generation && this.operation === id) { this.operation = null; this.update({ busy: false }); }
    }
  }
}
