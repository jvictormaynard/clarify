// Run the actual containing-app UI against an isolated local account service.
// The signed project and production endpoint are never modified.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
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
const journalPath = path.join(output, 'requests.jsonl');
function record(event) {
  const line = JSON.stringify({ at: new Date().toISOString(), ...event });
  fs.appendFileSync(journalPath, `${line}\n`);
  console.log(`APP_UI_HTTP ${line}`);
}
const { createAppUIService } = require('../tests/app-ui-service.cjs');
const service = createAppUIService({ record });
const { server, requests, unexpected } = service;
let simulator;
const results = [];
const scenarios = [];
let exitCode = 1;
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const endpoint = `http://127.0.0.1:${server.address().port}`;
  record({ event: 'listening', endpoint });
  fs.cpSync(original, fixture, { recursive: true, filter: file => !['Pods', 'build'].includes(path.relative(original, file).split(path.sep)[0]) });
  fs.symlinkSync(path.join(original, 'Pods'), path.join(fixture, 'Pods'), 'dir');
  run('python3', ['-c', 'import plistlib,sys; p=sys.argv[1]; d=plistlib.load(open(p,"rb")); d["ClarifyCloudURL"]=sys.argv[2]; d["NSAppTransportSecurity"]={"NSAllowsArbitraryLoads":True}; plistlib.dump(d,open(p,"wb"))', path.join(fixture, 'Clarify/Info.plist'), endpoint]);
  run('ruby', [path.join(root, 'scripts/app-ui-project.rb'), root, fixture, endpoint]);
  const testSource = path.join(fixture, 'ClarifyAppFlowTests.swift');
  fs.writeFileSync(testSource, fs.readFileSync(testSource, 'utf8').replaceAll('__CLARIFY_APP_UI_ENDPOINT__', endpoint));
  const runtimes = JSON.parse(run('xcrun', ['simctl', 'list', 'runtimes', '--json'], { encoding: 'utf8', stdio: 'pipe' })).runtimes;
  const runtime = runtimes.find(item => item.isAvailable && item.identifier.startsWith(`com.apple.CoreSimulator.SimRuntime.${process.env.CLARIFY_IOS_RUNTIME || 'iOS-'}`));
  const types = JSON.parse(run('xcrun', ['simctl', 'list', 'devicetypes', '--json'], { encoding: 'utf8', stdio: 'pipe' })).devicetypes;
  const regular = types.find(item => item.name === 'iPhone 17 Pro') || types.find(item => item.name.startsWith('iPhone'));
  const compact = types.find(item => item.name === 'iPhone 13 mini') || types.find(item => item.name === 'iPhone SE (3rd generation)');
  if (!compact) throw new Error('Compact iPhone simulator is unavailable.');
  for (const scenario of [
    { name: 'AppFlow', device: regular, appearance: 'dark', text: 'large' },
    { name: 'AppFlow-compact-light', device: compact, appearance: 'light', text: 'accessibility-extra-extra-extra-large' },
  ]) {
  const device = scenario.device;
  scenarios.push({ ...scenario, device: device?.name });
  await fetch(endpoint + '/__fixture/control', { method: 'POST', body: JSON.stringify({ catalog: 'ready', revision: 1, release: true }) });
  if (!runtime || !device) throw new Error('Matching iPhone simulator is unavailable.');
  simulator = run('xcrun', ['simctl', 'create', `Clarify App UI ${process.pid}`, device.identifier, runtime.identifier], { encoding: 'utf8', stdio: 'pipe' }).trim();
  run('xcrun', ['simctl', 'bootstatus', simulator, '-b']);
  run('xcrun', ['simctl', 'ui', simulator, 'appearance', scenario.appearance]);
  run('xcrun', ['simctl', 'ui', simulator, 'content_size', scenario.text]);
  const result = path.join(output, scenario.name + '.xcresult');
  results.push({ path: result, name: scenario.name });
  await new Promise((resolve, reject) => {
    // Installed simulator apps need base entitlements for the real Keychain.
    // Ad-hoc signing applies to this copied project and needs no certificate.
    const child = spawn('xcodebuild', ['test', '-workspace', path.join(fixture, 'Clarify.xcworkspace'), '-scheme', 'ClarifyAppFlow', '-configuration', 'Release', '-destination', `platform=iOS Simulator,id=${simulator}`, '-parallel-testing-enabled', 'NO', '-derivedDataPath', path.join(os.tmpdir(), `clarify-app-ui-derived-${process.pid}`), '-resultBundlePath', result, 'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-', 'CODE_SIGN_INJECT_BASE_ENTITLEMENTS=YES', 'ONLY_ACTIVE_ARCH=YES', 'OTHER_SWIFT_FLAGS=$(inherited) -D CLARIFY_APP_FLOW_TESTING'], { stdio: 'inherit', env: { ...process.env, RCT_NO_LAUNCH_PACKAGER: '1', EXPO_NO_TELEMETRY: '1' } });
    child.once('error', reject);
    child.once('exit', code => code === 0 ? resolve() : reject(new Error(`App UI acceptance failed (${code}).`)));
  });
  run('xcrun', ['simctl', 'shutdown', simulator]);
  run('xcrun', ['simctl', 'delete', simulator]);
  simulator = undefined;
  }
  if (unexpected.length) throw new Error(`Unexpected fixture endpoints: ${JSON.stringify(unexpected)}`);
  if (!requests.some(item => item.route === '/_allauth/app/v1/auth/code/confirm') || !requests.some(item => item.method === 'DELETE')) throw new Error('Account flow did not traverse the real native HTTP client.');
  if (requests.some(item => ['/v1/text', '/v1/text-actions/execute'].includes(item.route) && ['cancelled-preparation', 'deactivated-preparation'].includes(item.value.text))) throw new Error('Cancelled or deactivated discovery sent a late processing POST.');
  exitCode = 0;
})().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(async () => {
  for (const result of results) if (fs.existsSync(result.path)) spawnSync('xcrun', ['xcresulttool', 'export', 'attachments', '--path', result.path, '--output-path', path.join(output, 'captures', result.name)], { stdio: 'inherit' });
  for (const [name, hash] of preserved) if (fingerprint(path.join(original, name)) !== hash) { console.error('Production generated project changed during app UI testing.'); exitCode = 1; }
  fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify({ exitCode, sourceProjectUnchanged: preserved.every(([name, hash]) => fingerprint(path.join(original, name)) === hash), requests, unexpected, scenarios }, null, 2));
  service.release();
  await new Promise(resolve => server.close(resolve));
  if (simulator) { spawnSync('xcrun', ['simctl', 'shutdown', simulator]); spawnSync('xcrun', ['simctl', 'delete', simulator]); }
  if (path.dirname(fixture) === root && path.basename(fixture).startsWith('.app-ui-')) fs.rmSync(fixture, { recursive: true, force: true });
  process.exitCode = exitCode;
});
