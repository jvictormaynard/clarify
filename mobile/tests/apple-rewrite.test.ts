import assert from 'node:assert/strict';
import test from 'node:test';
import { AppleRewriteSession } from '../src/apple-rewrite.ts';

function fixture() {
  const requests: { id: string; source: string; language: string; style: string; resolve: (text: string) => void; reject: (error: Error) => void }[] = [];
  const cancelled: string[] = [];
  let sequence = 0;
  const session = new AppleRewriteSession({
    newOperationID: () => String(++sequence),
    rewriteWithApple: (id, source, language, style) => new Promise<string>((resolve, reject) => requests.push({ id, source, language, style, resolve, reject })),
    cancelAppleRewrite: async id => { cancelled.push(id); },
  });
  return { session, requests, cancelled };
}

test('the lab freezes source/preferences and rejects late results after editing or cancellation', async () => {
  const { session, requests, cancelled } = fixture();
  const saved = { language: 'en', style: 'organized' } as const;
  session.setPreferences(saved);
  assert.equal(session.getState().preferences.style, 'default');
  assert.equal(saved.style, 'organized', 'the lab must not change saved preferences');
  for (const style of ['very_casual', 'informal'] as const) {
    session.setPreferences({ language: 'en', style });
    assert.equal(session.getState().preferences.style, 'casual');
  }
  session.setSource('Send 5 copies to Ana.');
  session.setPreferences({ language: 'de', style: 'formal' });
  const first = session.run();
  assert.deepEqual([requests[0].source, requests[0].language, requests[0].style], ['Send 5 copies to Ana.', 'de', 'formal']);
  await session.run();
  assert.equal(requests.length, 1, 'duplicate taps must not start another operation');
  session.setSource('Keep the backup.');
  await session.cancel();
  const second = session.run();
  requests[0].resolve('Old result'); await first;
  assert.equal(session.getState().busy, true);
  assert.equal(session.getState().result, '');
  requests[1].resolve('Keep the backup.'); await second;
  assert.equal(session.getState().source, 'Keep the backup.');
  assert.equal(session.getState().result, 'Keep the backup.');
  session.setPreferences({ language: 'en', style: 'casual' });
  assert.equal(session.getState().result, '', 'changing a preference invalidates the previous result');
  const third = session.run();
  await session.cancel();
  requests[2].reject(new Error('Late failure')); await third;
  assert.equal(session.getState().error, '');
  assert.deepEqual(cancelled, ['1', '3']);
});

test('native cancellation keeps admission closed until the previous task has stopped', async () => {
  let releaseCancellation!: () => void;
  let calls = 0;
  let finishRewrite!: (text: string) => void;
  const session = new AppleRewriteSession({
    newOperationID: () => String(++calls),
    rewriteWithApple: () => new Promise<string>(resolve => { finishRewrite = resolve; }),
    cancelAppleRewrite: () => new Promise<void>(resolve => { releaseCancellation = resolve; }),
  });
  session.setSource('First source.');
  const run = session.run();
  session.setSource('Changed source.');
  const cancellation = session.cancel();
  assert.equal(session.getState().busy, true);
  await session.run();
  assert.equal(calls, 1, 'cancelling must not admit another native task');
  finishRewrite('Late result'); await run;
  assert.equal(session.getState().busy, true, 'old completion must not clear cancellation');
  releaseCancellation(); await cancellation;
  assert.equal(session.getState().busy, false);
  assert.equal(session.getState().result, '');
  assert.equal(session.getState().source, 'Changed source.');
});

test('failed rewriting keeps the source and permits another explicit attempt', async () => {
  const { session, requests } = fixture();
  session.setSource('Preserve this original.');
  const run = session.run();
  requests[0].reject(new Error('Model unavailable')); await run;
  assert.equal(session.getState().source, 'Preserve this original.');
  assert.equal(session.getState().result, '');
  assert.equal(session.getState().error, 'Model unavailable');
  assert.equal(session.getState().busy, false);
  const retry = session.run(); requests[1].resolve('Preserve this original.'); await retry;
  assert.equal(session.getState().error, '');
  assert.equal(session.getState().result, 'Preserve this original.');
});
