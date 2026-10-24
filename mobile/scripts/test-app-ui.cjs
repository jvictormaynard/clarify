// Run the actual containing-app UI against an isolated local account service.
// The signed project and production endpoint are never modified.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const crypto = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
if (process.platform !== 'darwin') throw new Error('App UI acceptance requires macOS and an iPhone simulator.');
const root = process.cwd();
const output = path.join(root, 'test-results/app-ui');
fs.mkdirSync(output, { recursive: true });
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.status !== 0) throw new Error(`${command} failed (${result.status ?? result.error?.message})`);
  return result.stdout;
}
const fingerprint = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const original = path.join(root, 'ios');
const preserved = ['Clarify/Info.plist', 'Clarify.xcodeproj/project.pbxproj'].map(name => [name, fingerprint(path.join(original, name))]);
const fixture = fs.mkdtempSync(path.join(root, '.app-ui-'));
const requests = [];
const unexpected = [];
const user = { id: '00000000-0000-4000-8000-000000000033', email: 'clarify-e2e@example.test', usage: { used_ms: 450000, limit_ms: 18000000, reserved_ms: 0, hosted_available: true } };
const server = http.createServer(async (request, response) => {
  let body = '';
  for await (const chunk of request) { body += chunk; if (body.length > 1048576) { response.writeHead(413).end(); return; } }
  let value = {};
  try { if (body) value = JSON.parse(body); } catch { response.writeHead(400).end(); return; }
  const route = request.url.split('?')[0];
  const method = request.method;
  let result, status = 200;
  if (method === 'POST' && route === '/_allauth/app/v1/auth/continue') {
    status = 401; result = { meta: { session_token: 'isolated-e2e-session', is_authenticated: false } };
  } else if (method === 'POST' && route === '/_allauth/app/v1/auth/code/confirm') {
    status = value.code === '123456' ? 200 : 401;
    result = { meta: { session_token: 'isolated-e2e-session', is_authenticated: status === 200 } };
  } else if (method === 'GET' && route === '/v1/account') result = user;
  else if (['GET', 'PUT'].includes(method) && ['/v1/dictionary', '/v1/snippets'].includes(route)) result = { revision: 0, entries: value.entries || [] };
  else if (method === 'POST' && route === '/v1/history/sync') result = { cursor: 0, hasMore: false, entries: [], deleted: [] };
  else if (method === 'DELETE' && route === '/_allauth/app/v1/auth/session') { status = 204; result = null; }
  else { status = 404; result = {}; unexpected.push({ method, route }); }
  requests.push({ method, route, status });
  response.writeHead(status, { 'Content-Type': 'application/json' });
  response.end(result === null ? '' : JSON.stringify(result));
});
let simulator;
let exitCode = 1;
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const endpoint = `http://127.0.0.1:${server.address().port}`;
  fs.cpSync(original, fixture, { recursive: true, filter: file => !['Pods', 'build'].includes(path.relative(original, file).split(path.sep)[0]) });
  fs.symlinkSync(path.join(original, 'Pods'), path.join(fixture, 'Pods'), 'dir');
  run('python3', ['-c', 'import plistlib,sys; p=sys.argv[1]; d=plistlib.load(open(p,"rb")); d["ClarifyCloudURL"]=sys.argv[2]; d["NSAppTransportSecurity"]={"NSAllowsArbitraryLoads":True}; plistlib.dump(d,open(p,"wb"))', path.join(fixture, 'Clarify/Info.plist'), endpoint]);
  run('ruby', [path.join(root, 'scripts/app-ui-project.rb'), root, fixture, endpoint]);
  const runtimes = JSON.parse(run('xcrun', ['simctl', 'list', 'runtimes', '--json'], { encoding: 'utf8', stdio: 'pipe' })).runtimes;
  const runtime = runtimes.find(item => item.isAvailable && item.identifier.startsWith(`com.apple.CoreSimulator.SimRuntime.${process.env.CLARIFY_IOS_RUNTIME || 'iOS-'}`));
  const types = JSON.parse(run('xcrun', ['simctl', 'list', 'devicetypes', '--json'], { encoding: 'utf8', stdio: 'pipe' })).devicetypes;
  const device = types.find(item => item.name === 'iPhone 17 Pro') || types.find(item => item.name.startsWith('iPhone'));
  if (!runtime || !device) throw new Error('Matching iPhone simulator is unavailable.');
  simulator = run('xcrun', ['simctl', 'create', `Clarify App UI ${process.pid}`, device.identifier, runtime.identifier], { encoding: 'utf8', stdio: 'pipe' }).trim();
  run('xcrun', ['simctl', 'bootstatus', simulator, '-b']);
  run('xcrun', ['simctl', 'ui', simulator, 'appearance', 'dark']);
  const result = path.join(output, 'AppFlow.xcresult');
  await new Promise((resolve, reject) => {
    const child = spawn('xcodebuild', ['test', '-workspace', path.join(fixture, 'Clarify.xcworkspace'), '-scheme', 'ClarifyAppFlow', '-configuration', 'Release', '-destination', `platform=iOS Simulator,id=${simulator}`, '-parallel-testing-enabled', 'NO', '-derivedDataPath', path.join(os.tmpdir(), `clarify-app-ui-derived-${process.pid}`), '-resultBundlePath', result, 'CODE_SIGNING_ALLOWED=NO'], { stdio: 'inherit', env: { ...process.env, RCT_NO_LAUNCH_PACKAGER: '1', EXPO_NO_TELEMETRY: '1' } });
    child.once('error', reject);
    child.once('exit', code => code === 0 ? resolve() : reject(new Error(`App UI acceptance failed (${code}).`)));
  });
  if (unexpected.length) throw new Error(`Unexpected fixture endpoints: ${JSON.stringify(unexpected)}`);
  if (!requests.some(item => item.route === '/_allauth/app/v1/auth/code/confirm') || !requests.some(item => item.method === 'DELETE')) throw new Error('Account flow did not traverse the real native HTTP client.');
  exitCode = 0;
})().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(async () => {
  const result = path.join(output, 'AppFlow.xcresult');
  if (fs.existsSync(result)) spawnSync('xcrun', ['xcresulttool', 'export', 'attachments', '--path', result, '--output-path', path.join(output, 'captures')], { stdio: 'inherit' });
  for (const [name, hash] of preserved) if (fingerprint(path.join(original, name)) !== hash) { console.error('Production generated project changed during app UI testing.'); exitCode = 1; }
  fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify({ exitCode, sourceProjectUnchanged: preserved.every(([name, hash]) => fingerprint(path.join(original, name)) === hash), requests, unexpected }, null, 2));
  await new Promise(resolve => server.close(resolve));
  if (simulator) { spawnSync('xcrun', ['simctl', 'shutdown', simulator]); spawnSync('xcrun', ['simctl', 'delete', simulator]); }
  if (path.dirname(fixture) === root && path.basename(fixture).startsWith('.app-ui-')) fs.rmSync(fixture, { recursive: true, force: true });
  process.exitCode = exitCode;
});
