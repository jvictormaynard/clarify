const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
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
const selfSizing = process.env.CLARIFY_DIAGNOSTIC_SELF_SIZING === 'off' ? 'off' : 'on';
const variant = process.env.CLARIFY_DIAGNOSTIC_VARIANT || 'production';
console.log(JSON.stringify({ runtime, device: device.name, selfSizing, variant }));
run('xcrun', ['simctl', 'bootstatus', device.udid, '-b']);
const output = path.join(root, 'test-results'); fs.mkdirSync(output, { recursive: true });
const results = fs.mkdtempSync(path.join(output, 'installed-keyboard-'));
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-extension-'));
let exitCode = 1;
try {
  run('ruby', [path.join(root, 'scripts/keyboard-extension-project.rb'), root, fixture]);
  const derived = path.join(fixture, 'DerivedData');
  run('xcodebuild', ['build', '-project', path.join(fixture, 'KeyboardExtension.xcodeproj'), '-scheme', 'ActivationContainer',
    '-destination', `platform=iOS Simulator,id=${device.udid}`, '-derivedDataPath', derived, 'CODE_SIGNING_ALLOWED=NO']);
  run('xcrun', ['simctl', 'install', device.udid, path.join(derived, 'Build/Products/Debug-iphonesimulator/ActivationContainer.app')]);
  run('xcrun', ['simctl', 'launch', device.udid, 'com.clarify.fixture.container']);
  const resultPath = path.join(results, 'KeyboardExtension.xcresult');
  const result = spawnSync('xcodebuild', ['test', '-project', path.join(fixture, 'KeyboardExtension.xcodeproj'),
    '-scheme', 'KeyboardExtension', '-destination', `platform=iOS Simulator,id=${device.udid}`,
    '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never',
    '-test-timeouts-enabled', 'YES', '-maximum-test-execution-time-allowance', '300',
    '-resultBundlePath', resultPath, 'CODE_SIGNING_ALLOWED=NO'], { stdio: 'inherit', timeout: 600000, killSignal: 'SIGINT' });
  exitCode = result.status ?? 1;
  if (fs.existsSync(resultPath)) run('xcrun', ['xcresulttool', 'export', 'attachments', '--path', resultPath, '--output-path', path.join(results, 'captures')]);
  const logs = spawnSync('xcrun', ['simctl', 'spawn', device.udid, 'log', 'show', '--style', 'compact', '--last', '15m', '--predicate', 'process IN {"ClarifyKeyboard", "ActivationContainer", "KeyboardHost"}'], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  fs.writeFileSync(path.join(results, 'extension-log.txt'), (logs.stdout ?? '') + (logs.stderr ?? ''));
} catch (error) {
  exitCode = 1;
  throw error;
} finally {
  const ready = path.join(fixture, 'Shared/container-ready.json');
  if (fs.existsSync(ready)) fs.copyFileSync(ready, path.join(results, 'container-ready.json'));
  const receipt = path.join(fixture, 'Shared/return-trace.json');
  if (fs.existsSync(receipt)) fs.copyFileSync(receipt, path.join(results, 'activation-return.json'));
  // This directory is created by this process and contains only the generated fixture.
  fs.rmSync(fixture, { recursive: true, force: true });
  fs.writeFileSync(path.join(results, 'summary.json'), JSON.stringify({ runtime, device: device.name, selfSizing, variant, exitCode }, null, 2));
}
process.exitCode = exitCode;
