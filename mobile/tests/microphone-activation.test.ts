import assert from 'node:assert/strict';
import { test } from 'node:test';
import { activateMicrophone } from '../src/state/activation.ts';

const inactive = { sessionActive: false, heartbeat: 1, phase: 'error' as const, configured: true };
const busyMessage = 'O microfone está em uso por uma ligação ou outro aplicativo. Encerre a ligação ou a gravação e tente novamente.';

test('a call blocking microphone activation shows the native message and never returns to the source app', async () => {
  let returns = 0;
  await assert.rejects(activateMicrophone({
    activate: async () => ({ active: false, message: busyMessage }),
    getSnapshot: async () => inactive,
    returnToSource: async () => { returns++; return true; },
  }, 'request-token'), { message: busyMessage });
  assert.equal(returns, 0);
});

test('after the call ends a new activation can succeed before returning to the source app', async () => {
  let attempts = 0;
  let returns = 0;
  const core = {
    activate: async () => ++attempts === 1 ? { active: false, message: busyMessage } : { active: true },
    getSnapshot: async () => ({ ...inactive, sessionActive: attempts === 2 }),
    returnToSource: async () => { returns++; return true; },
  };
  await assert.rejects(activateMicrophone(core, 'request-token'));
  const state = await activateMicrophone(core, 'request-token');
  assert.equal(state.sessionActive, true);
  assert.equal(attempts, 2);
  assert.equal(returns, 1);
});

test('an interruption after activation cannot trigger an automatic return', async () => {
  let returns = 0;
  await assert.rejects(activateMicrophone({
    activate: async () => ({ active: true }),
    getSnapshot: async () => inactive,
    returnToSource: async () => { returns++; return true; },
  }, 'request-token'), /Ative o microfone novamente/);
  assert.equal(returns, 0);
});
