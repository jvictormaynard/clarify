import assert from 'node:assert/strict';

import test from 'node:test';

import { spawnSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';

import { createRequire } from 'node:module';

import fs from 'node:fs';

import os from 'node:os';

import path from 'node:path';

import { generateKeyPairSync } from 'node:crypto';

const script = fileURLToPath(new URL('../scripts/publish-testflight.cjs', import.meta.url));

const require = createRequire(import.meta.url);

const helper = require(script);

const root = path.resolve(path.dirname(script), '../..');

const privateKey = generateKeyPairSync('ec', { namedCurve: 'P-256' }).privateKey
  .export({ type: 'pkcs8', format: 'pem' }).toString();

const stable = JSON.parse(fs.readFileSync(path.join(root, 'mobile/app.json'), 'utf8')).expo;

const currentNotes: Record<string, string> = {
  'pt-BR': `Teste interno do Clarify ${stable.version} (${stable.ios.buildNumber}). Consulte o relat\u00f3rio de valida\u00e7\u00e3o desta vers\u00e3o.`,
  'en-US': `Internal test of Clarify ${stable.version} (${stable.ios.buildNumber}). See this build's validation report.`,
  'es-ES': `Prueba interna de Clarify ${stable.version} (${stable.ios.buildNumber}). Consulte el informe de validaci\u00f3n de esta versi\u00f3n.`
};


function fixture(t: { after: (callback: () => void) => void }) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-testflight-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return { directory, env: { RUNNER_TEMP: directory,
    CLARIFY_ASC_KEY_ID: 'synthetic', CLARIFY_ASC_ISSUER_ID: 'synthetic', CLARIFY_ASC_KEY_P8: privateKey },
 };
}
function dependencies(f: ReturnType<typeof fixture>, apple: Apple) {
  const receipts: unknown[] = [], logs: string[] = [];
  return { env: f.env, fetch: apple.fetch, sleep: async () => {},
    log: (value: string) => logs.push(value), writeReceipt: (value: unknown) => receipts.push(value),
    now: () => new Date('2026-10-27T06:00:00Z'), receipts, logs };
}


class Apple {
  calls: { url: URL; method: string; body?: { data: unknown } }[] = [];
  attached = false;
  delayed = false;
  membershipReads = 0;
  detailReads = 0;
  failStatus = 0;
  rawBodyReads = 0;
  externalNext = false;
  otherBuild = false;
  duplicateBuild = false;
  internalGroup: boolean | string = true;
  pagedMembership = false;
  pagedTesters = false;
  selectedVersion = stable.version;
  selectedBuild = stable.ios.buildNumber;
  fetch = async (input: string, init: { method: string; body?: string; redirect?: string }): Promise<{
    ok: boolean; status: number; json: () => Promise<unknown>;
  }> => {
    const url = new URL(input);
    assert.equal(url.origin, 'https://api.appstoreconnect.apple.com');
    assert.equal(init.redirect, 'error');
    const body = init.body ? JSON.parse(init.body) : undefined;
    this.calls.push({ url, method: init.method, body });
    if (this.failStatus) return { ok: false, status: this.failStatus, json: async () => {
      this.rawBodyReads++; return { errors: [{ detail: 'PRIVATE_TOKEN_AND_EMAIL' }] }; } };
    let data: unknown = [];
    let extra = {};
    const endpoint = url.pathname.slice('/v1/'.length);
    if (endpoint === 'betaGroups') {
      assert.equal(url.searchParams.get('filter[app]'), '6820869157');
      data = [{ id: '111', attributes: { name: 'Clarify Interno', isInternalGroup: this.internalGroup } }];
      if (this.externalNext) extra = { links: { next: 'https://attacker.invalid/v1/betaGroups' } };
    } else if (endpoint === 'builds') {
      assert.equal(url.searchParams.get('filter[app]'), '6820869157');
      assert.equal(url.searchParams.get('filter[version]'), this.selectedBuild);
      const item = { id: '222', attributes: { version: this.otherBuild ? '999' : this.selectedBuild,
        processingState: 'VALID' }, relationships: { preReleaseVersion: { data: { id: '333' } } } };
      data = this.duplicateBuild ? [item, { ...item, id: '223' }] : [item];
      extra = { included: [{ id: '333', type: 'preReleaseVersions', attributes: { version: this.selectedVersion } }] };
    } else if (endpoint === 'betaGroups/111/relationships/builds') {
      assert.equal(init.method, 'POST');
      assert.deepEqual(body, { data: [{ type: 'builds', id: '222' }] });
      this.attached = true;
    } else if (endpoint === 'betaGroups/111/builds') {
      this.membershipReads++;
      data = this.attached ? [{ id: '222' }] : [];
      if (this.pagedMembership && !url.searchParams.has('cursor')) {
        data = [{ id: '999' }];
        extra = { links: { next: 'https://api.appstoreconnect.apple.com/v1/betaGroups/111/builds?limit=100&cursor=next' } };
      }
    } else if (endpoint === 'builds/222/betaBuildLocalizations') {
      data = [];
    } else if (endpoint === 'betaBuildLocalizations') {
      assert.equal(init.method, 'POST');
    } else if (endpoint === 'builds/222/buildBetaDetail') {
      this.detailReads++;
      data = { attributes: { internalBuildState: this.delayed && this.detailReads === 1
        ? 'READY_FOR_BETA_TESTING' : 'IN_BETA_TESTING' } };
    } else if (endpoint === 'betaGroups/111/relationships/betaTesters') {
      data = [{ id: url.searchParams.has('cursor') ? 'private-tester-2' : 'private-tester',
        attributes: { email: 'PRIVATE_EMAIL' } }];
      if (this.pagedTesters && !url.searchParams.has('cursor')) {
        extra = { links: { next: 'https://api.appstoreconnect.apple.com/v1/betaGroups/111/relationships/betaTesters?limit=200&cursor=next' } };
      }
    } else throw new Error('Unexpected Apple operation: ' + init.method + ' ' + endpoint);
    return { ok: true, status: 200, json: async () => ({ data, ...extra }) };
  };
}

