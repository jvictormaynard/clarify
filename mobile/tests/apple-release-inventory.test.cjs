'use strict';

const assert = require('node:assert/strict');
const { createHash, generateKeyPairSync, verify } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { test } = require('node:test');
const { collectInventory } = require('../scripts/read-apple-inventory.cjs');

const ORIGIN = 'https://api.appstoreconnect.apple.com';
const APP = '/v1/apps/6820869157';
const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
const env = {
  ASC_KEY: privateKey.export({ type: 'pkcs8', format: 'pem' }),
  ASC_KEY_ID: 'TESTKEY123',
  ASC_ISSUER: '00000000-0000-4000-8000-000000000000',
  GITHUB_REPOSITORY: 'jvictormaynard/clarify',
  GITHUB_SHA: 'b'.repeat(40),
  GITHUB_REF: 'refs/heads/t3/apple-release-inventory',
  GITHUB_WORKFLOW_REF: 'jvictormaynard/clarify/.github/workflows/ios-testflight.yml@refs/heads/t3/apple-release-inventory',
  GITHUB_WORKFLOW_SHA: 'b'.repeat(40),
  GITHUB_RUN_ID: '40986690898',
  GITHUB_RUN_ATTEMPT: '2',
};
const clock = () => new Date('2026-10-30T03:00:00Z');
const resource = (type, id, attributes = {}) => ({ type, id, attributes });
const build = id => resource('builds', id, { version: id.slice(1), processingState: 'VALID' });
const builds = Array.from({ length: 12 }, (_, i) => build(`b${i + 1}`));
const uploads = builds.map(b => resource('buildUploads', `u${b.id}`, {
  cfBundleShortVersionString: '0.11.0', cfBundleVersion: b.attributes.version,
  state: { state: 'COMPLETE', errors: [], warnings: [] },
}));

function fixture() {
  const calls = [];
  const bodies = [];
  const routes = new Map();
  function pages(path, chunks, included = []) {
    chunks.forEach((data, index) => routes.set(`${path}:${index ? `p${index}` : ''}`, url => {
      const next = new URL(url);
      next.searchParams.set('cursor', `p${index + 1}`);
      return {
        data, included,
        links: { self: url.href, next: index + 1 < chunks.length ? next.href : null },
        meta: { paging: { total: chunks.flat().length, limit: 200 } },
      };
    }));
  }
  pages('/v1/builds', [builds.slice(0, 10), builds.slice(10)], [resource('preReleaseVersions', 'pr1', { version: '0.11.0' })]);
  pages(`${APP}/buildUploads`, [uploads.slice(0, 6), uploads.slice(6)]);
  const versions = [resource('appStoreVersions', 'v1', { versionString: '0.11.0', appStoreState: 'WAITING_FOR_REVIEW' }),
    resource('appStoreVersions', 'v2', { versionString: '0.12.0', appStoreState: 'PREPARE_FOR_SUBMISSION' })];
  versions[0].relationships = { build: { data: { type: 'builds', id: 'b12' } } };
  versions[1].relationships = { build: { data: null } };
  pages(`${APP}/appStoreVersions`, [versions.slice(0, 1), versions.slice(1)]);
  routes.set('/v1/appStoreVersions/v1/build:', url => ({ data: builds[11], links: { self: url.href } }));
  routes.set('/v1/appStoreVersions/v2/build:', url => ({ data: null, links: { self: url.href } }));
  pages(`${APP}/reviewSubmissions`, [[resource('reviewSubmissions', 'r1', { state: 'WAITING_FOR_REVIEW' })],
    [resource('reviewSubmissions', 'r2', { state: 'COMPLETE' })]]);
  pages('/v1/reviewSubmissions/r1/items', [[resource('reviewSubmissionItems', 'ri1', { state: 'READY_FOR_REVIEW' })],
    [resource('reviewSubmissionItems', 'ri2', { state: 'ACCEPTED' })]], [versions[0]]);
  pages('/v1/reviewSubmissions/r2/items', [[]]);
  pages('/v1/betaAppReviewSubmissions', [[resource('betaAppReviewSubmissions', 'br1', { betaReviewState: 'IN_REVIEW' })],
    [resource('betaAppReviewSubmissions', 'br2', { betaReviewState: 'APPROVED' })]]);
  pages('/v1/betaGroups', [[resource('betaGroups', 'g1', { name: 'Internal', isInternalGroup: true })],
    [resource('betaGroups', 'g2', { name: 'External', isInternalGroup: false })]]);
  pages('/v1/betaGroups/g1/builds', [builds.slice(0, 10), builds.slice(10)]);
  pages('/v1/betaGroups/g2/builds', [[]]);
  pages('/v1/betaGroups/g1/relationships/betaTesters', [[{ type: 'betaTesters', id: 't1' }], [{ type: 'betaTesters', id: 't2' }]]);
  pages('/v1/betaGroups/g2/relationships/betaTesters', [[]]);
  const transport = async (address, options) => {
    const url = new URL(address);
    calls.push({ url, options });
    const handler = routes.get(`${url.pathname}:${url.searchParams.get('cursor') || ''}`);
    assert.ok(handler, 'Unexpected endpoint');
    const body = JSON.stringify(handler(url));
    bodies.push(body);
    return new Response(body, { headers: { 'Content-Type': 'application/json' } });
  };
  return { calls, bodies, routes, transport };
}

