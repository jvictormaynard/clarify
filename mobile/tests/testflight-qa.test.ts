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
// Git results are injected by the fixtures, including in Git-free execution roots.
const base = 'd'.repeat(40);
const baseTree = 'e'.repeat(40);
const source = 'a'.repeat(40);
const privateKey = generateKeyPairSync('ec', { namedCurve: 'P-256' }).privateKey
  .export({ type: 'pkcs8', format: 'pem' }).toString();
const stable = JSON.parse(fs.readFileSync(path.join(root, 'mobile/app.json'), 'utf8')).expo;
// Frozen default-note oracle from immutable stable source 678772aadda5d5eec78bd8f2b818635a7657ba90.
const originalNotes: Record<string, string> = {
  "pt-BR": "Entre ou crie sua conta com Google, Microsoft ou GitHub. A aba Conta mostra o consumo semanal e a pr\u00f3xima renova\u00e7\u00e3o. Esta vers\u00e3o mant\u00e9m as quatro abas, o guia inicial e as corre\u00e7\u00f5es de grava\u00e7\u00e3o do build 37.",
  "en-US": "Sign in or create an account with Google, Microsoft or GitHub. Account shows weekly usage and the next reset. This version preserves the four tabs, first-launch guide and recording fixes from build 37.",
  "es-ES": "Inicia sesi\u00f3n o crea una cuenta con Google, Microsoft o GitHub. Cuenta muestra el consumo semanal y la pr\u00f3xima renovaci\u00f3n. Esta versi\u00f3n conserva las cuatro pesta\u00f1as, la gu\u00eda inicial y las correcciones de grabaci\u00f3n del build 37."
};

