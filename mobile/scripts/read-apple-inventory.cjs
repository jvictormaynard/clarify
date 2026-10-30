'use strict';

const { createHash, createPrivateKey, sign } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const ORIGIN = 'https://api.appstoreconnect.apple.com';
const APP = '6820869157';
const WORKFLOW = 'jvictormaynard/clarify/.github/workflows/ios-testflight.yml';
const DEFAULT_LIMITS = Object.freeze({
  maxPages: 200,
  maxPagesPerCollection: 100,
  maxResponseBytes: 2 * 1024 ** 2,
  maxTotalBytes: 32 * 1024 ** 2,
  maxRecords: 20000,
  requestTimeoutMs: 15000,
  maxDurationMs: 180000,
});

class InventoryError extends Error {}
function requireCondition(condition, message) {
  if (!condition) throw new InventoryError(message);
}
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const nonempty = value => typeof value === 'string' && value.length > 0;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

function checkResource(value, type) {
  requireCondition(object(value) && typeof value.id === 'string' && /^[A-Za-z0-9-]{1,128}$/.test(value.id)
    && nonempty(value.type) && (!type || value.type === type), 'Invalid Apple resource');
  if (!type || type === 'betaTesters') return;
  const attributes = value.attributes;
  requireCondition(object(attributes), 'Missing Apple resource attributes');
  const fields = {
    builds: ['version', 'processingState'],
    buildUploads: ['cfBundleShortVersionString', 'cfBundleVersion'],
    appStoreVersions: ['versionString'],
    reviewSubmissions: ['state'],
    reviewSubmissionItems: ['state'],
    betaAppReviewSubmissions: ['betaReviewState'],
    betaGroups: ['name'],
  }[type] || [];
  requireCondition(fields.every(field => nonempty(attributes[field])), 'Incomplete Apple resource attributes');
  if (type === 'buildUploads') requireCondition(object(attributes.state) && nonempty(attributes.state.state), 'Missing build upload state');
  if (type === 'appStoreVersions') requireCondition(nonempty(attributes.appStoreState)
    || nonempty(attributes.appVersionState), 'Missing App Store version state');
  if (type === 'betaGroups') requireCondition(typeof attributes.isInternalGroup === 'boolean', 'Missing group type');
}

function pageURL(address, root) {
  requireCondition(typeof address === 'string' && address.length <= 8192
    && !/[\s\\\u0000-\u001f\u007f]/.test(address), 'Invalid pagination URL');
  let url;
  try { url = new URL(address, root); } catch { throw new InventoryError('Invalid pagination URL'); }
  requireCondition(url.origin === ORIGIN && !url.username && !url.password && !url.hash
    && url.pathname === root.pathname, 'Unsafe pagination origin or resource');
  const names = [...url.searchParams.keys()];
  requireCondition(new Set(names).size === names.length
    && names.every(name => name === 'cursor' || root.searchParams.has(name))
    && [...root.searchParams].every(([name, value]) => url.searchParams.get(name) === value),
  'Pagination changed the original query');
  if (url.searchParams.has('cursor')) requireCondition(nonempty(url.searchParams.get('cursor'))
    && url.searchParams.get('cursor').length <= 2048, 'Invalid pagination cursor');
  url.searchParams.sort();
  return url;
}

