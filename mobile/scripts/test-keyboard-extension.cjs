const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const strictOpeningHeight = process.argv.includes('--check-opening-height');
const keyboardHeightDiagnostics = process.env.CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS === '1';
const keyboardHeightBootstrapControl = process.env.CLARIFY_KEYBOARD_HEIGHT_BOOTSTRAP !== undefined;
const keyboardHeightBootstrap = process.env.CLARIFY_KEYBOARD_HEIGHT_BOOTSTRAP ?? 'enabled';
if (!['enabled', 'disabled'].includes(keyboardHeightBootstrap)) throw new Error('Unknown keyboard height bootstrap arm.');
if (keyboardHeightBootstrapControl && (process.env.CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS !== '0' || !strictOpeningHeight)) {
  throw new Error('The startup A/B requires diagnostics=0 and strict opening checks in both arms.');
}
if (process.argv.slice(2).some(argument => argument !== '--check-opening-height')) throw new Error('Unknown installed keyboard test argument.');
if (process.platform !== 'darwin') throw new Error('The installed extension diagnostic requires macOS.');
const root = process.cwd();
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.status !== 0) throw new Error(`${command} failed (${result.status ?? result.error?.message ?? 'unknown error'})`);
  return result;
}
run('defaults', ['write', 'com.apple.iphonesimulator', 'ConnectHardwareKeyboard', '-bool', 'NO']);
const devices = run('xcrun', ['simctl', 'list', 'devices', 'available', '--json'], { encoding: 'utf8', stdio: 'pipe' });
const runtimes = Object.entries(JSON.parse(devices.stdout).devices).filter(([runtime]) => !process.env.CLARIFY_IOS_RUNTIME || runtime.startsWith(`com.apple.CoreSimulator.SimRuntime.${process.env.CLARIFY_IOS_RUNTIME}`));
const device = runtimes.flatMap(([, items]) => items).find(item => item.name.startsWith('iPhone'));
if (!device) throw new Error('No matching iPhone simulator.');
const runtime = runtimes.find(([, items]) => items.some(item => item.udid === device.udid))[0];
console.log(JSON.stringify({ runtime, device: device.name, keyboardHeightDiagnostics, keyboardHeightBootstrap, keyboardHeightBootstrapControl }));
run('xcrun', ['simctl', 'bootstatus', device.udid, '-b']);
const output = path.join(root, 'test-results'); fs.mkdirSync(output, { recursive: true });
const results = fs.mkdtempSync(path.join(output, 'installed-keyboard-'));
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-extension-'));
let exitCode = 1;
let recording;
let heightSyncSourceProof = null;
let heightSyncSourceVerified = false;
try {
  run('ruby', [path.join(root, 'scripts/keyboard-extension-project.rb'), root, fixture, String(strictOpeningHeight)]);
  if (!keyboardHeightDiagnostics) {
    const source = fs.readFileSync(path.join(root, 'native/keyboard/KeyboardViewController.swift'));
    const generated = fs.readFileSync(path.join(fixture, 'KeyboardViewController.swift'));
    if (!source.equals(generated)) throw new Error('The distribution fixture must use the unmodified keyboard controller.');
  }
  const productionHeightSync = fs.readFileSync(path.join(root, 'native/keyboard/KeyboardHeightSync.m'));
  const compiledHeightSync = fs.readFileSync(path.join(fixture, 'KeyboardHeightSync.m'));
  const bootstrapAnchor = Buffer.from('@implementation ClarifyKeyboardHeightSyncBootstrap\n+ (void)load {\n');
  const anchorIndex = productionHeightSync.indexOf(bootstrapAnchor);
  if (anchorIndex < 0 || productionHeightSync.indexOf(bootstrapAnchor, anchorIndex + 1) >= 0) {
    throw new Error('Expected exactly one production height bootstrap anchor.');
  }
  const insertAt = anchorIndex + bootstrapAnchor.length;
  const expectedHeightSync = keyboardHeightBootstrap === 'disabled'
    ? Buffer.concat([productionHeightSync.subarray(0, insertAt), Buffer.from('    return;\n'), productionHeightSync.subarray(insertAt)])
    : productionHeightSync;
  if (!compiledHeightSync.equals(expectedHeightSync)) throw new Error('The compiled height module does not match the selected bootstrap arm.');
  heightSyncSourceProof = JSON.parse(fs.readFileSync(path.join(fixture, 'KeyboardHeightSync-build.json'), 'utf8'));
  const sha256 = source => createHash('sha256').update(source).digest('hex');
  if (heightSyncSourceProof.bootstrap !== keyboardHeightBootstrap || heightSyncSourceProof.bootstrapControl !== keyboardHeightBootstrapControl ||
      heightSyncSourceProof.diagnostics !== keyboardHeightDiagnostics || heightSyncSourceProof.anchorMatches !== 1 ||
      heightSyncSourceProof.productionSHA256 !== sha256(productionHeightSync) || heightSyncSourceProof.compiledSHA256 !== sha256(compiledHeightSync)) {
    throw new Error('The height module provenance does not match the compiled source.');
  }
  heightSyncSourceVerified = true;
  const derived = path.join(fixture, 'DerivedData');
  run('xcodebuild', ['build', '-project', path.join(fixture, 'KeyboardExtension.xcodeproj'), '-scheme', 'ActivationContainer',
    '-configuration', 'Release', '-destination', `platform=iOS Simulator,id=${device.udid}`, '-derivedDataPath', derived, 'CODE_SIGNING_ALLOWED=NO']);
  run('xcrun', ['simctl', 'install', device.udid, path.join(derived, 'Build/Products/Release-iphonesimulator/ActivationContainer.app')]);
  run('xcrun', ['simctl', 'launch', device.udid, 'com.clarify.fixture.container']);
  const ready = path.join(fixture, 'Shared/container-ready.json');
  function waitForFile(file) {
    const deadline = Date.now() + 5000;
    while (!fs.existsSync(file) && Date.now() < deadline) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
    if (!fs.existsSync(file)) throw new Error(`The isolated container did not publish ${path.basename(file)}`);
  }
  waitForFile(ready);
  recording = spawn('xcrun', ['simctl', 'io', device.udid, 'recordVideo', '--codec=h264', '--force', path.join(results, 'opening.mov')], { stdio: 'ignore' });
  recording.on('error', error => console.warn(`Simulator video unavailable: ${error.message}`));
  // URL delivery has its own UI test. A routing failure must not prevent the
  // independent keyboard acceptance test from collecting its display frames.
  const resultPath = path.join(results, 'KeyboardExtension.xcresult');
  const result = spawnSync('xcodebuild', ['test', '-project', path.join(fixture, 'KeyboardExtension.xcodeproj'),
    '-scheme', 'KeyboardExtension', '-configuration', 'Release', '-destination', `platform=iOS Simulator,id=${device.udid}`, '-derivedDataPath', derived,
    '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never',
    '-test-timeouts-enabled', 'YES', '-maximum-test-execution-time-allowance', '300',
    '-resultBundlePath', resultPath, 'CODE_SIGNING_ALLOWED=NO'], { stdio: 'inherit', timeout: 600000, killSignal: 'SIGINT' });
  exitCode = result.status ?? 1;
  if (fs.existsSync(resultPath)) run('xcrun', ['xcresulttool', 'export', 'attachments', '--path', resultPath, '--output-path', path.join(results, 'captures')]);
} catch (error) {
  exitCode = 1;
  throw error;
} finally {
  // SIGINT lets simctl finalize the movie. Its child-process handle keeps Node
  // alive until that write finishes, before the workflow uploads the results.
  recording?.kill('SIGINT');
  spawnSync('xcrun', ['simctl', 'io', device.udid, 'screenshot', path.join(results, 'final-screen.png')], { stdio: 'ignore' });
  const logs = spawnSync('xcrun', ['simctl', 'spawn', device.udid, 'log', 'show', '--style', 'compact', '--last', '15m', '--predicate', 'process IN {"ClarifyKeyboard", "ActivationContainer", "KeyboardHost"}'], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  fs.writeFileSync(path.join(results, 'extension-log.txt'), (logs.stdout ?? '') + (logs.stderr ?? ''));
  const events = path.join(fixture, 'Shared/container-events.json');
  if (fs.existsSync(events)) fs.copyFileSync(events, path.join(results, 'container-events.json'));
  const ready = path.join(fixture, 'Shared/container-ready.json');
  if (fs.existsSync(ready)) fs.copyFileSync(ready, path.join(results, 'container-ready.json'));
  const receipt = path.join(fixture, 'Shared/return-trace.json');
  if (fs.existsSync(receipt)) fs.copyFileSync(receipt, path.join(results, 'activation-return.json'));
  const preflight = path.join(fixture, 'Shared/container-preflight.json');
  if (fs.existsSync(preflight)) fs.copyFileSync(preflight, path.join(results, 'container-preflight.json'));
  for (const name of ['KeyboardViewController.swift', 'KeyboardHeightSync-build.json', 'App.plist', 'Keyboard.plist', 'Container.plist', 'Tests.plist']) {
    const source = path.join(fixture, name);
    if (fs.existsSync(source)) fs.copyFileSync(source, path.join(results, 'generated-' + name));
  }
  for (const name of ['KeyboardHeightSync.m', 'KeyboardHeightSync.h']) {
    fs.copyFileSync(path.join(root, 'native/keyboard', name), path.join(results, 'production-' + name));
  }
  const compiledHeightSync = path.join(fixture, 'KeyboardHeightSync.m');
  if (fs.existsSync(compiledHeightSync)) fs.copyFileSync(compiledHeightSync, path.join(results, 'compiled-KeyboardHeightSync.m'));
  const projectFile = path.join(fixture, 'KeyboardExtension.xcodeproj/project.pbxproj');
  if (fs.existsSync(projectFile)) fs.copyFileSync(projectFile, path.join(results, 'generated-project.pbxproj'));
  // This directory is created by this process and contains only the generated fixture.
  fs.rmSync(fixture, { recursive: true, force: true });
  fs.writeFileSync(path.join(results, 'summary.json'), JSON.stringify({ runtime, device: device.name, strictOpeningHeight, keyboardHeightDiagnostics, keyboardHeightBootstrap, keyboardHeightBootstrapControl, heightSyncSourceVerified, heightSyncSourceProof, exitCode }, null, 2));
}
process.exitCode = exitCode;
