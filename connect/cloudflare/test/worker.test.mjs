import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createWorker } from '../worker.mjs';
import {
  LocalD1, CONTROL, API, OWNER, TUNNEL, body, key, environment,
  request, grantRequest, claimRequest, cloudflareFake, json,
} from './support.mjs';

globalThis.fetch = () => { throw new Error('Real network is forbidden in these tests'); };

function fixture(t, extra = {}) {
  const db = new LocalD1();
  t.after(() => db.close());
  const upstream = cloudflareFake();
  let now = 1800000000;
  const worker = createWorker({ fetch: upstream.fetch, now: () => now, timeoutMs: 30 });
  const env = environment(db, extra);
  const send = req => worker.fetch(req, env);
  const issue = async (value = body()) => {
    const response = await send(grantRequest(value));
    assert.equal(response.status, 200);
    return response.json();
  };
  return { db, upstream, worker, env, send, issue, advance: seconds => { now += seconds; } };
}

test('disabled configuration has no D1 or external effects', async () => {
  const response = await createWorker().fetch(grantRequest(body()), { CONNECT_ENABLED: 'false' });
  assert.equal(response.status, 503);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

test('verified session uses one fixed GET; grant is hashed, scoped, and expires in 240 seconds', async t => {
  const f = fixture(t);
  const grant = await f.issue();
  assert.deepEqual(Object.keys(grant).sort(), ['schema_version', 'grant', 'expires_at', 'control_url', 'hostname'].sort());
  assert.equal(grant.control_url, CONTROL);
  assert.equal(grant.expires_at, 1800000240);
  // Independent vector: SHA256(raw key 01..20), RFC4648 Base32, lowercase, no padding.
  assert.equal(grant.hostname, 'c-' + base32(createHash('sha256').update(Buffer.from(body().hpke_public_key, 'base64url')).digest()) + '.victormaynard.com');
  assert.equal(grant.hostname.split('.')[0].length, 54);
  const calls = f.upstream.calls;
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, API + '/v1/account');
  assert.equal(calls[0].method, 'GET');
  assert.equal(calls[0].redirect, 'manual');
  assert.equal(calls[0].headers['X-Session-Token'], 'private-session');
  const row = f.db.rows()[0];
  assert.equal(row.grant_hash, createHash('sha256').update(Buffer.from(grant.grant, 'base64url')).digest('hex'));
  assert(!JSON.stringify(row).includes(grant.grant));
  assert(!JSON.stringify(row).includes('private-session'));
  assert(!JSON.stringify(row).includes('do-not-store'));
});

function base32(bytes) {
  let bits = [...bytes].map(byte => byte.toString(2).padStart(8, '0')).join('');
  bits = bits.padEnd(Math.ceil(bits.length / 5) * 5, '0');
  return bits.match(/.{5}/g).map(group => 'abcdefghijklmnopqrstuvwxyz234567'[parseInt(group, 2)]).join('');
}

test('auth failures, redirects, malformed JSON, size overflow, and timeout never admit a computer', async t => {
  const cases = [
    () => new Response('', { status: 401 }),
    () => new Response('', { status: 403 }),
    () => new Response('', { status: 302, headers: { location: 'https://evil.invalid' } }),
    () => new Response('{', { headers: { 'content-type': 'application/json' } }),
    () => Response.json({ id: OWNER }, { headers: { 'content-length': '9999999' } }),
    () => Response.json({ id: OWNER, padding: 'x'.repeat(17000) }),
    () => Response.json({ id: OWNER }, { headers: { 'content-type': 'text/html' } }),
    () => Response.json({ id: 'not-a-user-id' }),
    () => new Promise(() => {}),
    () => new Response(new ReadableStream({ start() {} }), { headers: { 'content-type': 'application/json' } }),
  ];
  for (const auth of cases) {
    const f = fixture(t);
    f.upstream.auth = auth;
    const result = await f.send(grantRequest(body()));
    assert([401, 502, 504].includes(result.status));
    assert.equal(f.db.rows().length, 0);
    assert.equal(f.upstream.calls.length, 1);
  }
});

test('missing/oversized session is rejected without account fetch', async t => {
  const f = fixture(t);
  for (const token of ['', 'x'.repeat(1025), 'with spaces']) {
    const result = await f.send(request('/v1/connect/grants', body(), { 'X-Session-Token': token }));
    assert.equal(result.status, 401);
  }
  assert.equal(f.upstream.calls.length, 0);
});

test('strict request schemas prevent caller-controlled origins, account scope and ports', async t => {
  const f = fixture(t);
  const changes = [
    { auth_origin: 'https://evil.invalid' }, { origin: 'http://evil.invalid' },
    { control_url: 'https://evil.invalid' }, { account_id: 'bad' }, { zone_id: 'bad' },
    { hostname: 'evil.invalid' }, { computer_id: '../account' },
    { certificate_sha256: 'c'.repeat(63) }, { hpke_public_key: key(1) + '=' },
    { hpke_public_key: 'A'.repeat(43) }, { origin_port: 0 }, { origin_port: 65536 },
    { origin_port: 1.5 }, { origin_port: '123' },
  ];
  for (const change of changes) assert.equal((await f.send(grantRequest({ ...body(), ...change }))).status, 400);
  assert.equal(f.db.rows().length, 0);
  assert.equal(f.upstream.calls.length, 0);
  assert.equal((await f.send(request('/v1/connect/claim', { grant: key(2), control_url: 'https://evil.invalid' }))).status, 400);
});

test('control origin, exact routes, content type, body limits, and configuration fail closed', async t => {
  const f = fixture(t);
  for (const url of ['https://evil.invalid/v1/connect/grants', CONTROL + ':444/v1/connect/grants', CONTROL + '/v1/connect/grants?auth_origin=evil']) {
    assert.equal((await f.send(new Request(url, { method: 'POST', body: '{}' }))).status, 400);
  }
  for (const path of ['/v1/computer/sealed', '/v1/account', '/v1/connect/grants/', '/proxy/https://evil.invalid']) {
    assert.equal((await f.send(request(path, {}))).status, 404);
  }
  assert.equal((await f.send(new Request(CONTROL + '/v1/connect/grants'))).status, 405);
  assert.equal((await f.send(request('/v1/connect/grants', body(), { 'content-type': 'text/plain' }))).status, 415);
  assert.equal((await f.send(request('/v1/connect/grants', { x: 'x'.repeat(4097) }))).status, 413);
  assert.equal((await f.send(new Request(CONTROL + '/v1/connect/claim', { method: 'POST', body: '{', headers: { 'content-type': 'application/json' } }))).status, 400);
  for (const config of [
    { CLARIFY_API_URL: 'http://example.invalid' }, { CLARIFY_API_URL: API + '/v1' },
    { CLARIFY_API_URL: API + '?x=1' }, { CLARIFY_API_URL: 'https://user:pass@example.invalid' },
    { CONTROL_URL: 'https://evil.invalid' }, { TUNNEL_DOMAIN: 'deeper.victormaynard.com' },
    { GLOBAL_COMPUTER_LIMIT: '901' }, { GLOBAL_COMPUTER_LIMIT: '0' }, { CF_ZONE_ID: 'placeholder' },
  ]) assert.equal((await f.worker.fetch(grantRequest(body()), { ...f.env, ...config })).status, 503);
  assert.equal(f.upstream.calls.length, 0);
});

test('expiry, replacement and parallel replay do not duplicate a claim', async t => {
  const f = fixture(t);
  const expired = await f.issue();
  f.advance(240);
  assert.equal((await f.send(claimRequest(expired.grant))).status, 409);
  const replaced = await f.issue();
  const current = await f.issue();
  assert.equal((await f.send(claimRequest(replaced.grant))).status, 409);
  const results = await Promise.all([f.send(claimRequest(current.grant)), f.send(claimRequest(current.grant))]);
  assert.deepEqual(results.map(response => response.status).sort(), [200, 409]);
  assert.equal((await f.send(claimRequest(current.grant))).status, 409);
  assert.equal(f.upstream.calls.filter(call => call.method === 'POST' && call.url.endsWith('/cfd_tunnel')).length, 1);
});

test('atomic admission enforces per-owner and configured global quotas under parallel requests', async t => {
  const f = fixture(t);
  const results = await Promise.all(Array.from({ length: 12 }, (_, i) => f.send(grantRequest(body(i + 1)))));
  assert.equal(results.filter(response => response.status === 200).length, 3);
  assert.equal(f.db.rows().length, 3);
  const g = fixture(t, { GLOBAL_COMPUTER_LIMIT: '2' });
  const global = await Promise.all(Array.from({ length: 8 }, (_, i) => g.send(grantRequest(body(i + 1)))));
  assert.equal(global.filter(response => response.status === 200).length, 2);
  assert.equal(g.db.rows().length, 2);
});

test('cross-owner, changed key, and shared hostname cannot take over a computer', async t => {
  const f = fixture(t);
  await f.issue();
  f.upstream.owner = '33333333-3333-4333-8333-333333333333';
  assert.equal((await f.send(grantRequest(body()))).status, 409);
  f.upstream.owner = OWNER;
  assert.equal((await f.send(grantRequest({ ...body(), hpke_public_key: key(99) }))).status, 409);
  assert.equal((await f.send(grantRequest({ ...body(2), hpke_public_key: body().hpke_public_key }))).status, 409);
});

test('claim configures exact hostname, loopback HTTP, catch-all404 and proxied CNAME; port changes reuse tunnel', async t => {
  const f = fixture(t);
  const grant = await f.issue();
  const response = await f.send(claimRequest(grant.grant));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), { schema_version: 1, hostname: grant.hostname, token: 'connector-test-token', origin_port: 49321 });
  assert.deepEqual(f.upstream.config, { ingress: [
    { hostname: grant.hostname, service: 'http://127.0.0.1:49321' }, { service: 'http_status:404' },
  ] });
  assert.deepEqual({ ...f.upstream.record, id: undefined }, {
    id: undefined, type: 'CNAME', name: grant.hostname, content: TUNNEL + '.cfargotunnel.com', proxied: true, ttl: 1,
  });
  const next = await f.issue({ ...body(), origin_port: 49322 });
  assert.equal((await f.send(claimRequest(next.grant))).status, 200);
  assert.equal(f.upstream.config.ingress[0].service, 'http://127.0.0.1:49322');
  assert.equal(f.upstream.calls.filter(call => call.method === 'POST' && call.url.endsWith('/cfd_tunnel')).length, 1);
  assert.equal(f.upstream.calls.filter(call => call.method === 'POST' && call.url.endsWith('/dns_records')).length, 1);
  assert(!JSON.stringify(f.db.rows()).includes('connector-test-token'));
  for (const call of f.upstream.calls.filter(call => call.url.startsWith('https://api.cloudflare.com'))) {
    assert.equal(call.headers.Authorization, 'Bearer server-only-test-token');
    assert.equal(call.headers['X-Session-Token'], undefined);
    assert.equal(call.redirect, 'manual');
  }
});

