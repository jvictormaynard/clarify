import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
const { createAppUIService } = createRequire(import.meta.url)('./app-ui-service.cjs');
const { requirePassedTest } = createRequire(import.meta.url)('../scripts/test-app-ui.cjs');

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
    const response = await fetch(base + '/v1/text-actions', { signal: AbortSignal.timeout(2000) });
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
    assert.equal(f.requests.filter((item: { route: string }) => item.route === '/v1/text-actions').length, 0);
    assert.equal((await (await fetch(base + '/__fixture/wait-catalog')).json()).held, 1);
    await control({ release: true });
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      body += decoder.decode(part.value);
    }
    const catalog = JSON.parse(body);
    assert.equal(catalog.revision, 1);
    assert.equal(catalog.actions.length, 3);
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
    const pending = fetch(base + '/v1/text-actions', { signal: abort.signal }).then(response => response.json()).catch(error => error);
    const state = await (await fetch(base + '/__fixture/wait-catalog')).json();
    assert.equal(state.held, 1);
    abort.abort(); await pending;
    await control({ release: true });
    const final = await (await fetch(base + '/__fixture/state')).json();
    assert.deepEqual(final.processing, []);
    for (const mode of ['empty', 'failed', 'unsupported']) {
      await control({ catalog: mode }); const response = await fetch(base + '/v1/text-actions');
      assert.equal(response.status, mode === 'failed' ? 503 : mode === 'unsupported' ? 404 : 200);
      if (mode === 'empty') assert.deepEqual((await response.json()).actions, []);
    }
    assert.deepEqual(f.unexpected, []);
  } finally { f.release(); await new Promise<void>(done => f.server.close(done)); }
});
