const { execFileSync } = require('node:child_process');
const { mkdtempSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { createHash, sign } = require('node:crypto');

const origin = 'https://api.appstoreconnect.apple.com';
const app = '6820869157';
const group = 'IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE';
const nativeSlides = {
  'en-US': '71c00019-68e3-8425-8004-3f590105eee2',
  'pt-BR': '3e000019-68e3-8425-8013-5c413e507dcc',
  'es-ES': '04400019-68e3-8425-802f-98917a0776ce',
};
const sourceImages = JSON.parse(readFileSync(__dirname + '/asc-gallery-manifest.json', 'utf8'));

function token() {
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const now = Math.floor(Date.now() / 1000);
  const unsigned = [
    encode({ alg: 'ES256', kid: process.env.ASC_KEY_ID, typ: 'JWT' }),
    encode({ iss: process.env.ASC_ISSUER, iat: now, exp: now + 300, aud: 'appstoreconnect-v1' }),
  ].join('.');
  const signed = sign('sha256', Buffer.from(unsigned), {
    key: process.env.ASC_KEY, dsaEncoding: 'ieee-p1363',
  });
  return unsigned + '.' + signed.toString('base64url');
}

async function request(path, method = 'GET', data) {
  const url = new URL(path, origin);
  if (url.origin !== origin || !/^\/v[12]\//.test(url.pathname)) throw new Error('Unexpected Apple API URL');
  const response = await fetch(url, {
    method,
    redirect: 'error',
    headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify({ data }),
    signal: AbortSignal.timeout(25_000),
  });
  if (response.status === 204) return {};
  const result = await response.json();
  if (!response.ok) {
    const details = (result.errors ?? []).map(error => [error.code, error.title].join(' ')).join('; ');
    throw new Error(`${method} ${url.pathname}: HTTP ${response.status} ${details}`);
  }
  return result;
}

async function list(path, filters = {}) {
  const url = new URL(path, origin);
  for (const [key, value] of Object.entries(filters)) url.searchParams.set(key, value);
  url.searchParams.set('limit', '100');
  const rows = [];
  let next = url.href;
  while (next) {
    const page = await request(next);
    rows.push(...page.data);
    next = page.links?.next;
  }
  return rows;
}

const relation = (type, id) => ({ data: { type, id } });

const status = version => version.attributes.appVersionState ?? version.attributes.appStoreState;
const experimentPath = '/v2/appStoreVersionExperiments';
const experimentName = 'Clarify three-image gallery 0.14.0';
const mode = process.env.ASC_PPO_MODE;
const treatmentType = 'appStoreVersionExperimentTreatments';
const experimentType = 'appStoreVersionExperiments';
const treatmentName = 'Three new Clarify images';
const locType = 'appStoreVersionExperimentTreatmentLocalizations';

const assetId = item => item.relationships?.image?.data?.id;
const livePlacements = id => list(`/v1/appStoreVersionLocalizations/${id}/placements`, {
  'filter[placementType]': 'APP_SCREENSHOT',
  sort: 'placementGroupPosition',
  include: 'image',
});
const treatmentPlacements = id => list(`/v1/${locType}/${id}/placements`, {
  'filter[placementType]': 'APP_SCREENSHOT',
  'filter[placementGroup]': group,
  sort: 'placementGroupPosition',
  include: 'image',
});
async function inspect() {
  const versions = await list(`/v1/apps/${app}/appStoreVersions`, { 'filter[platform]': 'IOS' });
  const live = versions.find(row => row.attributes.versionString === '0.14.0' && status(row) === 'READY_FOR_DISTRIBUTION');
  const draft = versions.find(row => row.attributes.versionString === '0.14.1' && status(row) === 'PREPARE_FOR_SUBMISSION');
  if (!live || !draft) throw new Error('Unexpected published or draft version');
  const localizations = await list(`/v1/appStoreVersions/${live.id}/appStoreVersionLocalizations`);
  const experiments = await list(`/v1/apps/${app}/appStoreVersionExperimentsV2`);
  console.log(JSON.stringify({ live: live.id, draft: draft.id, locales: localizations.map(row => row.attributes.locale),
    experiments: experiments.map(row => [row.id, row.type, row.attributes.name, row.attributes.state]) }));
  const expected = {};
  for (const [locale, native] of Object.entries(nativeSlides)) {
    const existing = localizations.find(row => row.attributes.locale === locale);
    if (!existing) throw new Error('No live localization ' + locale);
    const placements = await livePlacements(existing.id);
    const current = placements.filter(row => row.attributes.placementGroup === group).map(assetId);
    if (!current.includes(native)) throw new Error('Could not verify the previously published native screenshot for ' + locale);
    const image = (await request('/v1/appAssetLibraryImages/' + native)).data.attributes;
    const { width, height } = image.imageAsset;
    if (image.state !== 'APPROVED' || width !== 1206 || height !== 2622) {
      throw new Error('Previously published asset not approved at expected size: ' + locale);
    }
    expected[locale] = { width, height, native, previous: current, sources: sourceImages[locale] };
    console.log(JSON.stringify({ locale, originals: current.length, width, height, native }));
  }
  return { live, experiments, expected };
}


const assetName = (locale, item) => `Clarify three-image gallery ${locale} ${item.key} ${item.sha256.slice(0, 12)}`;

async function resizedAsset(locale, plan, item) {
  const type = 'appAssetLibraryImages';
  const { width, height } = plan;
  const name = assetName(locale, item);
  const lookup = await list(`/v1/appAssetLibraries/${app}/images`, { 'filter[referenceName]': name });
  if (lookup.length > 1) throw new Error('Ambiguous treatment asset for ' + locale);
  let asset = lookup[0];
  if (!asset || asset.attributes.state === 'AWAITING_UPLOAD') {
    const source = Buffer.concat(Array.from({ length: item.count }, (_, index) => {
      const key = item.key + '_' + String(index + 1).padStart(2, '0');
      if (!process.env[key]) throw new Error('Missing screenshot chunk: ' + key);
      return Buffer.from(process.env[key], 'base64');
    }));
    if (createHash('sha256').update(source).digest('hex') !== item.sha256 ||
        source.length !== item.bytes || source.readUInt32BE(16) !== 1320 || source.readUInt32BE(20) !== 2868) {
      throw new Error('Input PNG does not match the selected gallery image');
    }
    const temporary = mkdtempSync(join(tmpdir(), 'clarify-ppo-'));
    let bytes;
    try {
      const raw = join(temporary, 'source');
      const resized = join(temporary, 'resized.png');
      writeFileSync(raw, source);
      execFileSync('convert', [raw, '-resize', `${width}x${height}^`, '-gravity', 'center', '-extent', `${width}x${height}`, '-alpha', 'off', 'PNG24:' + resized]);
      bytes = readFileSync(resized);
    } finally {
      rmSync(temporary, { recursive: true, force: true });
    }
    asset ??= (await request('/v1/' + type, 'POST', {
      type, attributes: {
        fileName: `clarify-gallery-${locale}-${item.key}-${width}x${height}.png`,
        fileSize: bytes.length, referenceName: name, category: 'APP_SCREENSHOTS_AND_PREVIEWS',
      },
      relationships: { assetLibrary: relation('appAssetLibraries', app) },
    })).data;
    if (asset.attributes.fileSize !== bytes.length || !asset.attributes.uploadOperations?.length) {
      throw new Error('Image reservation could not be resumed: ' + asset.id);
    }
    for (const operation of asset.attributes.uploadOperations) {
      const { method, url, offset, length, requestHeaders } = operation;
      if (new URL(url).protocol !== 'https:' || method !== 'PUT' || offset < 0 || length <= 0 || offset + length > bytes.length) {
        throw new Error('Invalid Apple asset operation');
      }
      const result = await fetch(url, {
        method, redirect: 'error', signal: AbortSignal.timeout(25_000),
        headers: Object.fromEntries(requestHeaders.map(({ name, value }) => [name, value])),
        body: bytes.subarray(offset, offset + length),
      });
      if (!result.ok) throw new Error('Apple upload HTTP ' + result.status);
    }
    asset = (await request(`/v1/${type}/${asset.id}`, 'PATCH', {
      type, id: asset.id, attributes: { uploaded: true },
    })).data;
  }
  for (let attempt = 0; asset.attributes.state === 'UPLOAD_COMPLETE' && attempt < 25; attempt++) {
    await delay(3000);
    asset = (await request(`/v1/${type}/${asset.id}`)).data;
  }
  const { state, imageAsset } = asset.attributes;
  if (!['PREPARE_FOR_SUBMISSION', 'APPROVED'].includes(state) || imageAsset?.width !== width || imageAsset?.height !== height) {
    throw new Error('Treatment screenshot processing or size mismatch: ' + asset.id + ' ' + state);
  }
  return asset.id;
}

async function setTreatmentImages(id, ordered, previous) {
  const localization = relation(locType, id);
  const type = 'appAssetLibraryPlacements';
  const existing = await treatmentPlacements(id);
  const found = new Map(existing.map(row => [assetId(row), row.id]));
  const inherited = [...found.keys()].filter(image => !ordered.includes(image));
  if (found.size !== existing.length || inherited.some(image => !previous.includes(image))) {
    throw new Error('Treatment contains screenshots outside the authorized replacement');
  }
  for (const image of inherited) {
    await request('/v1/' + type + '/' + found.get(image), 'DELETE');
    found.delete(image);
  }
  for (const image of ordered) {
    if (found.has(image)) continue;
    const row = (await request('/v1/' + type, 'POST', {
      type, attributes: { placementType: 'APP_SCREENSHOT', placementGroup: group },
      relationships: { image: relation('appAssetLibraryImages', image), appStoreVersionExperimentTreatmentLocalization: localization },
    })).data;
    found.set(image, row.id);
  }
  const current = (await treatmentPlacements(id)).map(assetId);
  if (JSON.stringify(current) !== JSON.stringify(ordered)) {
    const type = 'appAssetLibraryPlacementOrderingRequests';
    await request('/v1/' + type, 'POST', {
      type, attributes: { placementGroup: group },
      relationships: {
        orderedPlacements: { data: ordered.map(image => ({ type: 'appAssetLibraryPlacements', id: found.get(image) })) },
        appStoreVersionExperimentTreatmentLocalization: localization,
      },
    });
  }
  if (JSON.stringify((await treatmentPlacements(id)).map(assetId)) !== JSON.stringify(ordered)) {
    throw new Error('Unable to verify treatment screenshot order');
  }
}

async function prepare({ experiments, expected }) {
  if (experiments.some(row => row.attributes.name !== experimentName &&
      !['STOPPED', 'COMPLETED'].includes(row.attributes.state))) {
    throw new Error('A separate Product Page Optimization experiment already exists');
  }
  let experiment = experiments.find(row => row.attributes.name === experimentName);
  if (!experiment) {
    experiment = (await request(experimentPath, 'POST', {
      type: experimentType,
      attributes: { name: experimentName, platform: 'IOS', trafficProportion: 10 },
      relationships: { app: relation('apps', app) },
    })).data;
  }
  console.log(JSON.stringify({ experiment: experiment.id, experimentState: experiment.attributes.state }));
  const treatments = await list(`${experimentPath}/${experiment.id}/${treatmentType}`);
  if (treatments.some(row => row.attributes.name !== treatmentName)) throw new Error('Unexpected existing treatment');
  const treatment = treatments[0] ?? (await request('/v1/' + treatmentType, 'POST', {
    type: treatmentType, attributes: { name: treatmentName },
    relationships: { appStoreVersionExperimentV2: relation(experimentType, experiment.id) },
  })).data;
  console.log(JSON.stringify({ treatment: treatment.id }));
  const locales = await list(`/v1/${treatmentType}/${treatment.id}/${locType}`);
  for (const [locale, plan] of Object.entries(expected)) {
    const firstTwo = await Promise.all(plan.sources.map(item => resizedAsset(locale, plan, item)));
    const ordered = [...firstTwo, plan.native];
    const loc = locales.find(row => row.attributes.locale === locale) ?? (await request('/v1/' + locType, 'POST', {
      type: locType, attributes: { locale },
      relationships: { appStoreVersionExperimentTreatment: relation(treatmentType, treatment.id) },
    })).data;
    await setTreatmentImages(loc.id, ordered, plan.previous);
    console.log(JSON.stringify({ locale, treatmentLocalization: loc.id, images: ordered, width: plan.width, height: plan.height }));
  }
}

async function submit({ experiments, expected }) {
  const experiment = experiments.find(row => row.attributes.name === experimentName);
  if (!experiment) throw new Error('Unexpected experiment');
  const treatments = await list(`${experimentPath}/${experiment.id}/${treatmentType}`);
  const treatment = treatments.find(row => row.attributes.name === treatmentName);
  if (treatments.length !== 1 || !treatment) {
    throw new Error('Unexpected treatment');
  }
  const locales = await list(`/v1/${treatmentType}/${treatment.id}/${locType}`);
  if (locales.length !== Object.keys(expected).length) throw new Error('Unexpected treatment locales');
  for (const [locale, plan] of Object.entries(expected)) {
    const loc = locales.find(row => row.attributes.locale === locale);
    if (!loc) throw new Error('Missing treatment localization: ' + locale);
    const firstTwo = await Promise.all(plan.sources.map(async item => {
      const [image, ...duplicates] = await list(`/v1/appAssetLibraries/${app}/images`, { 'filter[referenceName]': assetName(locale, item) });
      if (!image || duplicates.length || !['PREPARE_FOR_SUBMISSION', 'APPROVED'].includes(image.attributes.state)) {
        throw new Error('Unverified treatment asset ' + item.key);
      }
      return image.id;
    }));
    const actual = (await treatmentPlacements(loc.id)).map(assetId);
    const desired = [...firstTwo, plan.native];
    if (JSON.stringify(actual) !== JSON.stringify(desired)) throw new Error('Treatment screenshot order changed: ' + locale);
  }
  const type = 'reviewSubmissions';
  const itemType = 'reviewSubmissionItems';
  const isTarget = item => item.relationships?.appStoreVersionExperimentV2?.data?.id === experiment.id;
  const submissions = await list(`/v1/apps/${app}/${type}`, { 'filter[platform]': 'IOS' });
  let existing;
  for (const row of submissions) {
    if (row.attributes.state === 'COMPLETE') continue;
    const items = await list(`/v1/${type}/${row.id}/items`, { include: 'appStoreVersionExperimentV2' });
    if (!items.some(isTarget)) continue;
    if (existing || items.length !== 1) throw new Error('Screenshot experiment shares a submission with another item');
    existing = row;
  }
  if (!existing && experiment.attributes.state !== 'PREPARE_FOR_SUBMISSION') {
    throw new Error('Unexpected experiment state: ' + experiment.attributes.state);
  }
  let submission = existing;
  if (!submission) {
    submission = (await request('/v1/' + type, 'POST', {
      type, attributes: { platform: 'IOS' }, relationships: { app: relation('apps', app) },
    })).data;
    console.log(JSON.stringify({ newSubmission: submission.id }));
    await request('/v1/' + itemType, 'POST', {
      type: itemType,
      relationships: {
        reviewSubmission: relation(type, submission.id),
        appStoreVersionExperimentV2: relation(experimentType, experiment.id),
      },
    });
  }
  const path = '/v1/' + type + '/' + submission.id;
  const items = await list(path + '/items', { include: 'appStoreVersionExperimentV2' });
  if (items.length !== 1 || !items.every(isTarget)) throw new Error('Submission is not screenshot experiment only');
  if (submission.attributes.state === 'READY_FOR_REVIEW') {
    await request(path, 'PATCH', { type, id: submission.id, attributes: { submitted: true } });
  }
  const final = (await request(path)).data;
  if (!['WAITING_FOR_REVIEW', 'IN_REVIEW', 'COMPLETING', 'COMPLETE'].includes(final.attributes.state)) {
    throw new Error('Screenshot review submission state: ' + final.attributes.state);
  }
  console.log(JSON.stringify({ submission: final.id, state: final.attributes.state,
    experiment: experiment.id, submittedItems: items.map(row => row.id) }));
}
async function reviewStatus() {
  const id = process.env.ASC_SUBMISSION;
  const experimentId = process.env.ASC_EXPERIMENT;
  const treatmentId = process.env.ASC_TREATMENT;
  if (![id, experimentId, treatmentId].every(value => /^[0-9a-f-]{36}$/.test(value ?? ''))) {
    throw new Error('Missing review resource identifiers');
  }
  const [review, experiment, treatment, live] = await Promise.all([
    request('/v1/reviewSubmissions/' + id),
    request('/v2/appStoreVersionExperiments/' + experimentId),
    request('/v1/appStoreVersionExperimentTreatments/' + treatmentId),
    request('/v1/appStoreVersions/89b9360d-fc31-423f-8d76-e6494ff49469'),
  ]);
  const items = await list('/v1/reviewSubmissions/' + id + '/items', { include: 'appStoreVersionExperimentV2' });
  if (items.length !== 1 || items[0].relationships?.appStoreVersionExperimentV2?.data?.id !== experimentId) {
    throw new Error('Review submission no longer contains the expected screenshot-only item');
  }
  console.log('CLARIFY_PPO_STATUS ' + JSON.stringify({
    submission: id,
    review: review.data.attributes.state,
    reviewItem: items[0].attributes.state,
    experiment: experimentId,
    experimentState: experiment.data.attributes.state,
    treatment: treatmentId,
    promotedDate: treatment.data.attributes.promotedDate,
    liveVersion: live.data.attributes.versionString,
    liveState: status(live.data),
  }));
}

async function main() {
  if (mode === 'screenshot-gallery-status') return reviewStatus();
  const target = await inspect();
  if (mode !== 'screenshot-gallery-submit') return;
  await prepare(target);
  await submit(await inspect());
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
