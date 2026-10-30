import assert from 'node:assert/strict';
import { test } from 'node:test';
import { actionChoices, composerResult, ownedTextResult, ownsTextOperation, targetLanguages, TextComposerSession } from '../src/text-actions.ts';
import { outputStyleLabel, visibleOutputStyle } from '../src/output-preferences.ts';
import type { AccountSnapshot, Snapshot } from '../modules/clarify-core';

const account = (values: Partial<AccountSnapshot> = {}): AccountSnapshot => ({
  signedIn: true, mode: 'hosted', endpoint: 'https://example.test', email: 'a@example.test', historyContext: 'scope',
  textActionsStatus: 'ready', textActionsSupported: true, textActions: [], outputPreferencesSupported: true,
  hosted: true, syncEnabled: true, busy: false, error: '', pending: '', usage: null, ...values,
});
const descriptor = { id: 'rewrite', revision: '9223372036854775807', name: 'My saved action', kind: 'rewrite', enabled: true, ready: true } as const;
const choice = actionChoices(account({ textActions: [descriptor] }))[0];
const op = { id: 'owned-uuid', context: 'scope' };
const ready: Snapshot = { sessionActive: false, heartbeat: 0, configured: true, phase: 'ready',
  operationID: op.id, processingContext: op.context, textOperation: true, text: 'Owned result' };

test('the composer does not offer a recording, another action, stale scope or nonterminal text as its result', () => {
  assert.equal(ownedTextResult(op, ready, 'scope'), 'Owned result');
  for (const state of [{ ...ready, textOperation: false }, { ...ready, operationID: 'other' },
    { ...ready, processingContext: 'old' }, { ...ready, phase: 'rewriting' }, { ...ready, phase: 'error' }]) {
    assert.equal(ownedTextResult(op, state as Snapshot, 'scope'), null);
  }
  assert.equal(ownedTextResult(op, ready, 'other'), null);
  assert.equal(ownedTextResult(null, ready, 'scope'), null);
  assert.equal(ownsTextOperation(op, { ...ready, phase: 'rewriting' }, 'scope'), true);
});

test('only unsupported enables legacy actions; empty, loading, failed and stale catalogs do not', () => {
  for (const status of ['ready', 'unavailable', 'loading', 'failed', 'stale']) {
    assert.deepEqual(actionChoices(account({ textActionsStatus: status as AccountSnapshot['textActionsStatus'] })), []);
  }
  assert.deepEqual(actionChoices(account({ textActionsStatus: 'unsupported' })).map(item => item.legacy), ['rewrite', 'translate']);
  assert.deepEqual(actionChoices(account({ textActionsStatus: 'unavailable', textActions: [descriptor] })), []);
});

