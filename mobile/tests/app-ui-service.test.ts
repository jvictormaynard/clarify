import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
const { createAppUIService } = createRequire(import.meta.url)('./app-ui-service.cjs');
const { appUIProfiles, requirePassedTest, requirePassedNativeTests, nativeMethods } = createRequire(import.meta.url)('../scripts/test-app-ui.cjs');

const computerHeaders = { Authorization: 'Bearer ' + Buffer.alloc(32, 3).toString('base64url') };

test('fixture pairs a computer, rejects hosted inference, and keeps account identity separate', async () => {
  const f = createAppUIService({ now: () => Date.parse('2026-11-16T00:00:00Z') });
  await new Promise<void>(done => f.server.listen(0, '127.0.0.1', done));
  const base = `http://127.0.0.1:${f.server.address().port}`;
  const post = (route: string, value: object, headers = {}) => fetch(base + route, { method: 'POST', headers, body: JSON.stringify(value) });
  try {
    const account = await (await fetch(base + '/v1/account')).json();
    assert.deepEqual(Object.keys(account).sort(), ['email', 'id']);
    const { invitation } = await (await fetch(base + '/__fixture/invitation')).json();
    const qr = JSON.parse(Buffer.from(invitation.split('data=')[1], 'base64url').toString());
    assert.equal(qr.expires_at, '2026-11-16T00:04:00.000Z');
    assert.deepEqual(qr.routes, [{ url: 'https://192.168.1.33:9443', certificate_sha256: 'a'.repeat(64) }]);
    assert.equal((await fetch(base + '/v1/computer/status')).status, 401);
    assert.equal((await post('/v1/computer/pair', { pairing_token: 'invalid', device_name: 'Fixture phone' })).status, 401);
    const paired = await post('/v1/computer/pair', { pairing_token: qr.pairing_token, device_name: 'Fixture phone' });
    assert.equal(paired.status, 201);
    const credential = await paired.json();
    assert.equal(credential.computer_id, qr.computer_id);
    const status = await (await fetch(base + '/v1/computer/status', { headers: computerHeaders })).json();
    assert.equal(status.computer_id, qr.computer_id);
    assert.equal(status.ready, true);
    assert.equal(status.text_actions[0].ready, true);
    assert.equal(status.text_actions[0].prompt, undefined);
    const request = { operation_id: '019a8888-1111-7111-8111-111111111111', action: 'text_action', action_id: 'translation', action_revision: 1,
      text: 'Synthetic text', language: 'ru', writing_style: 'casual' };
    assert.equal((await post('/v1/computer/text', request)).status, 401);
    const processed = await post('/v1/computer/text', request, computerHeaders);
    assert.equal(processed.status, 200);
    const result = await processed.json();
    assert.equal(result.operation_id, request.operation_id);
    assert.equal(result.action_revision, 1);
    assert.equal(result.text, 'Fixture result: Synthetic text');
    assert.equal(result.output_language_applied, 'ru');
    assert.equal(result.writing_style_applied, 'casual');
    assert.equal(result.successful, true);
    assert.equal((await post('/v1/computer/text', request, computerHeaders)).status, 409);
    await post('/__fixture/control', { revision: 2 });
    const stale = await post('/v1/computer/text', { ...request, operation_id: '019a8888-1111-7111-8111-111111111112' }, computerHeaders);
    assert.equal(stale.status, 409);
    assert.equal((await stale.json()).error, 'text_action_stale');
    for (const route of ['/v1/text', '/v1/text-actions/execute', '/v1/dictations']) {
      assert.equal((await post(route, request)).status, 404);
    }
    assert.equal((await fetch(base + '/v1/text-actions')).status, 404);
    assert.equal((await fetch(base + '/v1/computer/session', { method: 'DELETE', headers: computerHeaders })).status, 204);
  } finally { f.release(); await new Promise<void>(done => f.server.close(done)); }
});

test('app UI profiles keep full coverage by default and reject ambiguous selection', () => {
  for (const [env, expected] of [
    [{}, ['regular', 'compact']],
    [{ CLARIFY_APP_UI_PROFILE: 'all' }, ['regular', 'compact']],
    [{ CLARIFY_APP_UI_PROFILE: 'regular' }, ['regular']],
    [{ CLARIFY_APP_UI_PROFILE: 'compact' }, ['compact']],
    [{ CLARIFY_APP_UI_COMPACT_ONLY: 'true' }, ['compact']],
    [{ CLARIFY_APP_UI_PROFILE: 'compact', CLARIFY_APP_UI_COMPACT_ONLY: 'true' }, ['compact']],
  ]) assert.deepEqual(appUIProfiles(env), expected);
  for (const env of [
    { CLARIFY_APP_UI_PROFILE: '' },
    { CLARIFY_APP_UI_PROFILE: 'unknown' },
    { CLARIFY_APP_UI_PROFILE: 'all', CLARIFY_APP_UI_COMPACT_ONLY: 'true' },
    { CLARIFY_APP_UI_PROFILE: 'regular', CLARIFY_APP_UI_COMPACT_ONLY: 'true' },
  ]) assert.throws(() => appUIProfiles(env));
});

