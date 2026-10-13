// Complete an already-authorized internal TestFlight delivery. Credentials
// remain in runner memory; this script never creates a group or adds testers.
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const config = require('../app.json').expo;
const app = require('../eas.json').submit.production.ios.ascAppId;
const notes = {
  'pt-BR': 'Correção no reconhecimento de gravações curtas, como “oi”, no modo de chave pessoal Groq com dicionário ativo. Os termos, variações e pronúncias salvos são preservados. Teste um ditado curto no aplicativo e pelo teclado, com seu dicionário ativo.',
  'en-US': 'Fixed recognition of short recordings such as “oi” when using a personal Groq key with an active dictionary. Saved terms, aliases and pronunciations are preserved. Test short speech in the app and through the keyboard with your dictionary enabled.',
  'es-ES': 'Corregido el reconocimiento de grabaciones cortas, como “oi”, con una clave personal de Groq y el diccionario activo. Se conservan los términos, variantes y pronunciaciones guardados. Prueba un dictado corto en la app y desde el teclado con tu diccionario activo.',
};
function token() {
  const now = Math.floor(Date.now() / 1000);
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString('base64url');
  const input = encode({ alg: 'ES256', kid: process.env.CLARIFY_ASC_KEY_ID, typ: 'JWT' }) + '.'
    + encode({ iss: process.env.CLARIFY_ASC_ISSUER_ID, iat: now, exp: now + 900, aud: 'appstoreconnect-v1' });
  return input + '.' + crypto.sign('sha256', Buffer.from(input), {
    key: process.env.CLARIFY_ASC_KEY_P8, dsaEncoding: 'ieee-p1363',
  }).toString('base64url');
}
async function request(route, method = 'GET', body) {
  const response = await fetch('https://api.appstoreconnect.apple.com/v1/' + route, {
    method, signal: AbortSignal.timeout(30_000),
    headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) throw new Error(`Apple API request failed: ${response.status}`);
  return response.status === 204 ? { data: [] } : response.json();
}
async function main() {
  for (const name of ['CLARIFY_ASC_KEY_ID', 'CLARIFY_ASC_ISSUER_ID', 'CLARIFY_ASC_KEY_P8']) {
    if (!process.env[name]) throw new Error('Missing configured App Store Connect credential.');
  }
  const groups = await request(`betaGroups?filter[app]=${app}&limit=100`);
  const group = groups.data.find((item) => item.attributes.name === 'Clarify Interno' && item.attributes.isInternalGroup);
  if (!group) throw new Error('The existing internal group was not found.');
  let attached = false;
  for (let attempt = 0; attempt < 40; attempt++) {
    const result = await request(`builds?filter[app]=${app}&filter[version]=${config.ios.buildNumber}&include=preReleaseVersion&limit=10`);
    const build = result.data.find((item) => result.included?.some((version) =>
      version.type === 'preReleaseVersions' && version.id === item.relationships.preReleaseVersion.data.id
      && version.attributes.version === config.version));
    if (build && ['FAILED', 'INVALID'].includes(build.attributes.processingState)) throw new Error('Apple rejected the uploaded build.');
    if (build?.attributes.processingState === 'VALID') {
      if (!attached) {
        const membership = await request(`betaGroups/${group.id}/builds?limit=100`);
        if (!membership.data.some((item) => item.id === build.id)) {
          await request(`betaGroups/${group.id}/relationships/builds`, 'POST', { data: [{ type: 'builds', id: build.id }] });
        }
        const localizations = await request(`builds/${build.id}/betaBuildLocalizations`);
        for (const [locale, whatsNew] of Object.entries(notes)) {
          const existing = localizations.data.find((item) => item.attributes.locale === locale);
          if (existing) await request(`betaBuildLocalizations/${existing.id}`, 'PATCH', { data: { type: 'betaBuildLocalizations', id: existing.id, attributes: { whatsNew } } });
          else await request('betaBuildLocalizations', 'POST', { data: { type: 'betaBuildLocalizations', attributes: { locale, whatsNew }, relationships: { build: { data: { type: 'builds', id: build.id } } } } });
        }
        attached = true;
      }
      const [detail, membership, testers] = await Promise.all([
        request(`builds/${build.id}/buildBetaDetail`), request(`betaGroups/${group.id}/builds?limit=100`),
        request(`betaGroups/${group.id}/relationships/betaTesters?limit=200`),
      ]);
      if (detail.data.attributes.internalBuildState === 'IN_BETA_TESTING'
          && membership.data.some((item) => item.id === build.id) && testers.data.length > 0) {
        const evidence = { checkedAt: new Date().toISOString(), id: build.id, version: config.version,
          build: config.ios.buildNumber, processing: 'VALID', internalState: 'IN_BETA_TESTING',
          group: group.attributes.name, availableInGroup: true, existingTesters: testers.data.length };
        fs.mkdirSync('test-results', { recursive: true });
        fs.writeFileSync(path.join('test-results', 'testflight-availability.json'), JSON.stringify(evidence, null, 2));
        console.log(JSON.stringify(evidence));
        return;
      }
    }
    console.log(JSON.stringify({ version: config.version, build: config.ios.buildNumber, processing: build?.attributes.processingState || 'NOT_VISIBLE' }));
    await new Promise((resolve) => setTimeout(resolve, 30_000));
  }
  throw new Error('Apple processing or internal TestFlight availability is still pending.');
}
main().catch((error) => { console.error(error.message); process.exitCode = 1; });