test('saved revisions remain decimal strings and text readiness is independent of dictation', () => {
  const computer = { paired: true, ready: false, status: 'not_ready', computerID: 'pc', computerName: 'PC', busy: false,
    textActionsSupported: true, textActionsStatus: 'ready', textActions: [descriptor], outputPreferencesSupported: true,
    actionReadiness: { dictate: false, rewrite: true, translate: false } } as const;
  const saved = actionChoices(account({ mode: 'computer', computer: { ...computer, textActions: [descriptor] } }));
  assert.equal(saved[0].ready, true);
  assert.equal(saved[0].saved?.revision, '9223372036854775807');
  const legacy = actionChoices(account({ mode: 'computer', computer: { ...computer, textActionsStatus: 'unsupported', textActions: [] } }));
  assert.equal(legacy[0].ready, true); assert.equal(legacy[1].ready, false);
  assert.equal(actionChoices(account({ textActions: [{ ...descriptor, enabled: false }] }))[0].enabled, false);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function fixture(start: () => Promise<string> = async () => op.id) {
  const calls: unknown[][] = [];
  const model = new TextComposerSession({
    processText: async (...args) => { calls.push(['legacy', ...args]); return start(); },
    processTextAction: async (...args) => { calls.push(['saved', ...args]); return start(); },
    command: async (...args) => { calls.push(args); },
  }, 'de');
  model.setContext('scope'); model.setDraft('Retain my draft'); model.select(choice.key);
  return { model, calls };
}

test('accepted start freezes draft, revision, explicit translation target and context', async () => {
  const pending = deferred<string>(); const { model, calls } = fixture(() => pending.promise);
  const request = model.start({ ...choice, translation: true });
  model.setDraft('Later edit'); model.setLanguage('ru');
  assert.equal(model.getState().operation, null);
  assert.deepEqual(calls, [['saved', 'rewrite', '9223372036854775807', 'Retain my draft', 'de', 'scope']]);
  pending.resolve(op.id); await request;
  assert.deepEqual(model.getState().operation, { ...op, selection: choice.key, language: 'de' });
  assert.equal(model.getState().draft, 'Later edit');
});

test('preparation failure preserves the draft and never adopts global result text', async () => {
  const { model } = fixture(async () => { throw new Error('Catalog unavailable'); });
  await model.start(choice);
  assert.equal(model.getState().draft, 'Retain my draft');
  assert.equal(model.getState().operation, null);
  assert.equal(model.getState().error, 'Catalog unavailable');
});

test('disabled and not-ready actions cannot submit or discard drafts', async () => {
  const { model, calls } = fixture();
  await model.start({ ...choice, enabled: false }); await model.start({ ...choice, ready: false });
  assert.deepEqual(calls, []); assert.equal(model.getState().draft, 'Retain my draft');
});

test('cancel before acceptance retires the late UUID, with no new processing request', async () => {
  const pending = deferred<string>(); const { model, calls } = fixture(() => pending.promise);
  const request = model.start(choice); await model.cancel(); pending.resolve(op.id); await request;
  assert.equal(model.getState().operation, null);
  assert.deepEqual(calls.at(-1), ['cancel', op.id, 'scope']);
  assert.equal(calls.filter(item => item[0] === 'saved').length, 1);
  assert.equal(model.getState().draft, 'Retain my draft');
});

test('context loss during acceptance cancels the captured operation and retains draft', async () => {
  const pending = deferred<string>(); const { model, calls } = fixture(() => pending.promise);
  const request = model.start(choice); model.setContext('new-scope'); pending.resolve(op.id); await request;
  assert.equal(model.getState().operation, null); assert.equal(model.getState().selected, '');
  assert.deepEqual(calls.at(-1), ['cancel', op.id, 'scope']);
  assert.equal(model.getState().draft, 'Retain my draft');
});

test('cancelled accepted result cannot be published and refresh does not discard drafts', async () => {
  const { model, calls } = fixture(); await model.start(choice); await model.cancel();
  assert.equal(ownedTextResult(model.getState().operation, ready, 'scope'), null);
  model.setContext('scope'); assert.equal(model.getState().draft, 'Retain my draft');
  assert.deepEqual(calls.at(-1), ['cancel', op.id, 'scope']);
});

test('another action or translation target cannot inherit an accepted result', async () => {
  const { model } = fixture(); await model.start(choice);
  assert.equal(composerResult(model.getState(), ready, 'scope'), 'Owned result');
  model.select('another-action'); assert.equal(composerResult(model.getState(), ready, 'scope'), null);
  model.select(choice.key); model.setLanguage('ru');
  assert.equal(composerResult(model.getState(), ready, 'scope'), null);
});

test('translation has all five flag and full-name targets; old style remains readable', () => {
  assert.deepEqual(targetLanguages.map(item => item.value), ['pt', 'en', 'es', 'de', 'ru']);
  assert.ok(targetLanguages.every(item => item.label.length > 5));
  assert.equal(outputStyleLabel('default'), 'Padrão'); assert.equal(visibleOutputStyle('default'), 'default');
  assert.equal(outputStyleLabel('casual'), 'Casual'); assert.equal(visibleOutputStyle('casual'), 'casual');
  assert.equal(outputStyleLabel('very_casual'), 'Muito casual');
  for (const style of ['natural', 'informal', 'organized'] as const) {
    assert.equal(visibleOutputStyle(style), style); assert.ok(outputStyleLabel(style));
  }
});
