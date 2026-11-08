import assert from 'node:assert/strict';
import { test } from 'node:test';
import { processingAvailable, computerStatus } from '../src/processing.ts';

test('computer authorization is independent of the hosted session and readiness', () => {
  assert.equal(processingAvailable(undefined), false);
  assert.equal(processingAvailable({ signedIn: true }), true);
  assert.equal(processingAvailable({ mode: 'hosted', signedIn: false }), false);
  assert.equal(processingAvailable({ mode: 'computer', signedIn: true }), false);
  assert.equal(processingAvailable({ mode: 'computer', signedIn: false, computer: { paired: true, ready: false, computerID: 'fixture', computerName: 'PC', status: 'offline', busy: false } }), true);
  assert.equal(processingAvailable({ mode: 'computer', signedIn: true, computer: { paired: false, ready: false, computerID: '', computerName: '', status: 'revoked', busy: false } }), false);
});
test('status displays only known nonsecret state', () => {
  assert.equal(computerStatus('ready'), 'Computador disponível');
  assert.equal(computerStatus('offline'), 'Computador indisponível');
  assert.equal(computerStatus('revoked'), 'A conexão foi revogada. Leia outro QR no computador.');
  assert.equal(computerStatus('provider says secret'), 'Conecte seu computador');
});
