// Complete an authorized internal delivery. Importing this module has no effects.
const fs = require('node:fs');
const crypto = require('node:crypto');
const { Buffer } = require('node:buffer');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const config = require('../app.json').expo;
const app = require('../eas.json').submit.production.ios.ascAppId;
const notes = {
  "pt-BR": "Entre ou crie sua conta com Google, Microsoft ou GitHub. A aba Conta mostra o consumo semanal e a próxima renovação. Esta versão mantém as quatro abas, o guia inicial e as correções de gravação do build 37.",
  "en-US": "Sign in or create an account with Google, Microsoft or GitHub. Account shows weekly usage and the next reset. This version preserves the four tabs, first-launch guide and recording fixes from build 37.",
  "es-ES": "Inicia sesión o crea una cuenta con Google, Microsoft o GitHub. Cuenta muestra el consumo semanal y la próxima renovación. Esta versión conserva las cuatro pestañas, la guía inicial y las correcciones de grabación del build 37."
};

const ROOT = path.resolve(path.dirname(module.filename), '../..');
const ORIGIN = 'https://api.appstoreconnect.apple.com/v1/';
const APP_ID = '6820869157';
const GROUP = 'Clarify Interno';
const WORKFLOW = '.github/workflows/ios-qa.yml';
const BUNDLE_PATHS = [
  { id: 'com.jvictormaynard.clarify', path: 'Payload/Clarify.app', executable: 'Clarify' },
  { id: 'com.jvictormaynard.clarify.keyboard', path: 'Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex', executable: 'ClarifyKeyboard' },
  { id: 'com.jvictormaynard.clarify.activity', path: 'Payload/Clarify.app/PlugIns/ClarifyActivity.appex', executable: 'ClarifyActivity' },
];
const QA_NOTES = Object.freeze({
  'pt-BR': 'Teste interno da conexão com o computador na rede local. O acesso por WAN ainda não está disponível. A disponibilidade remota de ponta a ponta não foi verificada.',
  'en-US': 'Internal QA for the computer connection on the local network. WAN access is not available. End-to-end remote availability has not been verified.',
  'es-ES': 'Prueba interna de la conexión con el ordenador en la red local. El acceso por WAN aún no está disponible. La disponibilidad remota de extremo a extremo no se ha verificado.',
});

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}
function exactKeys(value, keys) {
  requireCondition(value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join(',') === [...keys].sort().join(','), 'Invalid QA context fields');
}
function positive(value, maximum = Number.MAX_SAFE_INTEGER) {
  requireCondition(Number.isSafeInteger(value) && value >= 1 && value <= maximum, 'Invalid QA integer');
}
function match(value, expression) {
  requireCondition(typeof value === 'string' && expression.exec(value)?.[0] === value, 'Invalid QA identity');
}
function validateQAContext(context) {
  exactKeys(context, ['schema', 'repository', 'pr', 'source_sha', 'source_tree', 'base_sha', 'base_tree', 'trusted_sha',
    'workflow', 'version', 'build', 'tag', 'run_id', 'run_attempt', 'artifact', 'ipa', 'bundles']);
  requireCondition(context.schema === 1 && context.pr === 179
    && context.repository === 'jvictormaynard/clarify', 'Unexpected QA scope');
  for (const key of ['source_sha', 'source_tree', 'base_sha', 'base_tree', 'trusted_sha']) match(context[key], /^[0-9a-f]{40}$/);
  exactKeys(context.workflow, ['id', 'path', 'blob_sha']);
  positive(context.workflow.id);
  requireCondition(context.workflow.path === WORKFLOW, 'Unexpected QA workflow path');
  match(context.workflow.blob_sha, /^[0-9a-f]{40}$/);
  requireCondition(context.base_sha === context.trusted_sha && context.source_sha !== context.base_sha, 'Unexpected QA composition');
  match(context.version, /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/);
  requireCondition(context.version.split('.').every(part => Number(part) <= 65535), 'Invalid QA version');
  match(context.build, /^[1-9][0-9]{0,8}$/);
  requireCondition(context.tag === 'ios/pr-179/v' + context.version + '-build' + context.build, 'Invalid QA tag');
  positive(context.run_id);
  positive(context.run_attempt, 100);
  exactKeys(context.artifact, ['id', 'name', 'run_id', 'run_attempt', 'sha256', 'bytes']);
  positive(context.artifact.id);
  requireCondition(context.artifact.name === 'clarify-ios-qa-unsigned-' + context.source_sha, 'Invalid QA artifact name');
  positive(context.artifact.run_id);
  positive(context.artifact.run_attempt, 100);
  exactKeys(context.ipa, ['sha256', 'bytes']);
  for (const item of [context.artifact, context.ipa]) {
    match(item.sha256, /^[0-9a-f]{64}$/);
    positive(item.bytes, 8 * 1024 ** 3);
  }
  requireCondition(Array.isArray(context.bundles) && context.bundles.length === 3, 'Expected three QA bundle digests');
  context.bundles.forEach((item, index) => {
    exactKeys(item, ['id', 'path', 'sha256', 'executable', 'executable_sha256', 'executable_bytes']);
    const expected = BUNDLE_PATHS[index];
    requireCondition(item.id === expected.id && item.path === expected.path && item.executable === expected.executable,
      'Unexpected QA bundle or executable path');
    match(item.sha256, /^[0-9a-f]{64}$/);
    match(item.executable_sha256, /^[0-9a-f]{64}$/);
    positive(item.executable_bytes, 512 * 1024 ** 2);
  });
  return context;
}

