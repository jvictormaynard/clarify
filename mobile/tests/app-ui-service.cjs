const http = require('node:http');

// Only synthetic simulator data. No request leaves this loopback service.
function createAppUIService({ record = () => {}, heartbeatMs = 1000 } = {}) {
  const requests = [], unexpected = [], held = [], waiters = [];
  let catalog = 'ready', revision = 1;
  const libraries = { '/v1/dictionary': [], '/v1/snippets': [] };
  const periodStart = new Date(); periodStart.setUTCHours(0, 0, 0, 0);
  periodStart.setUTCDate(periodStart.getUTCDate() - (periodStart.getUTCDay() + 6) % 7);
  const resetAt = new Date(periodStart); resetAt.setUTCDate(resetAt.getUTCDate() + 7);
  const user = { id: '00000000-0000-4000-8000-000000000033', email: 'clarify-e2e@example.test', output_preferences_supported: true, usage: {
    schema_version: 2, period_start: periodStart.toISOString(), reset_at: resetAt.toISOString(), used_percent: 12.5,
    remaining_percent: 82.5, reserved_percent: 5, allocation_status: 'available', hosted_available: true,
  } };
  const actions = () => [
    { id: 'rewrite', revision, name: 'Reescrever', kind: 'rewrite', enabled: true, prompt: 'Fixture rewrite' },
    { id: 'translation', revision, name: 'Traduzir', kind: 'translation', enabled: true, prompt: 'Fixture translation' },
    { id: 'disabled', revision, name: 'Desativada', kind: 'custom', enabled: false, prompt: 'Fixture disabled' },
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
      send(200, { held: held.length, processing: requests.filter(item => item.method === 'POST' && ['/v1/text', '/v1/text-actions/execute'].includes(item.route)) }); return;
    }
    if (method === 'GET' && route === '/v1/text-actions') {
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
        held.push(() => { stop(); send(200, { revision, actions: actions() }); });
        waiters.splice(0).forEach(done => done()); return;
      }
      send(catalog === 'failed' ? 503 : catalog === 'unsupported' ? 404 : 200,
        { revision, actions: catalog === 'empty' ? [] : actions() }); return;
    }
    if (method === 'POST' && ['/v1/text', '/v1/text-actions/execute'].includes(route)) {
      const result = { operation_id: value.operation_id, text: `Fixture result: ${value.text}` };
      if (value.action_id) Object.assign(result, { action_id: value.action_id, action_revision: value.action_revision });
      if (value.writing_style) Object.assign(result, { writing_style_requested: value.writing_style, writing_style_applied: value.writing_style, writing_style_status: 'applied' });
      send(200, result); return;
    }
    if (method === 'POST' && route === '/_allauth/app/v1/auth/continue') send(401, { meta: { session_token: 'isolated-e2e-session', is_authenticated: false } });
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