test('missing or exhausted authenticated Cloudflare count blocks creation', async t => {
  for (const mode of ['missing', 'limit', 'failure']) {
    const f = fixture(t);
    const grant = await f.issue();
    f.upstream.missingCount = mode === 'missing';
    f.upstream.count = mode === 'limit' ? 900 : 0;
    if (mode === 'failure') f.upstream.fail = () => new Response('', { status: 403 });
    assert.equal((await f.send(claimRequest(grant.grant))).status, 502);
    assert.equal(f.upstream.calls.filter(call => call.method !== 'GET').length, 0);
    assert.equal(f.db.rows()[0].state, 'blocked');
    assert.equal((await f.send(claimRequest(grant.grant))).status, 409);
  }
});

test('grant is durably consumed before mutation; tunnel or DNS uncertainty is never retried', async t => {
  for (const stage of ['tunnel', 'config', 'dns', 'token']) {
    const f = fixture(t);
    const grant = await f.issue();
    let checked = false;
    f.upstream.fail = (url, init) => {
      if (init.method !== 'GET') {
        assert.equal(f.db.rows()[0].grant_hash, null);
        assert.equal(f.db.rows()[0].state, 'claiming');
        checked = true;
      }
      if ((stage === 'tunnel' && init.method === 'POST' && url.endsWith('/cfd_tunnel')) ||
          (stage === 'config' && url.endsWith('/configurations')) ||
          (stage === 'dns' && init.method === 'POST' && url.endsWith('/dns_records')) ||
          (stage === 'token' && url.endsWith('/token'))) throw new Error('lost provider reply with SECRET');
    };
    const result = await f.send(claimRequest(grant.grant));
    assert.equal(result.status, 502);
    assert(!JSON.stringify(await result.json()).includes('SECRET'));
    assert(checked);
    assert.equal(f.db.rows()[0].state, 'uncertain');
    const calls = f.upstream.calls.length;
    assert.equal((await f.send(claimRequest(grant.grant))).status, 409);
    assert.equal((await f.send(grantRequest(body()))).status, 409);
    assert.equal(f.upstream.calls.length, calls + 1); // Only a fresh fixed account GET.
  }
});

