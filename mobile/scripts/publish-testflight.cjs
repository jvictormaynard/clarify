const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const config = require('../app.json').expo;
const ORIGIN = 'https://api.appstoreconnect.apple.com/v1/';
const APP_ID = '6820869157';
const GROUP = 'Clarify Interno';

function requireCondition(value, message) {
  if (!value) throw new Error(message);
}

function releaseNotes(version, build) {
  return {
    'pt-BR': `Teste interno do Clarify ${version} (${build}). Consulte o relat\u00f3rio de valida\u00e7\u00e3o desta vers\u00e3o.`,
    'en-US': `Internal test of Clarify ${version} (${build}). See this build's validation report.`,
    'es-ES': `Prueba interna de Clarify ${version} (${build}). Consulte el informe de validaci\u00f3n de esta versi\u00f3n.`,
  };
}

function token(env) {
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const now = Math.floor(Date.now() / 1000);
  const input = encode({ alg: 'ES256', kid: env.CLARIFY_ASC_KEY_ID, typ: 'JWT' }) + '.'
    + encode({ iss: env.CLARIFY_ASC_ISSUER_ID, iat: now, exp: now + 900, aud: 'appstoreconnect-v1' });
  return input + '.' + crypto.sign('sha256', Buffer.from(input), {
    key: env.CLARIFY_ASC_KEY_P8, dsaEncoding: 'ieee-p1363',
  }).toString('base64url');
}

async function publish({ env = process.env, fetch = globalThis.fetch,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  log = value => console.log(value), now = () => new Date(), writeReceipt } = {}) {
  for (const name of ['CLARIFY_ASC_KEY_ID', 'CLARIFY_ASC_ISSUER_ID', 'CLARIFY_ASC_KEY_P8']) {
    requireCondition(env[name], 'Missing configured App Store Connect credential.');
  }
  async function request(route, method = 'GET', body) {
    const url = new URL(route, ORIGIN);
    requireCondition(url.origin === new URL(ORIGIN).origin && url.pathname.startsWith('/v1/')
      && !url.username && !url.password && !url.hash, 'Unexpected Apple API path');
    const response = await fetch(url.href, {
      method, redirect: 'error', signal: AbortSignal.timeout(30_000),
      headers: { Authorization: 'Bearer ' + token(env), 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      const failure = await response.json();
      const detail = (failure.errors || []).map(item => [item.code, item.detail || item.title].filter(Boolean).join(': ')).join('; ');
      throw new Error(`Apple API ${response.status} for ${method} ${route.split('?')[0]}: ${detail}`);
    }
    return response.status === 204 ? { data: [] } : response.json();
  }
  async function list(route) {
    const data = [], included = [], visited = new Set(), identities = new Set();
    const first = new URL(route, ORIGIN);
    const filters = [...first.searchParams].filter(([key]) => key.startsWith('filter['));
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
      requireCondition(next === undefined || next === null || (typeof next === 'string' && next.length > 0), 'Unexpected Apple pagination value');
      if (!next) return { data, included };
      const url = new URL(next, ORIGIN);
      requireCondition(url.origin === first.origin && url.pathname === first.pathname && !url.username
        && !url.password && !url.hash && filters.every(([key, value]) => url.searchParams.get(key) === value), 'Unexpected Apple pagination path');
      route = url.pathname.slice('/v1/'.length) + url.search;
    }
    throw new Error('Apple pagination exceeded the safety limit');
  }
  function id(value) {
    requireCondition(typeof value === 'string' && /^[0-9A-Za-z_-]{1,128}$/.test(value), 'Unexpected Apple resource identity');
    return value;
  }
  const groups = await list('betaGroups?filter[app]=' + APP_ID + '&limit=100');
  const matches = groups.data.filter(item => item.attributes?.name === GROUP && item.attributes.isInternalGroup === true);
  requireCondition(matches.length > 0, 'The existing internal group was not found.');
  requireCondition(matches.length === 1, 'The existing internal group is ambiguous.');
  const group = matches[0];
  id(group.id);
  // Read the configured build only after the existing group has been checked.
  const selected = { version: config.version, build: config.ios.buildNumber };
  let attached = false, selectedBuildId;
  for (let attempt = 0; attempt < 40; attempt++) {
    const result = await list('builds?filter[app]=' + APP_ID + '&filter[version]=' + selected.build + '&include=preReleaseVersion&limit=10');
    const builds = result.data.filter(item => item.attributes?.version === selected.build
      && result.included.some(version => version.type === 'preReleaseVersions'
        && version.id === item.relationships?.preReleaseVersion?.data?.id && version.attributes?.version === selected.version));
    requireCondition(builds.length <= 1, 'Apple returned ambiguous builds for this identity');
    const build = builds[0];
    if (build) {
      id(build.id);
      requireCondition(!selectedBuildId || selectedBuildId === build.id, 'Apple build identity changed during availability');
      selectedBuildId = build.id;
    }
    if (build && ['FAILED', 'INVALID'].includes(build.attributes.processingState)) throw new Error('Apple rejected the uploaded build.');
    if (build?.attributes.processingState === 'VALID') {
      if (!attached) {
        const membership = await list('betaGroups/' + group.id + '/builds?limit=100');
        if (!membership.data.some(item => item.id === build.id)) {
          await request('betaGroups/' + group.id + '/relationships/builds', 'POST', { data: [{ type: 'builds', id: build.id }] });
        }
        const localizations = await list('builds/' + build.id + '/betaBuildLocalizations');
        for (const [locale, whatsNew] of Object.entries(releaseNotes(selected.version, selected.build))) {
          const existing = localizations.data.find(item => item.attributes?.locale === locale);
          if (existing) await request('betaBuildLocalizations/' + id(existing.id), 'PATCH', {
            data: { type: 'betaBuildLocalizations', id: existing.id, attributes: { whatsNew } },
          });
          else await request('betaBuildLocalizations', 'POST', {
            data: { type: 'betaBuildLocalizations', attributes: { locale, whatsNew },
              relationships: { build: { data: { type: 'builds', id: build.id } } } },
          });
        }
        attached = true;
      }
      const [detail, membership, testers] = await Promise.all([
        request('builds/' + build.id + '/buildBetaDetail'),
        list('betaGroups/' + group.id + '/builds?limit=100'),
        list('betaGroups/' + group.id + '/relationships/betaTesters?limit=200'),
      ]);
      if (detail.data?.attributes?.internalBuildState === 'IN_BETA_TESTING'
          && membership.data.some(item => item.id === build.id) && testers.data.length > 0) {
        const evidence = { checkedAt: now().toISOString(), id: build.id, version: selected.version,
          build: selected.build, processing: 'VALID', internalState: 'IN_BETA_TESTING',
          group: GROUP, availableInGroup: true, existingTesters: testers.data.length };
        if (writeReceipt) writeReceipt(evidence);
        else {
          const output = path.join(__dirname, '../test-results/testflight-availability.json');
          fs.mkdirSync(path.dirname(output), { recursive: true });
          fs.writeFileSync(output, JSON.stringify(evidence, null, 2) + '\n');
        }
        log(JSON.stringify(evidence));
        return evidence;
      }
    }
    log(JSON.stringify({ version: selected.version, build: selected.build, processing: build?.attributes.processingState || 'NOT_VISIBLE' }));
    await sleep(30_000);
  }
  throw new Error('Apple processing or internal TestFlight availability is still pending.');
}

async function main(args = process.argv.slice(2), dependencies = {}) {
  requireCondition(args.length === 0, 'Use publish-testflight.cjs without arguments');
  return publish(dependencies);
}

module.exports = { main, publish, releaseNotes };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