test('native text state gate rejects missing, duplicate, unknown and failing cases', () => {
  const lines = nativeMethods.flatMap((method: string) => [
    `Test Case '-[ClarifyTextInputTests ${method}]' started.`,
    `Test Case '-[ClarifyTextInputTests ${method}]' passed (0.1 seconds).`,
  ]);
  assert.doesNotThrow(() => requirePassedNativeTests(lines));
  for (const invalid of [[], lines.slice(0, -2), [...lines, ...lines.slice(0, 2)],
    lines.map((line: string) => line.replace(nativeMethods[0], 'testUnknown')),
    lines.map((line: string) => line.replace('passed', 'failed'))]) {
    assert.throws(() => requirePassedNativeTests(invalid));
  }
});

test('account fixture checks the complete email sent by the native client', async () => {
  const f = createAppUIService();
  await new Promise<void>(done => f.server.listen(0, '127.0.0.1', done));
  const base = `http://127.0.0.1:${f.server.address().port}`;
  const send = (email: string) => fetch(base + '/_allauth/app/v1/auth/continue', {
    method: 'POST', body: JSON.stringify({ email }),
  });
  try {
    const complete = await send('clarify-e2e@example.test');
    assert.equal(complete.status, 401);
    assert.equal((await complete.json()).meta.session_token, 'isolated-e2e-session');
    const truncated = await send('clarify-e2e@exa');
    assert.equal(truncated.status, 400);
    assert.equal((await truncated.json()).meta, undefined);
  } finally { f.release(); await new Promise<void>(done => f.server.close(done)); }
});

test('native profile accepts only its selected passing test, not a zero-test success', () => {
  const method = 'testCompactKeyboardAndActionLayout';
  const start = `Test Case '-[ClarifyAppFlowTests.AppFlowUITests ${method}]' started.`;
  const pass = `Test Case '-[ClarifyAppFlowTests.AppFlowUITests ${method}]' passed (123.456 seconds).`;
  assert.doesNotThrow(() => requirePassedTest([start, pass], method));
  for (const lines of [[], [start], [start, pass.replace('passed', 'failed')], [start, pass, start, pass]]) {
    assert.throws(() => requirePassedTest(lines, method));
  }
  assert.throws(() => requirePassedTest([start, pass], 'testDifferentFlow'));
});

test('held catalog keeps the connection active and completes JSON only after release', async () => {
  const f = createAppUIService({ heartbeatMs: 10 });
  await new Promise<void>(done => f.server.listen(0, '127.0.0.1', done));
  const base = `http://127.0.0.1:${f.server.address().port}`;
  const control = (body: object) => fetch(base + '/__fixture/control', { method: 'POST', body: JSON.stringify(body) });
  try {
    await control({ catalog: 'slow' });
    const response = await fetch(base + '/v1/computer/status', { headers: computerHeaders, signal: AbortSignal.timeout(2000) });
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let body = '';
    for (let chunk = 0; chunk < 2; chunk++) {
      const part = await reader.read();
      assert.equal(part.done, false);
      const whitespace = decoder.decode(part.value);
      assert.match(whitespace, /^\s+$/);
      body += whitespace;
    }
    assert.equal(f.requests.filter((item: { route: string }) => item.route === '/v1/computer/status').length, 0);
    assert.equal((await (await fetch(base + '/__fixture/wait-catalog')).json()).held, 1);
    await control({ release: true });
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      body += decoder.decode(part.value);
    }
    const catalog = JSON.parse(body);
    assert.equal(catalog.text_actions[0].revision, 1);
    assert.equal(catalog.text_actions.length, 3);
    assert.deepEqual((await (await fetch(base + '/__fixture/state')).json()).processing, []);
  } finally { f.release(); await new Promise<void>(done => f.server.close(done)); }
});

test('slow catalog uses an explicit release barrier and never sends processing on its own', async () => {
  const f = createAppUIService();
  await new Promise<void>(done => f.server.listen(0, '127.0.0.1', done));
  const base = `http://127.0.0.1:${f.server.address().port}`;
  const control = (body: object) => fetch(base + '/__fixture/control', { method: 'POST', body: JSON.stringify(body) });
  try {
    await control({ catalog: 'slow' });
    const abort = new AbortController();
    const pending = fetch(base + '/v1/computer/status', { headers: computerHeaders, signal: abort.signal }).then(response => response.json()).catch(error => error);
    const state = await (await fetch(base + '/__fixture/wait-catalog')).json();
    assert.equal(state.held, 1);
    // An automatic account refresh can overlap the action's catalog read.
    const refresh = await fetch(base + '/v1/computer/status', { headers: computerHeaders, signal: AbortSignal.timeout(2000) });
    const refreshedCatalog = refresh.json();
    assert.equal((await (await fetch(base + '/__fixture/wait-catalog')).json()).held, 2);
    assert.deepEqual((await (await fetch(base + '/__fixture/state')).json()).processing, []);
    abort.abort(); await pending;
    await control({ release: true });
    assert.equal((await refreshedCatalog).text_actions[0].revision, 1);
    const final = await (await fetch(base + '/__fixture/state')).json();
    assert.deepEqual(final.processing, []);
    for (const mode of ['empty', 'failed', 'unsupported']) {
      await control({ catalog: mode }); const response = await fetch(base + '/v1/computer/status', { headers: computerHeaders });
      assert.equal(response.status, mode === 'failed' ? 503 : 200);
      if (mode === 'empty') assert.deepEqual((await response.json()).text_actions, []);
      if (mode === 'unsupported') assert.equal((await response.json()).text_actions, undefined);
    }
    assert.deepEqual(f.unexpected, []);
  } finally { f.release(); await new Promise<void>(done => f.server.close(done)); }
});