function fixture(t: { after: (callback: () => void) => void }) {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-qa-helper-')));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const qa = path.join(directory, 'clarify-ios-qa');
  fs.mkdirSync(path.join(qa, 'output'), { recursive: true });
  const contextPath = path.join(qa, 'context.json');
  const context = { schema: 1, repository: 'jvictormaynard/clarify', pr: 179,
    source_sha: source, source_tree: 'b'.repeat(40), trusted_sha: base, base_sha: base, base_tree: baseTree,
    workflow: { id: 99, path: '.github/workflows/ios-qa.yml', blob_sha: 'f'.repeat(40) }, version: '1.2.3', build: '8',
    tag: 'ios/pr-179/v1.2.3-build8', run_id: 33986942056, run_attempt: 1,
    artifact: { id: 123, name: 'clarify-ios-qa-unsigned-' + source, run_id: 33986942056,
      run_attempt: 1, sha256: 'd'.repeat(64), bytes: 123 },
    ipa: { sha256: 'e'.repeat(64), bytes: 456 },
    bundles: [
      ['com.jvictormaynard.clarify', 'Payload/Clarify.app', 'Clarify'],
      ['com.jvictormaynard.clarify.keyboard', 'Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex', 'ClarifyKeyboard'],
      ['com.jvictormaynard.clarify.activity', 'Payload/Clarify.app/PlugIns/ClarifyActivity.appex', 'ClarifyActivity'],
    ].map(([id, location, executable]) => ({ id, path: location, executable, sha256: '1'.repeat(64),
      executable_sha256: '2'.repeat(64), executable_bytes: 64 })) };
  const env = { RUNNER_TEMP: directory, GITHUB_REPOSITORY: 'jvictormaynard/clarify',
    GITHUB_EVENT_NAME: 'workflow_dispatch', GITHUB_REF: 'refs/heads/main', GITHUB_SHA: base,
    QA_WORKFLOW_SHA: base, QA_WORKFLOW_ID: '99', QA_WORKFLOW_REF: 'jvictormaynard/clarify/.github/workflows/ios-qa.yml@refs/heads/main',
    GITHUB_RUN_ID: String(context.run_id), GITHUB_RUN_ATTEMPT: '1',
    CLARIFY_ASC_KEY_ID: 'synthetic', CLARIFY_ASC_ISSUER_ID: 'synthetic', CLARIFY_ASC_KEY_P8: privateKey };
  const save = () => fs.writeFileSync(contextPath, JSON.stringify(context));
  const git = (program: string, args: string[], options: { cwd: string }) => {
    assert.equal(program, 'git');
    assert.equal(options.cwd, root);
    if (args[0] === 'rev-parse') return (args[1].endsWith('^{tree}') ? baseTree
      : args[1].includes(':.github/') ? 'f'.repeat(40) : base) + '\n';
    assert.equal(args[0], 'diff');
    return '';
  };
  save();
  return { directory, qa, contextPath, context, env, git, save };
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
  expectQA = true;
  selectedVersion = '1.2.3';
  selectedBuild = '8';
  fetch = async (input: string, init: { method: string; body?: string; redirect?: string }): Promise<{
    ok: boolean; status: number; json: () => Promise<unknown>;
  }> => {
    const url = new URL(input);
    assert.equal(url.origin, 'https://api.appstoreconnect.apple.com');
    assert.equal(init.redirect, this.expectQA ? 'error' : undefined);
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

function dependencies(f: ReturnType<typeof fixture>, apple: Apple) {
  const receipts: unknown[] = [], logs: string[] = [];
  return { env: f.env, git: f.git, fetch: apple.fetch, sleep: async () => {},
    log: (value: string) => logs.push(value), writeReceipt: (value: unknown) => receipts.push(value),
    now: () => new Date('2026-10-27T06:00:00Z'), receipts, logs };
}

test('importing the availability helper does not read credentials or contact Apple', () => {
  const env = { ...process.env };
  for (const name of Object.keys(env)) if (name.startsWith('CLARIFY_ASC_')) delete env[name];
  const result = spawnSync(process.execPath, ['-e', `require(${JSON.stringify(script)})`], { env, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
  assert.equal(result.stderr, '');
});

test('QA uses the explicit identity and fixed notes, with one membership write during delayed availability', async t => {
  const f = fixture(t), apple = new Apple();
  apple.delayed = true;
  const deps = dependencies(f, apple);
  const result = await helper.main(['--qa-context', f.contextPath], deps);
  assert.equal(apple.calls.filter(call => call.url.pathname.endsWith('/relationships/builds')).length, 1);
  assert.equal(apple.calls.filter(call => call.url.pathname === '/v1/betaBuildLocalizations').length, 3);
  const localizations = apple.calls.filter(call => call.url.pathname === '/v1/betaBuildLocalizations');
  for (const call of localizations) {
    const data = call.body!.data as { attributes: { locale: string; whatsNew: string } };
    assert.equal(data.attributes.whatsNew, helper.QA_NOTES[data.attributes.locale]);
    assert.match(data.attributes.whatsNew, /WAN/);
  }
  assert.equal(result.qa.source_sha, source);
  assert.equal(result.qa.ipa.sha256, 'e'.repeat(64));
  assert.equal(result.ipaVerifiedByThisHelper, false);
  assert.equal(result.workflowArtifactProvenanceVerified, false);
  assert.equal(result.existingTesters, 1);
  assert.equal(result.availableInGroup, true);
  assert.equal(deps.receipts.length, 1);
  assert.doesNotMatch(deps.logs.join('\n'), /PRIVATE_EMAIL|PRIVATE_TOKEN|PRIVATE KEY/);
});

test('already attached builds are queried without another membership write', async t => {
  const f = fixture(t), apple = new Apple();
  apple.attached = true;
  await helper.main(['--qa-context', f.contextPath], dependencies(f, apple));
  assert.equal(apple.calls.filter(call => call.url.pathname.endsWith('/relationships/builds')).length, 0);
});

test('a later availability run keeps the original artifact producer identity without rebuilding', async t => {
  const f = fixture(t), apple = new Apple();
  f.context.artifact.run_id = 123456;
  f.context.artifact.run_attempt = 2;
  f.save();
  apple.attached = true;
  const result = await helper.main(['--qa-context', f.contextPath], dependencies(f, apple));
  assert.equal(result.qa.artifact.run_id, 123456);
  assert.equal(result.qa.artifact.run_attempt, 2);
  assert.equal(result.qa.run_id, 33986942056);
  assert.equal(apple.calls.filter(call => call.url.pathname.endsWith('/relationships/builds')).length, 0);
});

test('stable mode retains main identity, original notes, result fields and no QA git checks', async t => {
  const f = fixture(t), apple = new Apple();
  apple.selectedVersion = stable.version;
  apple.selectedBuild = stable.ios.buildNumber;
  apple.expectQA = false;
  const deps = dependencies(f, apple);
  deps.git = () => { throw new Error('Stable mode must not load a QA context'); };
  const result = await helper.main([], deps);
  assert.deepEqual(result, { checkedAt: '2026-10-27T06:00:00.000Z', id: '222',
    version: stable.version, build: stable.ios.buildNumber, processing: 'VALID',
    internalState: 'IN_BETA_TESTING', group: 'Clarify Interno', availableInGroup: true, existingTesters: 1 });
  const localizations = apple.calls.filter(call => call.url.pathname === '/v1/betaBuildLocalizations');
  for (const call of localizations) {
    const data = call.body!.data as { attributes: { locale: string; whatsNew: string } };
    assert.equal(data.attributes.whatsNew, originalNotes[data.attributes.locale]);
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

test('stable mode ignores extra arguments without interpreting them as QA', async t => {
  const f = fixture(t), apple = new Apple();
  apple.selectedVersion = stable.version;
  apple.selectedBuild = stable.ios.buildNumber;
  apple.expectQA = false;
  const deps = dependencies(f, apple);
  deps.git = () => { throw new Error('Stable mode must not load a QA context'); };
  const result = await helper.main(['--ignored', 'value'], deps);
  assert.equal(result.version, stable.version);
  assert.equal(result.build, stable.ios.buildNumber);
  assert.equal(result.availableInGroup, true);
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

test('QA mode rejects extra or misplaced arguments before reading context or calling Apple', async t => {
  const f = fixture(t), apple = new Apple();
  const deps = dependencies(f, apple);
  deps.git = () => { throw new Error('Invalid arguments must not read the checkout'); };
  for (const args of [['--qa-context'], ['--qa-context', f.contextPath, '--ignored'],
    ['--ignored', '--qa-context', f.contextPath]]) {
    await assert.rejects(helper.main(args, deps), { message: 'Use [--qa-context ABS_JSON]' });
  }
  assert.equal(apple.calls.length, 0);
});

test('stable pending output keeps the original processing state until the unchanged failure', async t => {
  const f = fixture(t), apple = new Apple(), deps = dependencies(f, apple);
  apple.expectQA = false;
  deps.fetch = async (input: string, init: { method: string; body?: string; redirect?: string }) => {
    if (new URL(input).pathname === '/v1/builds') return { ok: true, status: 200, json: async () => ({
      data: [{ id: '222', attributes: { processingState: 'SYNTHETIC_UNKNOWN_STATE' },
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

test('stable CLI failures retain exit code and exact output without the QA flag', t => {
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
    for (const args of [[], ['--ignored', 'value']]) {
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
  for (const args of [[], ['--ignored', 'value']]) {
    const result = spawnSync(process.execPath, [script, ...args], { env, cwd: f.directory, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.equal(result.stdout, '');
    assert.equal(result.stderr.replace(/\r\n/g, '\n'), 'Missing configured App Store Connect credential.\n');
  }
});

test('unknown fields, altered identities, unsafe numbers and another attempt block before fetch', async t => {
  const f = fixture(t), original = structuredClone(f.context);
  const mutations = [
    (c: Record<string, unknown>) => { c.endpoint = 'https://attacker.invalid'; },
    (c: Record<string, unknown>) => { c.notes = 'arbitrary'; },
    (c: Record<string, unknown>) => { c.schema = true; },
    (c: Record<string, unknown>) => { c.source_sha = source + '\n'; },
    (c: Record<string, unknown>) => { c.base_sha = 'b'.repeat(40); },
    (c: Record<string, unknown>) => { c.run_id = Number.MAX_SAFE_INTEGER + 1; },
    (c: Record<string, unknown>) => { c.run_attempt = 2; },
    (c: Record<string, unknown>) => { c.build = '08'; },
    (c: Record<string, unknown>) => { c.tag = 'ios/v1.2.3-build8'; },
  ];
  for (const mutate of mutations) {
    const context = structuredClone(original);
    mutate(context);
    fs.writeFileSync(f.contextPath, JSON.stringify(context));
    const apple = new Apple();
    await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)));
    assert.equal(apple.calls.length, 0);
  }
});

test('duplicate JSON keys including escaped spellings are rejected', t => {
  const f = fixture(t);
  for (const raw of [JSON.stringify(f.context).replace('"schema":1', '"schema":1,"schema":1'),
    JSON.stringify(f.context).replace('"schema":1', '"schema":1,"schem\\u0061":1'),
    JSON.stringify(f.context).replace('"id":123', '"id":123,"id":123')]) {
    assert.throws(() => helper.decodeContext(raw), /Duplicate/);
  }
});

test('relative, escaped, outside and hard-linked context files are rejected', async t => {
  const f = fixture(t), apple = new Apple();
  for (const filename of ['context.json', path.join(f.directory, 'elsewhere.json'),
    path.join(f.qa, 'output') + path.sep + '..' + path.sep + 'context.json']) {
    await assert.rejects(helper.main(['--qa-context', filename], dependencies(f, apple)));
  }
  fs.linkSync(f.contextPath, path.join(f.directory, 'linked.json'));
  await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)), /regular file/);
  assert.equal(apple.calls.length, 0);
});

test('a tag run, dirty helper checkout or foreign trusted SHA cannot reach Apple', async t => {
  const f = fixture(t), apple = new Apple();
  f.env.GITHUB_REF = 'refs/tags/ios/pr-179/v1.2.3-build8';
  await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)));
  f.env.GITHUB_REF = 'refs/heads/main';
  const deps = dependencies(f, apple);
  deps.git = () => 'b'.repeat(40);
  await assert.rejects(helper.main(['--qa-context', f.contextPath], deps));
  deps.git = (_program: string, args: string[]) => {
    if (args[0] === 'diff') throw new Error('modified trusted helper');
    return f.git(_program, args, { cwd: root });
  };
  await assert.rejects(helper.main(['--qa-context', f.contextPath], deps));
  assert.equal(apple.calls.length, 0);
});

test('unknown Apple error bodies and network failures are sanitized and not retried', async t => {
  const f = fixture(t), apple = new Apple();
  apple.failStatus = 500;
  await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)), /HTTP 500/);
  assert.equal(apple.rawBodyReads, 0);
  assert.equal(apple.calls.length, 1);
  const deps = dependencies(f, new Apple());
  deps.fetch = async () => { throw new Error('PRIVATE_TOKEN'); };
  await assert.rejects(helper.main(['--qa-context', f.contextPath], deps), error => {
    assert.doesNotMatch(String(error), /PRIVATE_TOKEN/);
    return true;
  });
});

test('foreign pagination and ambiguous builds stop without membership writes', async t => {
  const f = fixture(t);
  for (const flag of ['externalNext', 'duplicateBuild'] as const) {
    const apple = new Apple();
    apple[flag] = true;
    await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)));
    assert.equal(apple.calls.filter(call => call.method !== 'GET').length, 0);
  }
});

test('a different build number never becomes available under this context', async t => {
  const f = fixture(t), apple = new Apple();
  apple.otherBuild = true;
  const deps = dependencies(f, apple);
  await assert.rejects(helper.main(['--qa-context', f.contextPath], deps), /pending/);
  assert.equal(apple.calls.filter(call => call.method !== 'GET').length, 0);
  assert.equal(deps.receipts.length, 0);
});

test('QA checks all membership and tester pages without resending a group association', async t => {
  const f = fixture(t), apple = new Apple();
  apple.attached = true;
  apple.pagedMembership = apple.pagedTesters = true;
  const result = await helper.main(['--qa-context', f.contextPath], dependencies(f, apple));
  assert.equal(result.existingTesters, 2);
  assert.equal(apple.calls.filter(call => call.url.pathname.endsWith('/relationships/builds')).length, 0);
});

test('an external group or non-boolean internal flag is never used', async t => {
  const f = fixture(t);
  for (const internal of [false, 'false']) {
    const apple = new Apple();
    apple.internalGroup = internal;
    await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)));
    assert.equal(apple.calls.filter(call => call.method !== 'GET').length, 0);
  }
});

test('a symlinked context parent is refused before an Apple request', async t => {
  const f = fixture(t), apple = new Apple();
  const moved = path.join(f.directory, 'moved');
  fs.renameSync(f.qa, moved);
  try { fs.symlinkSync(moved, f.qa, 'junction'); }
  catch { t.skip('This Windows account cannot create directory links'); return; }
  await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)), /links/);
  assert.equal(apple.calls.length, 0);
});