test('account-global mutation lock serializes independent claims and survives an uncertain create', async t => {
  const f = fixture(t);
  const first = await f.issue();
  const second = await f.issue(body(2));
  let release;
  let started;
  const atCreate = new Promise(resolve => { started = resolve; });
  f.upstream.fail = async (url, init) => {
    if (init.method === 'POST' && url.endsWith('/cfd_tunnel')) {
      started();
      await new Promise(resolve => { release = resolve; });
      throw new Error('uncertain create');
    }
  };
  const running = f.send(claimRequest(first.grant));
  await atCreate;
  assert.equal((await f.send(claimRequest(second.grant))).status, 409);
  assert(f.db.rows().find(row => row.computer_id === body(2).computer_id).grant_hash);
  release();
  assert.equal((await running).status, 502);
  assert.equal((await f.send(claimRequest(second.grant))).status, 409);
});

test('foreign named tunnel or DNS record is never adopted or overwritten', async t => {
  for (const collision of ['tunnel', 'dns']) {
    const f = fixture(t);
    const grant = await f.issue();
    if (collision === 'tunnel') {
      f.upstream.tunnel = { id: TUNNEL, name: grant.hostname.split('.')[0], config_src: 'cloudflare', deleted_at: null };
      f.upstream.count = 1;
    } else {
      f.upstream.record = { id: 'd'.repeat(32), type: 'CNAME', name: grant.hostname, content: 'foreign.cfargotunnel.com', proxied: true };
    }
    assert.equal((await f.send(claimRequest(grant.grant))).status, 502);
    assert.equal(f.upstream.calls.filter(call => call.method === 'PUT' && call.url.includes('/dns_records/')).length, 0);
    assert.equal(f.upstream.calls.filter(call => call.method === 'POST' && call.url.endsWith('/dns_records')).length, 0);
    if (collision === 'tunnel') assert.equal(f.upstream.calls.filter(call => call.method !== 'GET').length, 0);
  }
});