test('importing the availability helper does not read credentials or contact Apple', () => {
  const env = { ...process.env };
  for (const name of Object.keys(env)) if (name.startsWith('CLARIFY_ASC_')) delete env[name];
  const result = spawnSync(process.execPath, ['-e', `require(${JSON.stringify(script)})`], { env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
  assert.equal(result.stderr, '');
});

test('stable mode retains identity and receipt fields with current build notes', async t => {
  const f = fixture(t), apple = new Apple();
  apple.selectedVersion = stable.version;
  apple.selectedBuild = stable.ios.buildNumber;
  const deps = dependencies(f, apple);
  const result = await helper.main([], deps);
  assert.deepEqual(result, { checkedAt: '2026-10-27T06:00:00.000Z', id: '222',
    version: stable.version, build: stable.ios.buildNumber, processing: 'VALID',
    internalState: 'IN_BETA_TESTING', group: 'Clarify Interno', availableInGroup: true, existingTesters: 1 });
  const localizations = apple.calls.filter(call => call.url.pathname === '/v1/betaBuildLocalizations');
  for (const call of localizations) {
    const data = call.body!.data as { attributes: { locale: string; whatsNew: string } };
    assert.equal(data.attributes.whatsNew, currentNotes[data.attributes.locale]);
  }
});

test('stable availability rejects a changed build number or ambiguous build identity before writes', async t => {
  const f = fixture(t);
  for (const flag of ['otherBuild', 'duplicateBuild'] as const) {
    const apple = new Apple();
    apple.selectedVersion = stable.version;
    apple.selectedBuild = stable.ios.buildNumber;
    apple[flag] = true;
    const deps = dependencies(f, apple);
    await assert.rejects(helper.main([], deps));
    assert.equal(apple.calls.filter(call => call.method !== 'GET').length, 0);
    assert.equal(deps.receipts.length, 0);
  }
});

test('stable failures preserve Apple details and original network and JSON errors', async t => {
  const f = fixture(t), deps = dependencies(f, new Apple());
  deps.fetch = async () => ({ ok: false, status: 503, json: async () => ({ errors: [
    { code: 'SERVICE_ERROR', detail: 'Synthetic response detail' },
    { code: 'OTHER_ERROR', title: 'Synthetic response title' },
  ] }) });
  await assert.rejects(helper.main([], deps), {
    message: 'Apple API 503 for GET betaGroups: SERVICE_ERROR: Synthetic response detail; OTHER_ERROR: Synthetic response title',
  });
  const networkError = new Error('Synthetic network failure');
  deps.fetch = async () => { throw networkError; };
  await assert.rejects(helper.main([], deps), error => error === networkError);
  const jsonError = new SyntaxError('Synthetic JSON failure');
  deps.fetch = async () => ({ ok: true, status: 200, json: async () => { throw jsonError; } });
  await assert.rejects(helper.main([], deps), error => error === jsonError);
});

test('stable mode queries the group before reading incomplete iOS configuration', async t => {
  const f = fixture(t), cached = require(path.join(root, 'mobile/app.json')).expo;
  const originalIOS = cached.ios;
  delete cached.ios;
  try {
    const deps = dependencies(f, new Apple());
    const requests: string[] = [];
    deps.fetch = async input => {
      requests.push(input);
      return { ok: true, status: 200, json: async () => ({ data: [] }) };
    };
    await assert.rejects(helper.main([], deps), { message: 'The existing internal group was not found.' });
    assert.equal(requests.length, 1);
    assert.equal(new URL(requests[0]).pathname, '/v1/betaGroups');
    const networkError = new Error('Synthetic group request failed');
    deps.fetch = async () => { throw networkError; };
    await assert.rejects(helper.main([], deps), error => error === networkError);
  } finally {
    cached.ios = originalIOS;
  }
});

test('stable pending output keeps the original processing state until the unchanged failure', async t => {
  const f = fixture(t), apple = new Apple(), deps = dependencies(f, apple);
  deps.fetch = async (input: string, init: { method: string; body?: string; redirect?: string }) => {
    if (new URL(input).pathname === '/v1/builds') return { ok: true, status: 200, json: async () => ({
      data: [{ id: '222', attributes: { version: stable.ios.buildNumber, processingState: 'SYNTHETIC_UNKNOWN_STATE' },
        relationships: { preReleaseVersion: { data: { id: '333' } } } }],
      included: [{ id: '333', type: 'preReleaseVersions', attributes: { version: stable.version } }],
    }) };
    return apple.fetch(input, init);
  };
  await assert.rejects(helper.main([], deps), { message: 'Apple processing or internal TestFlight availability is still pending.' });
  assert.deepEqual(deps.logs, Array(40).fill(JSON.stringify({
    version: stable.version, build: stable.ios.buildNumber, processing: 'SYNTHETIC_UNKNOWN_STATE',
  })));
  assert.equal(deps.receipts.length, 0);
});

test('stable CLI failures retain exit code and exact output', t => {
  const f = fixture(t), preload = path.join(f.directory, 'synthetic-fetch.cjs');
  const failures = [
    { fetch: "async () => { throw new Error('Synthetic network failure'); }", message: 'Synthetic network failure' },
    { fetch: "async () => ({ ok: false, status: 503, json: async () => ({ errors: [{ code: 'SERVICE_ERROR', detail: 'Synthetic response detail' }] }) })",
      message: 'Apple API 503 for GET betaGroups: SERVICE_ERROR: Synthetic response detail' },
    { fetch: "async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('Synthetic JSON failure'); } })",
      message: 'Synthetic JSON failure' },
  ];
  for (const failure of failures) {
    fs.writeFileSync(preload, 'globalThis.fetch = ' + failure.fetch + ';');
    for (const args of [[]]) {
      const result = spawnSync(process.execPath, ['--require', preload, script, ...args], {
        env: { ...process.env, ...f.env }, cwd: f.directory, encoding: 'utf8',
      });
      assert.equal(result.status, 1, result.stderr);
      assert.equal(result.stdout, '');
      assert.equal(result.stderr.replace(/\r\n/g, '\n'), failure.message + '\n');
    }
  }
  const env = { ...process.env };
  for (const name of Object.keys(env)) if (name.startsWith('CLARIFY_ASC_')) delete env[name];
  for (const args of [[]]) {
    const result = spawnSync(process.execPath, [script, ...args], { env, cwd: f.directory, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.equal(result.stdout, '');
    assert.equal(result.stderr.replace(/\r\n/g, '\n'), 'Missing configured App Store Connect credential.\n');
  }
});


test('unsupported options stop before credentials or Apple requests', async t => {
  const f = fixture(t), apple = new Apple(), deps = dependencies(f, apple);
  for (const args of [['--ignored'], ['--qa-context', 'retired.json'], ['--mode', 'status']]) {
    await assert.rejects(helper.main(args, deps), /without arguments/);
  }
  assert.equal(apple.calls.length, 0);
  assert.equal(deps.receipts.length, 0);
});
test('delayed availability associates a build once and waits for internal availability', async t => {
  const f = fixture(t), apple = new Apple(); apple.delayed = true;
  const result = await helper.main([], dependencies(f, apple));
  assert.equal(result.availableInGroup, true);
  assert.equal(apple.calls.filter(c => c.url.pathname.endsWith('/relationships/builds')).length, 1);
  assert.equal(apple.detailReads, 2);
});
test('an existing association is reused without a membership write', async t => {
  const f = fixture(t), apple = new Apple(); apple.attached = true;
  await helper.main([], dependencies(f, apple));
  assert.equal(apple.calls.filter(c => c.url.pathname.endsWith('/relationships/builds')).length, 0);
});
test('membership and tester pagination retains every page', async t => {
  const f = fixture(t), apple = new Apple();
  apple.attached = true; apple.pagedMembership = true; apple.pagedTesters = true;
  const result = await helper.main([], dependencies(f, apple));
  assert.equal(result.existingTesters, 2);
  assert.equal(apple.calls.filter(c => c.url.pathname.endsWith('/relationships/builds')).length, 0);
});
test('foreign pagination and an external or malformed group cannot cause Apple writes', async t => {
  const f = fixture(t);
  for (const invalid of ['pagination', false, 'true'] as const) {
    const apple = new Apple();
    if (invalid === 'pagination') apple.externalNext = true; else apple.internalGroup = invalid;
    await assert.rejects(helper.main([], dependencies(f, apple)));
    assert.equal(apple.calls.filter(c => c.method !== 'GET').length, 0);
  }
});