// JSON.parse validates syntax; this structural pass also rejects duplicate keys,
// including keys with escaped spellings. Values are never evaluated as code.
function decodeContext(text) {
  requireCondition(Buffer.byteLength(text, 'utf8') <= 8192, 'QA context is too large');
  const value = JSON.parse(text);
  const stack = [];
  for (const token of text.match(/"(?:\\[\s\S]|[^"\\])*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|[{}\[\],:]/g) || []) {
    if (/^[-0-9]/.test(token)) requireCondition(/^(0|[1-9][0-9]*)$/.test(token), 'QA numbers must use integer JSON syntax');
    if (token === '{') stack.push({ object: true, keys: new Set(), key: true });
    else if (token === '[') stack.push({ object: false });
    else if (token === '}' || token === ']') stack.pop();
    else {
      const top = stack[stack.length - 1];
      if (top?.object) {
        if (token === ',') top.key = true;
        else if (token === ':') top.key = false;
        else if (token.startsWith('"') && top.key) {
          const key = JSON.parse(token);
          requireCondition(!top.keys.has(key), 'Duplicate QA JSON field');
          top.keys.add(key);
        }
      }
    }
    requireCondition(stack.length <= 16, 'QA context is too deeply nested');
  }
  return validateQAContext(value);
}

function safeQAPath(value, relative, env, mustExist = true) {
  requireCondition(typeof env.RUNNER_TEMP === 'string' && path.isAbsolute(env.RUNNER_TEMP),
    'RUNNER_TEMP must be absolute');
  const expected = path.join(env.RUNNER_TEMP, 'clarify-ios-qa', relative);
  requireCondition(typeof value === 'string' && path.isAbsolute(value) && path.resolve(value) === expected
    && !value.split(/[\\/]/).includes('..'), 'Unexpected QA data path');
  let current = expected;
  for (;;) {
    const exists = fs.existsSync(current);
    if (!(current === expected && !mustExist && !exists)) {
      const info = fs.lstatSync(current);
      requireCondition(!info.isSymbolicLink(), 'QA paths must not contain links');
      if (current === expected) requireCondition(info.isFile() && info.nlink === 1, 'QA data must be one regular file');
      else requireCondition(info.isDirectory(), 'QA parent must be a directory');
    } else {
      // existsSync is false for a dangling symlink as well.
      try { fs.lstatSync(current); throw new Error('QA output must not be a dangling link'); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return expected;
}

function loadQAContext(value, { env = process.env, git = execFileSync } = {}) {
  const filename = safeQAPath(value, 'context.json', env);
  requireCondition(fs.statSync(filename).size <= 8192, 'QA context is too large');
  const context = decodeContext(fs.readFileSync(filename, 'utf8'));
  const expected = {
    GITHUB_REPOSITORY: context.repository, GITHUB_EVENT_NAME: 'workflow_dispatch',
    GITHUB_REF: 'refs/heads/main', GITHUB_SHA: context.trusted_sha, QA_WORKFLOW_SHA: context.trusted_sha,
    QA_WORKFLOW_ID: String(context.workflow.id),
    QA_WORKFLOW_REF: 'jvictormaynard/clarify/.github/workflows/ios-qa.yml@refs/heads/main',
    GITHUB_RUN_ID: String(context.run_id), GITHUB_RUN_ATTEMPT: String(context.run_attempt),
  };
  requireCondition(Object.entries(expected).every(([name, value]) => env[name] === value),
    'QA context does not match the trusted manual run');
  const options = { cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 30_000 };
  requireCondition(git('git', ['rev-parse', 'HEAD'], options).trim() === context.trusted_sha,
    'Helper checkout does not match trusted main');
  requireCondition(git('git', ['rev-parse', context.trusted_sha + '^{tree}'], options).trim() === context.base_tree,
    'Trusted tree differs from context');
  requireCondition(git('git', ['rev-parse', context.trusted_sha + ':' + WORKFLOW], options).trim() === context.workflow.blob_sha,
    'Trusted workflow blob differs from context');
  git('git', ['diff', '--exit-code', context.trusted_sha, '--',
    'mobile/scripts/publish-testflight.cjs', 'mobile/app.json', 'mobile/eas.json', WORKFLOW], options);
  return context;
}

function token(env) {
  const now = Math.floor(Date.now() / 1000);
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const input = encode({ alg: 'ES256', kid: env.CLARIFY_ASC_KEY_ID, typ: 'JWT' }) + '.'
    + encode({ iss: env.CLARIFY_ASC_ISSUER_ID, iat: now, exp: now + 900, aud: 'appstoreconnect-v1' });
  return input + '.' + crypto.sign('sha256', Buffer.from(input), {
    key: env.CLARIFY_ASC_KEY_P8, dsaEncoding: 'ieee-p1363',
  }).toString('base64url');
}

async function publish({ qa = null, env = process.env, fetch = globalThis.fetch,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  log = value => console.log(value), now = () => new Date(), writeReceipt } = {}) {
  if (qa) validateQAContext(qa);
  for (const name of ['CLARIFY_ASC_KEY_ID', 'CLARIFY_ASC_ISSUER_ID', 'CLARIFY_ASC_KEY_P8']) {
    if (!env[name]) throw new Error('Missing configured App Store Connect credential.');
  }
  const selected = qa ? { version: qa.version, build: qa.build, app: APP_ID, notes: QA_NOTES }
    : {
      // Keep configuration reads in the original request and receipt order.
      get version() { return config.version; },
      get build() { return config.ios.buildNumber; },
      app, notes,
    };
  async function request(route, method = 'GET', body) {
    let response;
    try {
      response = await fetch(ORIGIN + route, { method, signal: AbortSignal.timeout(30_000),
        ...(qa ? { redirect: 'error' } : {}),
        headers: { Authorization: 'Bearer ' + token(env), 'Content-Type': 'application/json' },
        ...(body ? { body: JSON.stringify(body) } : {}) });
    } catch (error) {
      if (!qa) throw error;
      throw new Error('Apple request failed; inspect the existing build before retrying.');
    }
    if (!response.ok) {
      if (!qa) {
        const failure = await response.json().catch(() => ({}));
        const detail = (failure.errors || []).map(error => `${error.code}: ${error.detail || error.title}`).join('; ');
        throw new Error(`Apple API ${response.status} for ${method} ${route.split('?')[0]}: ${detail}`);
      }
      // Do not print unknown Apple response bodies, URLs, credentials or fetch errors.
      const status = Number.isInteger(response.status) ? response.status : 'unknown';
      throw new Error('Apple API failed: HTTP ' + status);
    }
    requireCondition(!qa || method !== 'GET' || response.status === 200, 'Unexpected Apple query status');
    if (response.status === 204) return { data: [] };
    if (!qa) return response.json();
    try { return await response.json(); }
    catch { throw new Error('Apple returned an invalid JSON response.'); }
  }
  async function list(route) {
    if (!qa) return request(route); // Preserve stable requests and paging behavior.
    const data = [], included = [], visited = new Set(), identities = new Set();
    const first = new URL(ORIGIN + route);
    const requiredFilters = [...first.searchParams].filter(([key]) => key.startsWith('filter['));
    for (let page = 0; page < 10; page++) {
      requireCondition(!visited.has(route), 'Apple pagination repeated a page');
      visited.add(route);
      const result = await request(route);
      requireCondition(Array.isArray(result.data), 'Apple list data is missing');
      for (const item of result.data) {
        requireCondition(item && typeof item.id === 'string' && item.id.length > 0
          && !identities.has(item.id), 'Duplicate or missing Apple resource identity');
        identities.add(item.id);
      }
      data.push(...result.data);
      included.push(...(result.included || []));
      const next = result.links?.next;
      requireCondition(next === undefined || next === null || (typeof next === 'string' && next.length > 0),
        'Unexpected Apple pagination value');
      if (!next) return { data, included };
      const url = new URL(next, ORIGIN);
      requireCondition(url.origin === first.origin && url.pathname === first.pathname && !url.username
        && !url.password && !url.hash && requiredFilters.every(([key, value]) => url.searchParams.get(key) === value),
        'Unexpected Apple pagination path');
      route = url.pathname.slice('/v1/'.length) + url.search;
    }
    throw new Error('Apple pagination exceeded the safety limit');
  }
  function id(value) {
    if (qa) match(value, /^[0-9A-Za-z_-]{1,128}$/);
    return value;
  }
  const groups = await list('betaGroups?filter[app]=' + selected.app + '&limit=100');
  const matches = qa ? groups.data.filter(item => item.attributes.name === GROUP
    && item.attributes.isInternalGroup === true)
    : [groups.data.find(item => item.attributes.name === GROUP && item.attributes.isInternalGroup)].filter(Boolean);
  if (!matches.length) throw new Error('The existing internal group was not found.');
  requireCondition(!qa || matches.length === 1, 'The existing internal group is ambiguous.');
  const group = matches[0];
  id(group.id);
  let attached = false, selectedBuildId;
  for (let attempt = 0; attempt < 40; attempt++) {
    const result = await list('builds?filter[app]=' + selected.app + '&filter[version]=' + selected.build
      + '&include=preReleaseVersion&limit=10');
    const matchesVersion = item => (!qa || item.attributes.version === selected.build)
      && result.included?.some(version => version.type === 'preReleaseVersions'
        && version.id === item.relationships.preReleaseVersion.data.id && version.attributes.version === selected.version);
    const builds = qa ? result.data.filter(matchesVersion) : [result.data.find(matchesVersion)].filter(Boolean);
    requireCondition(!qa || builds.length <= 1, 'Apple returned ambiguous builds for this identity');
    const build = builds[0];
    if (build) {
      id(build.id);
      if (qa) {
        requireCondition(!selectedBuildId || selectedBuildId === build.id, 'Apple build identity changed during availability');
        selectedBuildId = build.id;
      }
    }
    if (build && ['FAILED', 'INVALID'].includes(build.attributes.processingState)) throw new Error('Apple rejected the uploaded build.');
    if (qa && build) requireCondition(['PROCESSING', 'VALID'].includes(build.attributes.processingState), 'Unknown Apple processing state');
    if (build?.attributes.processingState === 'VALID') {
      if (!attached) {
        const membership = await list('betaGroups/' + group.id + '/builds?limit=100');
        if (!membership.data.some(item => item.id === build.id)) {
          await request('betaGroups/' + group.id + '/relationships/builds', 'POST', { data: [{ type: 'builds', id: build.id }] });
        }
        const localizations = await list('builds/' + build.id + '/betaBuildLocalizations');
        for (const [locale, whatsNew] of Object.entries(selected.notes)) {
          const existing = localizations.data.find(item => item.attributes.locale === locale);
          if (existing) await request('betaBuildLocalizations/' + id(existing.id), 'PATCH',
            { data: { type: 'betaBuildLocalizations', id: existing.id, attributes: { whatsNew } } });
          else await request('betaBuildLocalizations', 'POST',
            { data: { type: 'betaBuildLocalizations', attributes: { locale, whatsNew },
              relationships: { build: { data: { type: 'builds', id: build.id } } } } });
        }
        attached = true;
      }
      const [detail, membership, testers] = await Promise.all([
        request('builds/' + build.id + '/buildBetaDetail'),
        list('betaGroups/' + group.id + '/builds?limit=100'),
        list('betaGroups/' + group.id + '/relationships/betaTesters?limit=200'),
      ]);
      if (detail.data.attributes.internalBuildState === 'IN_BETA_TESTING'
          && membership.data.some(item => item.id === build.id) && testers.data.length > 0) {
        const evidence = { checkedAt: now().toISOString(), id: build.id, version: selected.version,
          build: selected.build, processing: 'VALID', internalState: 'IN_BETA_TESTING',
          group: GROUP, availableInGroup: true, existingTesters: testers.data.length };
        if (qa) Object.assign(evidence, { qa, appId: APP_ID, team: '8K353P3496', ipaVerifiedByThisHelper: false,
          bundleDigestsVerifiedByThisHelper: false, workflowArtifactProvenanceVerified: false });
        if (writeReceipt) writeReceipt(evidence);
        else {
          const output = qa ? safeQAPath(path.join(env.RUNNER_TEMP, 'clarify-ios-qa/output/testflight-availability.json'),
            'output/testflight-availability.json', env, false) : path.join('test-results', 'testflight-availability.json');
          fs.mkdirSync(path.dirname(output), { recursive: true });
          fs.writeFileSync(output, JSON.stringify(evidence, null, 2));
        }
        log(JSON.stringify(evidence));
        return evidence;
      }
    }
    const state = qa ? (['PROCESSING', 'VALID', 'FAILED', 'INVALID'].includes(build?.attributes.processingState)
      ? build.attributes.processingState : build ? 'UNKNOWN' : 'NOT_VISIBLE')
      : build?.attributes.processingState || 'NOT_VISIBLE';
    log(JSON.stringify({ version: selected.version, build: selected.build, processing: state }));
    await sleep(30_000);
  }
  throw new Error('Apple processing or internal TestFlight availability is still pending.');
}

async function main(argv = process.argv.slice(2), dependencies = {}) {
  const useQA = argv.includes('--qa-context');
  requireCondition(!useQA || (argv.length === 2 && argv[0] === '--qa-context'),
    'Use [--qa-context ABS_JSON]');
  const env = dependencies.env || process.env;
  const qa = useQA ? loadQAContext(argv[1], { env, git: dependencies.git || execFileSync }) : null;
  if (qa) safeQAPath(path.join(env.RUNNER_TEMP, 'clarify-ios-qa/output/testflight-availability.json'),
    'output/testflight-availability.json', env, false);
  return publish({ ...dependencies, qa, env });
}

module.exports = { main, publish, loadQAContext, validateQAContext, decodeContext, QA_NOTES };
if (require.main === module) {
  main().catch(error => {
    const safeMessages = new Set(['Missing configured App Store Connect credential.',
      'The existing internal group was not found.', 'Apple rejected the uploaded build.',
      'Apple processing or internal TestFlight availability is still pending.']);
    console.error(!process.argv.slice(2).includes('--qa-context') || safeMessages.has(error.message) ? error.message
      : 'Internal TestFlight availability failed. Inspect the existing build before retrying.');
    process.exitCode = 1;
  });
}
