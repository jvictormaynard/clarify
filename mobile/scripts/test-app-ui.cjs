// Run the actual containing-app UI against an isolated local account service.
// The signed project and production endpoint are never modified.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
const readline = require('node:readline');

// A successful xcodebuild with a stale selector can execute zero tests.
function requirePassedTest(lines, method) {
  const name = `ClarifyAppFlowTests.AppFlowUITests ${method}`;
  const events = lines.map(line => line.match(/^Test Case '-\[([^\]]+)\]' (started|passed|failed)\b/));
  if (events.length !== 2 || events.some(event => !event || event[1] !== name)
      || events[0][2] !== 'started' || events[1][2] !== 'passed') {
    throw new Error(`Expected exactly one passing App UI test: ${method}. Observed: ${lines.join('\n')}`);
  }
}

async function runXcode(args, method) {
  const lines = [];
  await new Promise((resolve, reject) => {
    const child = spawn('xcodebuild', args, { stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, RCT_NO_LAUNCH_PACKAGER: '1', EXPO_NO_TELEMETRY: '1' } });
    for (const [stream, destination] of [[child.stdout, process.stdout], [child.stderr, process.stderr]]) {
      stream.pipe(destination, { end: false });
      readline.createInterface({ input: stream }).on('line', line => {
        if (line.startsWith("Test Case '")) lines.push(line);
      });
    }
    child.once('error', reject);
    child.once('close', code => code === 0 ? resolve() : reject(new Error(`App UI xcodebuild failed (${code}).`)));
  });
  if (method) requirePassedTest(lines, method);
}

async function main() {
  if (process.platform !== 'darwin') throw new Error('App UI acceptance requires macOS and an iPhone simulator.');
  const root = process.cwd();
  const output = path.join(root, 'test-results/app-ui');
  if (fs.existsSync(output) && fs.readdirSync(output).length) throw new Error('App UI output must be empty; preserve the previous run separately.');
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
  const inputTraceErrors = [];
  const scenarios = [];
  const compactOnly = process.env.CLARIFY_APP_UI_COMPACT_ONLY === 'true';
  const derivedData = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-app-ui-derived-'));
  let testRun, buildSeconds;
  let exitCode = 1;
  try {
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
      { name: 'AppFlow', device: regular, appearance: 'dark', text: 'large', method: 'testFirstPresentationAccountNavigationAndExplicitReplay' },
      { name: 'AppFlow-compact-light', device: compact, appearance: 'light', text: 'accessibility-extra-extra-extra-large', method: 'testCompactKeyboardAndActionLayout' },
    ].filter(scenario => !compactOnly || scenario.name === 'AppFlow-compact-light')) {
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
      if (!testRun) {
        // Installed simulator apps need base entitlements for the real Keychain.
        // Ad-hoc signing applies to this copied project and needs no certificate.
        const started = Date.now();
        await runXcode(['build-for-testing', '-workspace', path.join(fixture, 'Clarify.xcworkspace'), '-scheme', 'ClarifyAppFlow', '-configuration', 'Release', '-destination', `platform=iOS Simulator,id=${simulator}`, '-derivedDataPath', derivedData, 'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-', 'CODE_SIGN_INJECT_BASE_ENTITLEMENTS=YES', 'ONLY_ACTIVE_ARCH=YES', 'OTHER_SWIFT_FLAGS=$(inherited) -D CLARIFY_APP_FLOW_TESTING']);
        buildSeconds = (Date.now() - started) / 1000;
        const products = path.join(derivedData, 'Build/Products');
        const manifests = fs.readdirSync(products).filter(name => name.endsWith('.xctestrun'));
        if (manifests.length !== 1) throw new Error(`Expected one App UI test manifest, found ${manifests.length}.`);
        const manifest = path.join(products, manifests[0]);
        testRun = { path: manifest, sha256: fingerprint(manifest) };
      }
      if (fingerprint(testRun.path) !== testRun.sha256) throw new Error('App UI test manifest changed between profiles.');
      const started = Date.now();
      try {
        await runXcode(['test-without-building', '-xctestrun', testRun.path, '-destination', `platform=iOS Simulator,id=${simulator}`, '-parallel-testing-enabled', 'NO', '-resultBundlePath', result, `-only-testing:ClarifyAppFlowTests/AppFlowUITests/${scenario.method}`], scenario.method);
      } finally {
        try {
          const container = run('xcrun', ['simctl', 'get_app_container', simulator, 'com.jvictormaynard.clarify', 'data'], { encoding: 'utf8', stdio: 'pipe' }).trim();
          const trace = path.join(container, 'Library/Caches/clarify-input-trace.jsonl');
          fs.copyFileSync(trace, path.join(output, `${scenario.name}-native-input.jsonl`));
          const records = fs.readFileSync(trace, 'utf8').trim().split('\n').map(line => JSON.parse(line));
          const installed = records.filter(record => record.event === 'installed');
          const hooks = ['single.replacements', 'single.writes', 'single.availability', 'multi.replacements', 'multi.writes', 'multi.availability'];
          if (!installed.length || installed.some(record => hooks.some(key => record[key] !== true))) throw new Error('Native input trace hooks were not installed.');
        } catch (error) { inputTraceErrors.push(error.message); console.error(`Input trace: ${error.message}`); }
      }
      if (inputTraceErrors.length) throw new Error('Native input trace is incomplete.');
      scenarios.at(-1).testSeconds = (Date.now() - started) / 1000;
      run('xcrun', ['simctl', 'shutdown', simulator]);
      run('xcrun', ['simctl', 'delete', simulator]);
      simulator = undefined;
    }
    if (unexpected.length) throw new Error(`Unexpected fixture endpoints: ${JSON.stringify(unexpected)}`);
    if (!requests.some(item => item.route === '/_allauth/app/v1/auth/code/confirm') || !requests.some(item => item.method === 'DELETE')) throw new Error('Account flow did not traverse the real native HTTP client.');
    if (requests.some(item => ['/v1/text', '/v1/text-actions/execute'].includes(item.route) && ['cancel', 'off', 'a\nb\nc'].includes(item.value.text))) throw new Error('Cancelled or deactivated discovery sent a late processing POST.');
    exitCode = 0;
  } catch (error) { console.error(error.message); } finally {
    for (const result of results) if (fs.existsSync(result.path)) spawnSync('xcrun', ['xcresulttool', 'export', 'attachments', '--path', result.path, '--output-path', path.join(output, 'captures', result.name)], { stdio: 'inherit' });
    for (const [name, hash] of preserved) if (fingerprint(path.join(original, name)) !== hash) { console.error('Production generated project changed during app UI testing.'); exitCode = 1; }
    fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify({ exitCode, diagnosticInputTrace: true, inputTraceErrors, completeAppAcceptance: false, sourceProjectUnchanged: preserved.every(([name, hash]) => fingerprint(path.join(original, name)) === hash), buildSeconds, testRun, requests, unexpected, scenarios }, null, 2));
    service.release();
    await new Promise(resolve => server.close(resolve));
    if (simulator) { spawnSync('xcrun', ['simctl', 'shutdown', simulator]); spawnSync('xcrun', ['simctl', 'delete', simulator]); }
    if (path.dirname(fixture) === root && path.basename(fixture).startsWith('.app-ui-')) fs.rmSync(fixture, { recursive: true, force: true });
    process.exitCode = exitCode;
  }
}

module.exports = { requirePassedTest };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
