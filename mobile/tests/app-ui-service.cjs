const http = require('node:http');

// Only synthetic simulator data. No request leaves this loopback service.
function createAppUIService({ record = () => {}, heartbeatMs = 1000, now = Date.now } = {}) {
  const requests = [], unexpected = [], held = [], waiters = [];
  let catalog = 'ready', revision = 1;
  const libraries = { '/v1/dictionary': [], '/v1/snippets': [] };
  const computerID = '00000000-0000-4000-8000-000000000034';
  const token = Buffer.alloc(32, 3).toString('base64url');
  const user = { id: '00000000-0000-4000-8000-000000000033', email: 'clarify-e2e@example.test' };
  const contract = { schema_version: 1, output_languages: ['auto', 'pt', 'en', 'es', 'de', 'ru'],
    writing_styles: ['formal', 'casual', 'very_casual', 'natural', 'informal', 'organized'],
    cleanup_levels: ['preserve', 'light', 'clarity'], dictation_actions: true, explicit_dictation_policy: true,
    dictation_editing: { legacy: true, natural: true, clarity: true, action: true, legacy_translated: true, natural_translated: true },
    text_input_bytes: 16000, text_output_bytes: 64000 };
  const actions = () => [
    { id: 'rewrite', revision, name: 'Reescrever', kind: 'rewrite', enabled: true, ready: true },
    { id: 'translation', revision, name: 'Traduzir', kind: 'translation', enabled: true, ready: true },
    { id: 'disabled', revision, name: 'Desativada', kind: 'custom', enabled: false, ready: false },
  ];
  const server = http.createServer(async (request, response) => {
    const route = request.url.split('?')[0], method = request.method;
    record({ event: 'received', method, route });
    let body = '';
    for await (const chunk of request) { body += chunk; if (body.length > 1048576) { response.writeHead(413).end(); return; } }
    let value = {};
    try { if (body) value = JSON.parse(body); } catch { response.writeHead(400).end(); return; }
    function send(status, result) {
      requests.push({ method, route, status, value }); record({ event: 'responded', method, route, status });
      if (response.destroyed) return;
      if (!response.headersSent) response.writeHead(status, { 'Content-Type': 'application/json' });
      response.end(result === null ? '' : JSON.stringify(result));
    }
    if (method === 'POST' && route === '/__fixture/control') {
      if (value.catalog) catalog = value.catalog;
      if (value.revision) revision = value.revision;
      if (value.release) { catalog = 'ready'; held.splice(0).forEach(done => done()); }
      send(200, { held: held.length }); return;
    }
    if (method === 'GET' && route === '/__fixture/wait-catalog') {
      if (held.length) send(200, { held: held.length }); else waiters.push(() => send(200, { held: held.length }));
      return;
    }
    if (method === 'GET' && route === '/__fixture/state') {
      send(200, { held: held.length, processing: requests.filter(item => item.method === 'POST' && item.route === '/v1/computer/text') }); return;
    }
    if (method === 'GET' && route === '/__fixture/invitation') {
      send(200, { invitation: 'clarify://computer?data=' + Buffer.from(JSON.stringify({
        schema_version: 1, computer_id: computerID, computer_name: 'Fixture PC',
        routes: [{ url: 'https://192.168.1.33:9443', certificate_sha256: 'a'.repeat(64) }],
        pairing_token: Buffer.alloc(32, 2).toString('base64url'), expires_at: new Date(now() + 240000).toISOString(),
      })).toString('base64url') }); return;
    }
    if (route.startsWith('/v1/computer/')) {
      if (method === 'POST' && route === '/v1/computer/pair') {
        if (request.headers.authorization || value.pairing_token !== Buffer.alloc(32, 2).toString('base64url') || !value.device_name) { send(401, {}); return; }
        send(201, { schema_version: 1, computer_id: computerID, computer_name: 'Fixture PC',
          device_id: '00000000-0000-4000-8000-000000000035', session_token: token }); return;
      }
      if (request.headers.authorization !== 'Bearer ' + token) { send(401, {}); return; }
    }
    if (method === 'DELETE' && route === '/v1/computer/session') { send(204, null); return; }
    const status = () => ({ schema_version: 1, computer_id: computerID, computer_name: 'Fixture PC', ready: true,
      action_readiness: { dictate: true, rewrite: true, translate: true }, output_preferences_supported: true,
      processing_contract: contract, ...(catalog === 'unsupported' ? {} : { text_actions: catalog === 'empty' ? [] : actions() }) });
    if (method === 'GET' && route === '/v1/computer/status') {
      if (catalog === 'slow') {
        // Keep the request active; only the release barrier completes its JSON.
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.write(' ');
        const heartbeat = setInterval(() => {
          if (!response.destroyed && !response.writableEnded) response.write(' ');
        }, heartbeatMs);
        heartbeat.unref();
        const stop = () => clearInterval(heartbeat);
        response.once('close', stop);
        held.push(() => { stop(); send(200, status()); });
        waiters.splice(0).forEach(done => done()); return;
      }
      send(catalog === 'failed' ? 503 : 200, status()); return;
    }
    if (method === 'POST' && route === '/v1/computer/text') {
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.operation_id || '')
        || !value.text || value.action !== 'text_action') { send(400, {}); return; }
      if (requests.some(item => item.route === route && item.status === 200 && item.value.operation_id === value.operation_id)) { send(409, {}); return; }
      if (!actions().some(action => action.id === value.action_id && action.revision === value.action_revision && action.enabled)) { send(409, { error: 'text_action_stale' }); return; }
      const result = { operation_id: value.operation_id, transcript: value.text, text: `Fixture result: ${value.text}`, rewritten: true, successful: true };
      if (value.action_id) Object.assign(result, { action_id: value.action_id, action_revision: value.action_revision });
      Object.assign(result, { output_language_requested: value.language, output_language_applied: value.language, output_language_status: value.language === 'auto' ? 'unchanged' : 'applied' });
      if (value.writing_style) Object.assign(result, { writing_style_requested: value.writing_style, writing_style_applied: value.writing_style, writing_style_status: 'applied' });
      send(200, result); return;
    }
    if (method === 'POST' && route === '/_allauth/app/v1/auth/continue') {
      if (value.email !== user.email) { send(400, { errors: [{ param: 'email', code: 'invalid' }] }); return; }
      send(401, { meta: { session_token: 'isolated-e2e-session', is_authenticated: false } });
    }
    else if (method === 'POST' && route === '/_allauth/app/v1/auth/code/confirm') send(value.code === '123456' ? 200 : 401, { meta: { session_token: 'isolated-e2e-session', is_authenticated: value.code === '123456' } });
    else if (method === 'GET' && route === '/v1/account') send(200, user);
    else if (['GET', 'PUT'].includes(method) && route in libraries) {
      if (method === 'PUT') libraries[route] = value.entries || [];
      send(200, { revision: 0, entries: libraries[route] });
    } else if (method === 'POST' && route === '/v1/history/sync') send(200, { cursor: 0, hasMore: false, entries: [], deleted: [] });
    else if (method === 'DELETE' && route === '/_allauth/app/v1/auth/session') send(204, null);
    else { unexpected.push({ method, route }); send(404, {}); }
  });
  return { server, requests, unexpected, release() { held.splice(0).forEach(done => done()); } };
}
module.exports = { createAppUIService };
