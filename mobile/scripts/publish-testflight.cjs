// Complete an already-authorized internal TestFlight delivery. Credentials
// remain in runner memory; this script never creates a group or adds testers.
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const config = require('../app.json').expo;
const app = require('../eas.json').submit.production.ios.ascAppId;
const notes = {
  'pt-BR': 'Histórico sincronizado automaticamente com o desktop 0.9.0. Entre com a mesma conta nos dois dispositivos e faça novas transcrições em cada um; confira texto, horário e origem no outro dispositivo. Registros antigos e feitos sem conta permanecem locais. Alterações pendentes sobrevivem a falhas de conexão e reinícios; exclusões também sincronizam. A correção de abertura do teclado já validada foi preservada. O retorno ao app de origem e a integração de altura mantêm APIs privadas da Apple no experimento autorizado para TestFlight.',
  'en-US': 'History syncs automatically with desktop 0.9.0. Sign in to the same account on both devices and create new transcriptions on each; check text, time and source on the other device. Existing records and account-free history remain local. Pending changes survive connection failures and app restarts; deletions also sync. The accepted keyboard-opening correction is preserved. Source-app return and keyboard-height integration retain private Apple APIs for the authorized TestFlight experiment.',
  'es-ES': 'El historial se sincroniza automáticamente con desktop 0.9.0. Inicia sesión con la misma cuenta en ambos dispositivos y crea nuevas transcripciones en cada uno; comprueba texto, hora y origen en el otro dispositivo. Los registros anteriores y el historial sin cuenta siguen siendo locales. Los cambios pendientes se conservan tras fallos de conexión y reinicios; las eliminaciones también se sincronizan. Se conserva la corrección de apertura del teclado ya validada. El regreso a la aplicación de origen y la integración de altura mantienen API privadas de Apple en el experimento autorizado para TestFlight.',
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
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    const detail = (failure.errors || []).map((error) => `${error.code}: ${error.detail || error.title}`).join('; ');
    throw new Error(`Apple API ${response.status} for ${method} ${route.split('?')[0]}: ${detail}`);
  }
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