function bind(report, env) {
  requireCondition(env.GITHUB_REPOSITORY === 'jvictormaynard/clarify'
    && /^[a-f0-9]{40}$/.test(env.GITHUB_SHA) && /^[a-f0-9]{40}$/.test(env.GITHUB_WORKFLOW_SHA)
    && /^refs\/(heads|tags)\/[^\s\u0000-\u001f]{1,200}$/.test(env.GITHUB_REF)
    && env.GITHUB_WORKFLOW_REF === `${WORKFLOW}@${env.GITHUB_REF}`
    && /^[1-9][0-9]{0,19}$/.test(env.GITHUB_RUN_ID) && /^[1-9][0-9]{0,5}$/.test(env.GITHUB_RUN_ATTEMPT),
  'Invalid GitHub source or run binding');
  Object.assign(report, {
    repository: env.GITHUB_REPOSITORY,
    source_sha: env.GITHUB_SHA,
    source_ref: env.GITHUB_REF,
    workflow_ref: env.GITHUB_WORKFLOW_REF,
    workflow_sha: env.GITHUB_WORKFLOW_SHA,
    run_id: env.GITHUB_RUN_ID,
    run_attempt: env.GITHUB_RUN_ATTEMPT,
    attempt_url: `https://github.com/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}/attempts/${env.GITHUB_RUN_ATTEMPT}`,
    collector_sha256: hash(fs.readFileSync(__filename)),
  });
}

function jwt(env, date) {
  requireCondition(typeof env.ASC_KEY === 'string' && env.ASC_KEY.length <= 16384
    && nonempty(env.ASC_KEY_ID) && /^[A-Za-z0-9]{1,32}$/.test(env.ASC_KEY_ID)
    && /^[a-fA-F0-9-]{36}$/.test(env.ASC_ISSUER), 'Missing or invalid Apple credentials');
  try {
    const key = createPrivateKey(env.ASC_KEY);
    requireCondition(key.asymmetricKeyType === 'ec'
      && key.asymmetricKeyDetails.namedCurve === 'prime256v1', 'Apple key must use P-256');
    const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
    const now = Math.floor(date.getTime() / 1000);
    const body = `${encode({ alg: 'ES256', kid: env.ASC_KEY_ID, typ: 'JWT' })}.${encode({
      iss: env.ASC_ISSUER, iat: now, exp: now + 300, aud: 'appstoreconnect-v1',
    })}`;
    return `${body}.${sign('sha256', Buffer.from(body), { key, dsaEncoding: 'ieee-p1363' }).toString('base64url')}`;
  } catch { throw new InventoryError('Cannot sign inventory JWT with the supplied Apple key'); }
}