test('migration hard limits survive direct SQL and owner changes', async t => {
  const f = fixture(t);
  const insert = f.db.sqlite.prepare(`INSERT INTO computers
    (computer_id, owner_id, hpke_public_key, certificate_sha256, hostname, origin_port, state, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, 1234, 'reserved', 1, 1)`);
  for (let i = 0; i < 900; i++) insert.run('id-' + i, 'owner-' + i, 'key-' + i, 'c'.repeat(64), 'host-' + i);
  assert.throws(() => insert.run('overflow', 'another-owner', 'another-key', 'c'.repeat(64), 'another-host'), /global_capacity/);
  assert.throws(() => f.db.sqlite.prepare("UPDATE computers SET owner_id = 'new-owner' WHERE computer_id = 'id-0'").run(), /immutable_identity/);
  const g = fixture(t);
  const direct = g.db.sqlite.prepare(`INSERT INTO computers
    (computer_id, owner_id, hpke_public_key, certificate_sha256, hostname, origin_port, state, created_at, updated_at)
    VALUES (?, 'same-owner', ?, ?, ?, 1234, 'reserved', 1, 1)`);
  for (let i = 0; i < 3; i++) direct.run('id-' + i, 'key-' + i, 'c'.repeat(64), 'host-' + i);
  assert.throws(() => direct.run('fourth', 'key-4', 'c'.repeat(64), 'host-4'), /owner_capacity/);
});

test('parallel global admission at 899 accepts exactly one new computer across owners', async t => {
  const f = fixture(t);
  const insert = f.db.sqlite.prepare(`INSERT INTO computers
    (computer_id, owner_id, hpke_public_key, certificate_sha256, hostname, origin_port, state, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, 1234, 'reserved', 1, 1)`);
  for (let i = 0; i < 899; i++) insert.run('id-' + i, 'owner-' + i, 'key-' + i, 'c'.repeat(64), 'host-' + i);
  let n = 0;
  f.upstream.auth = () => Response.json({ id: `11111111-1111-4111-8111-${String(++n).padStart(12, '0')}` });
  const responses = await Promise.all(Array.from({ length: 8 }, (_, i) => f.send(grantRequest(body(i + 1)))));
  assert.equal(responses.filter(response => response.status === 200).length, 1);
  assert.equal(f.db.rows().length, 900);
});