test('collects every page and binds complete evidence, selected builds, reviews and groups', async () => {
  const fake = fixture();
  const report = await collectInventory({ env, clock, transport: fake.transport });
  assert.equal(report.complete, true, JSON.stringify(report.errors));
  assert.equal(report.source_sha, env.GITHUB_SHA);
  assert.equal(report.workflow_sha, env.GITHUB_WORKFLOW_SHA);
  assert.equal(report.run_id, env.GITHUB_RUN_ID);
  assert.equal(report.run_attempt, '2');
  assert.equal(report.started_at, clock().toISOString());
  assert.equal(report.finished_at, clock().toISOString());
  assert.match(report.collector_sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(report.collections.builds.data, builds);
  assert.deepEqual(report.collections.uploads.data, uploads);
  assert.equal(report.collections.builds.included.length, 2);
  assert.equal(report.collections.appStoreVersions.data.length, 2);
  assert.deepEqual(report.appStoreVersionBuilds, [{ version_id: 'v1', build: builds[11] }, { version_id: 'v2', build: null }]);
  assert.equal(report.collections.reviewSubmissions.data[0].attributes.state, 'WAITING_FOR_REVIEW');
  assert.equal(report.collections['reviewItems:r1'].data.length, 2);
  assert.equal(report.collections['betaReviews:0'].data.length, 2);
  assert.equal(report.collections['groupBuilds:g1'].data.length, 12);
  assert.equal(report.collections['groupTesters:g1'].data.length, 2);
  assert.equal(report.collections.groups.data.length, 2);
  assert.ok(Object.values(report.collections).every(c => c.complete));
  assert.equal(report.queries.length, fake.calls.length);
  report.queries.forEach((q, index) => {
    assert.equal(q.method, 'GET');
    assert.equal(q.status, 200);
    assert.equal(q.url, fake.calls[index].url.href);
    assert.equal(q.sha256, createHash('sha256').update(fake.bodies[index]).digest('hex'));
    assert.equal(q.bytes, Buffer.byteLength(fake.bodies[index]));
  });
  for (const { url, options } of fake.calls) {
    assert.equal(url.origin, ORIGIN);
    assert.equal(options.method, 'GET');
    assert.equal(options.redirect, 'error');
    assert.equal(options.body, undefined);
    const token = options.headers.Authorization.slice('Bearer '.length);
    const [head, payload, signature] = token.split('.');
    assert.equal(verify('sha256', Buffer.from(`${head}.${payload}`),
      { key: publicKey, dsaEncoding: 'ieee-p1363' }, Buffer.from(signature, 'base64url')), true);
    const claims = JSON.parse(Buffer.from(payload, 'base64url'));
    assert.equal(claims.exp - claims.iat, 300);
    assert.equal(claims.aud, 'appstoreconnect-v1');
    assert.ok(!JSON.stringify(report).includes(token));
  }
  assert.ok(!JSON.stringify(report).includes(env.ASC_KEY));
  assert.equal(report.number_availability, 'Not determined. Git and external reservations require separate checks.');
  const beforeSelectedBuilds = Object.entries(report.collections)
    .filter(([name]) => !name.startsWith('versionBuild:'))
    .reduce((count, [, collection]) => count + collection.data.length + collection.included.length, 0);
  const bounded = await collectInventory({ env, clock, transport: fixture().transport,
    limits: { maxRecords: beforeSelectedBuilds } });
  assert.equal(bounded.complete, false);
  assert.equal(bounded.errors[0].collection, 'versionBuild:v1');
  assert.equal(bounded.errors[0].message, 'Inventory record bound reached');
});

test('rejects pagination outside its origin, resource or original query before forwarding auth', async () => {
  for (const next of [
    'https://example.com/v1/builds?cursor=p1',
    'http://api.appstoreconnect.apple.com/v1/builds?cursor=p1',
    'https://user@api.appstoreconnect.apple.com/v1/builds?cursor=p1',
    'https://api.appstoreconnect.apple.com:8443/v1/builds?cursor=p1',
    `${ORIGIN}/v1/apps/other/builds?cursor=p1`,
    `${ORIGIN}/v1/builds?filter[app]=other&limit=200&cursor=p1`,
  ]) {
    const fake = fixture();
    const first = fake.routes.get('/v1/builds:');
    fake.routes.set('/v1/builds:', url => ({ ...first(url), links: { self: url.href, next } }));
    const report = await collectInventory({ env, clock, transport: fake.transport });
    assert.equal(report.complete, false);
    assert.equal(fake.calls.length, 1);
    assert.equal(report.collections.builds.complete, false);
    assert.match(report.errors[0].message, /pagination/i);
  }
});

test('fails closed on HTTP, schema, incomplete pagination, repeated cursors and collection bounds', async () => {
  const scenarios = [
    ['HTTP 403', f => { f.transport = async () => new Response('private error body', { status: 403 }); }],
    ['HTTP 302', f => { f.transport = async () => new Response('', { status: 302, headers: { Location: 'https://example.com' } }); }],
    ['Missing data', f => { f.routes.set('/v1/builds:', url => ({ links: { self: url.href }, meta: { paging: { total: 0, limit: 200 } } })); }],
    ['Missing total', f => { f.routes.set('/v1/builds:', url => ({ data: [], links: { self: url.href } })); }],
    ['Missing resource ID', f => { const first = f.routes.get('/v1/builds:'); f.routes.set('/v1/builds:', url => {
      const doc = first(url); doc.data = [{ type: 'builds', attributes: { version: '1', processingState: 'VALID' } }]; return doc;
    }); }],
    ['Incomplete total', f => { const first = f.routes.get('/v1/builds:'); f.routes.set('/v1/builds:', url => ({ ...first(url), links: { self: url.href } })); }],
    ['Orphan cursor', f => { f.routes.set('/v1/builds:', url => ({ data: [], links: { self: url.href }, meta: { paging: { total: 0, limit: 200, nextCursor: 'p1' } } })); }],
    ['Repeated cursor', f => { const first = f.routes.get('/v1/builds:'); f.routes.set('/v1/builds:p1', url => ({ ...first(url), data: [build('b13')] })); }],
    ['Duplicate records', f => { const first = f.routes.get('/v1/builds:'); f.routes.set('/v1/builds:p1', url => ({ ...first(url), links: { self: url.href } })); }],
    ['Page bound', () => {}, { maxPages: 1 }],
    ['Collection page bound', () => {}, { maxPagesPerCollection: 1 }],
    ['Response bound', () => {}, { maxResponseBytes: 64 }],
    ['Total byte bound', () => {}, { maxTotalBytes: 3000 }],
    ['Later resource unavailable', f => { const original = f.transport; f.transport = (url, options) => new URL(url).pathname === `${APP}/buildUploads`
      ? Promise.resolve(new Response('unavailable', { status: 503 })) : original(url, options); }],
    ['Upload state missing', f => { for (const cursor of ['', 'p1']) {
      const route = `${APP}/buildUploads:${cursor}`;
      const original = f.routes.get(route);
      f.routes.set(route, url => { const doc = original(url); return { ...doc,
        data: doc.data.map(item => ({ ...item, attributes: { ...item.attributes, state: {} } })),
      }; });
    } }],
    ['Selected build changed', f => { f.routes.set('/v1/appStoreVersions/v1/build:', url => ({ data: builds[0], links: { self: url.href } })); }],
    ['Selected build unavailable', f => { const original = f.transport; f.transport = (url, options) => new URL(url).pathname === '/v1/appStoreVersions/v1/build'
      ? Promise.resolve(new Response('unavailable', { status: 404 })) : original(url, options); }],
    ['Truncated stream', f => { f.transport = async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(Buffer.from('{"data":[')); controller.error(new Error(env.ASC_KEY)); },
    })); }],
    ['Transport secret', f => { f.transport = async (_url, options) => { throw new Error(env.ASC_KEY + options.headers.Authorization); }; }],
  ];
  for (const [name, change, limits] of scenarios) {
    const fake = fixture();
    change(fake);
    const report = await collectInventory({ env, clock, transport: fake.transport, limits });
    assert.equal(report.complete, false, name);
    assert.ok(report.errors.length > 0, name);
    assert.ok(Object.values(report.collections).some(c => !c.complete), name);
    assert.ok(!JSON.stringify(report).includes('private error body'), name);
    assert.ok(!JSON.stringify(report).includes(env.ASC_KEY), name);
    assert.ok(!JSON.stringify(report).includes('Bearer '), name);
    if (name.startsWith('HTTP')) assert.equal(report.queries[0].status, Number(name.slice(5)));
    if (name === 'Total byte bound') {
      assert.ok(report.queries.length > 1);
      assert.match(report.errors[0].message, /total byte bound/);
    }
    if (name === 'Repeated cursor') assert.match(report.errors[0].message, /Repeated pagination cursor/);
    if (name === 'Selected build changed') assert.match(report.errors[0].message, /Selected build changed/);
    if (name === 'Truncated stream') {
      assert.equal(report.queries[0].body_complete, false);
      assert.equal(report.queries[0].sha256, null);
    }
    if (name === 'Later resource unavailable') {
      assert.equal(report.collections.builds.complete, true);
      assert.equal(report.collections.uploads.complete, false);
      assert.equal(report.queries.at(-1).status, 503);
    }
  }
  // Prove the CLI preserves an incomplete report and exits nonzero before any HTTP request.
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'apple-release-inventory-'));
  const output = path.join(directory, 'inventory.json');
  try {
    const result = spawnSync(process.execPath, [path.join(__dirname, '../scripts/read-apple-inventory.cjs'), output], {
      env: { ...env, ASC_KEY: 'generated-invalid-test-key' }, encoding: 'utf8',
    });
    assert.equal(result.status, 1);
    const report = JSON.parse(fs.readFileSync(output, 'utf8'));
    assert.equal(report.complete, false);
    assert.equal(report.queries.length, 0);
    assert.equal(report.source_sha, env.GITHUB_SHA);
    assert.ok(!result.stderr.includes('generated-invalid-test-key'));
    assert.ok(!result.stdout.includes('generated-invalid-test-key'));
  } finally {
    if (fs.existsSync(output)) fs.unlinkSync(output);
    fs.rmdirSync(directory);
  }
});