// Official endpoint/schema reference: https://developer.apple.com/documentation/appstoreconnectapi
// No writes, retries, number selection, or external/Git reservation claims belong here.
async function collectInventory({ env = process.env, transport = globalThis.fetch,
  clock = () => new Date(), limits: overrides = {} } = {}) {
  const report = {
    schema: 1, app: APP, method: 'GET', started_at: clock().toISOString(), complete: false,
    number_availability: 'Not determined. Git and external reservations require separate checks.',
    collections: {}, queries: [], appStoreVersionBuilds: [], errors: [],
  };
  let current = 'setup';
  const started = performance.now();
  let bytes = 0;
  let records = 0;
  try {
    for (const [name, value] of Object.entries(overrides)) requireCondition(name in DEFAULT_LIMITS
      && Number.isSafeInteger(value) && value > 0 && value <= DEFAULT_LIMITS[name], 'Invalid inventory limits');
    const limits = { ...DEFAULT_LIMITS, ...overrides };
    report.limits = limits;
    bind(report, env);
    const token = jwt(env, clock());

    async function get(url, collection, page) {
      requireCondition(report.queries.length < limits.maxPages, 'Inventory page bound reached');
      const remaining = limits.maxDurationMs - (performance.now() - started);
      requireCondition(remaining > 0, 'Inventory time bound reached');
      const query = { collection, page, url: url.href, method: 'GET', started_at: clock().toISOString(),
        status: null, bytes: 0, sha256: null, body_complete: false };
      report.queries.push(query);
      try {
        const signal = AbortSignal.timeout(Math.ceil(Math.min(remaining, limits.requestTimeoutMs)));
        const response = await transport(url.href, {
          method: 'GET', redirect: 'error', signal,
          headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        });
        query.status = response.status;
        const chunks = [];
        if (response.body) for await (const chunk of response.body) {
          signal.throwIfAborted();
          query.bytes += chunk.byteLength;
          bytes += chunk.byteLength;
          requireCondition(query.bytes <= limits.maxResponseBytes, 'Apple response byte bound reached');
          requireCondition(bytes <= limits.maxTotalBytes, 'Inventory total byte bound reached');
          chunks.push(Buffer.from(chunk));
        }
        signal.throwIfAborted();
        const raw = Buffer.concat(chunks);
        query.sha256 = hash(raw);
        query.body_complete = true;
        requireCondition(response.status === 200, `Apple GET failed: HTTP ${response.status}`);
        let document;
        try { document = JSON.parse(raw.toString('utf8')); } catch { throw new InventoryError('Invalid Apple JSON response'); }
        requireCondition(object(document) && !Object.hasOwn(document, 'errors')
          && Object.hasOwn(document, 'data') && object(document.links)
          && nonempty(document.links.self), 'Incomplete Apple response document');
        requireCondition(document.included === undefined || Array.isArray(document.included), 'Invalid included resources');
        for (const item of document.included || []) checkResource(item);
        query.links = document.links;
        query.meta = document.meta;
        return document;
      } catch (error) {
        // Transport/crypto/parser errors can contain input, headers or keys. Never retain them.
        throw error instanceof InventoryError ? error : new InventoryError('Apple GET or response read failed');
      } finally { query.finished_at = clock().toISOString(); }
    }

    function rootURL(endpoint, params) {
      const url = new URL(endpoint, ORIGIN);
      url.search = new URLSearchParams(params).toString();
      return pageURL(url.href, url);
    }

    async function collect(name, endpoint, type, params = { limit: '200' }, single = false) {
      current = name;
      const root = rootURL(endpoint, params);
      const collection = { url: root.href, complete: false, data: single ? null : [], included: [], pages: [] };
      report.collections[name] = collection;
      let url = root;
      let total;
      const cursors = new Set();
      const identities = new Set();
      do {
        requireCondition(collection.pages.length < limits.maxPagesPerCollection, 'Collection page bound reached');
        const cursor = url.searchParams.get('cursor') || '';
        requireCondition(!cursors.has(cursor), 'Repeated pagination cursor');
        cursors.add(cursor);
        const index = report.queries.length;
        let document;
        try { document = await get(url, name, collection.pages.length + 1); }
        finally { if (report.queries.length > index) collection.pages.push(index); }
        collection.included.push(...(document.included || []));
        records += (Array.isArray(document.data) ? document.data.length : document.data === null ? 0 : 1)
          + (document.included || []).length;
        requireCondition(records <= limits.maxRecords, 'Inventory record bound reached');
        if (single) {
          requireCondition(document.data === null || object(document.data), 'Invalid selected-build response');
          requireCondition(!document.links.next, 'Unexpected selected-build pagination');
          if (document.data !== null) checkResource(document.data, type);
          collection.data = document.data;
          break;
        }
        requireCondition(Array.isArray(document.data), 'Missing Apple collection data');
        const paging = document.meta?.paging;
        requireCondition(object(paging) && Number.isSafeInteger(paging.total) && paging.total >= 0
          && paging.total <= limits.maxRecords && Number.isSafeInteger(paging.limit)
          && paging.limit >= 0 && paging.limit <= 200 && document.data.length <= paging.limit,
        'Missing or invalid Apple paging total/limit');
        if (total === undefined) total = paging.total;
        requireCondition(total === paging.total, 'Apple paging total changed during collection');
        for (const item of document.data) {
          checkResource(item, type);
          requireCondition(!identities.has(item.id), 'Duplicate Apple resource across pages');
          identities.add(item.id);
          collection.data.push(item);
        }
        requireCondition(collection.data.length <= total, 'Apple paging total mismatch');
        const next = document.links.next;
        const nextCursor = paging.nextCursor;
        requireCondition(nextCursor === undefined || nextCursor === null || (nonempty(nextCursor) && nonempty(next)),
          'Incomplete pagination cursor metadata');
        if (next === undefined || next === null) {
          requireCondition(collection.data.length === total, 'Incomplete Apple pagination total');
          url = null;
        } else {
          requireCondition(nonempty(next) && document.data.length > 0 && collection.data.length < total,
            'Inconsistent Apple pagination link');
          url = pageURL(next, root);
          requireCondition(url.searchParams.has('cursor'), 'Missing pagination cursor');
          if (nextCursor != null) requireCondition(url.searchParams.get('cursor') === nextCursor, 'Pagination cursor mismatch');
        }
      } while (url);
      collection.total = single ? (collection.data === null ? 0 : 1) : total;
      collection.complete = true;
      return collection.data;
    }

    const builds = await collect('builds', '/v1/builds', 'builds', {
      'filter[app]': APP, limit: '200', include: 'preReleaseVersion,buildBetaDetail',
    });
    await collect('uploads', `/v1/apps/${APP}/buildUploads`, 'buildUploads', { limit: '200', include: 'build' });
    const versions = await collect('appStoreVersions', `/v1/apps/${APP}/appStoreVersions`, 'appStoreVersions', {
      limit: '200', include: 'build,appStoreVersionSubmission',
    });
    const submissions = await collect('reviewSubmissions', `/v1/apps/${APP}/reviewSubmissions`, 'reviewSubmissions', {
      limit: '200', include: 'appStoreVersionForReview',
    });
    for (const submission of submissions) await collect(`reviewItems:${submission.id}`,
      `/v1/reviewSubmissions/${submission.id}/items`, 'reviewSubmissionItems', { limit: '200', include: 'appStoreVersion' });
    report.beta_review_builds_checked = builds.map(build => build.id);
    for (let offset = 0; offset < builds.length; offset += 50) await collect(`betaReviews:${offset / 50}`,
      '/v1/betaAppReviewSubmissions', 'betaAppReviewSubmissions', {
        'filter[build]': builds.slice(offset, offset + 50).map(build => build.id).join(','), limit: '200', include: 'build',
      });
    const groups = await collect('groups', '/v1/betaGroups', 'betaGroups', { 'filter[app]': APP, limit: '200' });
    for (const group of groups) {
      await collect(`groupBuilds:${group.id}`, `/v1/betaGroups/${group.id}/builds`, 'builds');
      // Relationship IDs give the complete tester count without names or email addresses.
      await collect(`groupTesters:${group.id}`, `/v1/betaGroups/${group.id}/relationships/betaTesters`, 'betaTesters');
    }
    for (const version of versions) {
      const selected = await collect(`versionBuild:${version.id}`, `/v1/appStoreVersions/${version.id}/build`, 'builds', {}, true);
      const inline = version.relationships?.build;
      requireCondition(!inline || !Object.hasOwn(inline, 'data') || inline.data?.id === selected?.id,
        'Selected build changed during inventory');
      requireCondition(selected === null || builds.some(build => build.id === selected.id), 'Selected build missing from full build inventory');
      report.appStoreVersionBuilds.push({ version_id: version.id, build: selected });
    }
    requireCondition(performance.now() - started < limits.maxDurationMs, 'Inventory time bound reached');
    report.complete = true;
  } catch (error) {
    if (report.collections[current]) report.collections[current].complete = false;
    report.errors.push({ collection: current, message: error instanceof InventoryError ? error.message : 'Inventory collection failed' });
  }
  report.finished_at = clock().toISOString();
  return report;
}

async function main() {
  try {
    requireCondition(process.argv.length === 3 && path.isAbsolute(process.argv[2]), 'An absolute evidence output path is required');
    const report = await collectInventory();
    fs.writeFileSync(process.argv[2], JSON.stringify(report, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    console.log(`Apple inventory complete: ${report.complete}. Evidence written.`);
    if (!report.complete) {
      for (const error of report.errors) console.error(`${error.collection}: ${error.message}`);
      process.exitCode = 1;
    }
  } catch { console.error('Cannot collect or write Apple inventory evidence.'); process.exitCode = 1; }
}

if (require.main === module) main();
module.exports = { collectInventory };