test('expired reservations keep the quota and cannot transfer identity', async t => {
  const f = fixture(t);
  await f.issue(body(1)); await f.issue(body(2)); await f.issue(body(3));
  f.advance(301);
  assert.equal((await f.send(grantRequest(body(4)))).status, 409);
  assert.equal((await f.send(grantRequest(body(1)))).status, 200);
  assert.equal(f.db.rows().length, 3);
});

test('a D1 checkpoint failure after tunnel creation preserves uncertainty and never recreates', async t => {
  const f = fixture(t);
  const grant = await f.issue();
  const prepare = f.db.prepare.bind(f.db);
  f.db.prepare = sql => {
    if (sql.startsWith('UPDATE computers SET tunnel_id')) throw new Error('storage unavailable');
    return prepare(sql);
  };
  assert.equal((await f.send(claimRequest(grant.grant))).status, 502);
  assert.equal(f.db.rows()[0].state, 'uncertain');
  assert.equal((await f.send(claimRequest(grant.grant))).status, 409);
  assert.equal((await f.send(grantRequest(body()))).status, 409);
  assert.equal(f.upstream.calls.filter(call => call.method === 'POST' && call.url.endsWith('/cfd_tunnel')).length, 1);
});

test('failed uncertainty write retains the earlier durable claiming barrier', async t => {
  const f = fixture(t);
  const grant = await f.issue();
  const batch = f.db.batch.bind(f.db);
  f.upstream.fail = (url, init) => {
    if (init.method === 'POST' && url.endsWith('/cfd_tunnel')) {
      f.db.batch = async () => { throw new Error('D1 unavailable'); };
      throw new Error('lost tunnel reply');
    }
  };
  assert.equal((await f.send(claimRequest(grant.grant))).status, 502);
  assert.equal(f.db.rows()[0].state, 'claiming');
  assert.equal(f.db.rows()[0].grant_hash, null);
  f.db.batch = batch;
  assert.equal((await f.send(claimRequest(grant.grant))).status, 409);
  assert.equal((await f.send(grantRequest(body()))).status, 409);
});

test('provider redirects, malformed inventory, and unexpected ingress cannot issue a token', async t => {
  for (const mode of ['redirect', 'body-overflow', 'missing-count', 'page-short', 'wrong-ingress', 'wrong-id']) {
    const f = fixture(t);
    const grant = await f.issue();
    f.upstream.fail = (url, init) => {
      if (url.includes('/tunnels?')) {
        if (mode === 'redirect') return new Response('', { status: 307, headers: { location: 'https://evil.invalid' } });
        if (mode === 'body-overflow') return json([], { pad: 'x'.repeat(2 * 1024 * 1024) });
        if (mode === 'missing-count') return json([]);
        if (mode === 'page-short') return json([], { result_info: { total_count: 1 } });
      }
      if (url.endsWith('/configurations') && mode === 'wrong-ingress') return json({ config: {
        ingress: [{ hostname: grant.hostname, service: 'http://192.168.1.1:80' }, { service: 'http_status:404' }],
      } });
      if (url.endsWith('/cfd_tunnel') && init.method === 'POST' && mode === 'wrong-id') return json({
        id: '../../foreign', name: grant.hostname.split('.')[0], config_src: 'cloudflare', deleted_at: null,
      });
    };
    assert.equal((await f.send(claimRequest(grant.grant))).status, 502);
    assert.equal(f.upstream.calls.filter(call => call.url.endsWith('/token')).length, 0);
    assert.equal((await f.send(claimRequest(grant.grant))).status, 409);
  }
});

test('provider JSON key order does not change safe ingress confirmation', async t => {
  const f = fixture(t);
  const grant = await f.issue();
  f.upstream.fail = url => {
    if (url.endsWith('/configurations')) return json({ config: { ingress: [
      { service: 'http://127.0.0.1:49321', hostname: grant.hostname, originRequest: {} },
      { service: 'http_status:404' },
    ] } });
  };
  assert.equal((await f.send(claimRequest(grant.grant))).status, 200);
});