test('trees, workflow identity/blob and fixed bundle paths are part of the mandatory binding', async t => {
  const f = fixture(t), original = structuredClone(f.context);
  const mutations = [
    (c: typeof original) => { c.source_tree = 'main'; },
    (c: typeof original) => { c.base_tree = 'c'.repeat(40); },
    (c: typeof original) => { c.workflow.id = 100; },
    (c: typeof original) => { c.workflow.blob_sha = '0'.repeat(40); },
    (c: typeof original) => { c.workflow.path = '.github/workflows/other.yml'; },
    (c: typeof original) => { c.bundles[0].path = '../candidate'; },
    (c: typeof original) => { c.bundles[1].executable = '../other'; },
  ];
  for (const mutate of mutations) {
    const context = structuredClone(original);
    mutate(context);
    fs.writeFileSync(f.contextPath, JSON.stringify(context));
    const apple = new Apple();
    await assert.rejects(helper.main(['--qa-context', f.contextPath], dependencies(f, apple)));
    assert.equal(apple.calls.length, 0);
  }
});

test('integer context fields reject floating and exponent JSON syntax', t => {
  const f = fixture(t);
  for (const token of ['1.0', '1e0']) {
    const raw = JSON.stringify(f.context).replace('"schema":1', '"schema":' + token);
    assert.throws(() => helper.decodeContext(raw), /integer JSON syntax/);
  }
});
