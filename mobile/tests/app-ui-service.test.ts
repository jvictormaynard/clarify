import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
const { createAppUIService } = createRequire(import.meta.url)('./app-ui-service.cjs');

test('slow catalog uses an explicit release barrier and never sends processing on its own', async () => {
  const f = createAppUIService();
  await new Promise<void>(done => f.server.listen(0, '127.0.0.1', done));
  const base = `http://127.0.0.1:${f.server.address().port}`;
  const control = (body: object) => fetch(base + '/__fixture/control', { method: 'POST', body: JSON.stringify(body) });
  try {
    await control({ catalog: 'slow' });
    const abort = new AbortController();
    const pending = fetch(base + '/v1/text-actions', { signal: abort.signal }).catch(error => error);
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
