const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
if (process.platform !== 'darwin') throw new Error('The installed extension test requires macOS.');
const root = process.cwd();
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.status !== 0) process.exit(result.status ?? 1);
  return result;
}
run('defaults', ['write', 'com.apple.iphonesimulator', 'ConnectHardwareKeyboard', '-bool', 'NO']);
const devices = spawnSync('xcrun', ['simctl', 'list', 'devices', 'available', '--json'], { encoding: 'utf8' });
if (devices.status !== 0) throw new Error(devices.stderr);
const runtimes = Object.entries(JSON.parse(devices.stdout).devices).filter(([runtime]) => !process.env.CLARIFY_IOS_RUNTIME || runtime.startsWith(`com.apple.CoreSimulator.SimRuntime.${process.env.CLARIFY_IOS_RUNTIME}`));
const device = runtimes.flatMap(([, items]) => items).find(item => item.name.startsWith('iPhone'));
if (!device) throw new Error('No iPhone simulator.');
console.log(JSON.stringify({ runtime: runtimes.find(([, items]) => items.some(item => item.udid === device.udid))?.[0], device: device.name }));
run('xcrun', ['simctl', 'bootstatus', device.udid, '-b']);
const output = path.join(root, 'test-results'); fs.mkdirSync(output, { recursive: true });
const variants = process.env.CLARIFY_KEYBOARD_VARIANTS?.split(',') ?? (process.argv.includes('--compare') ? ['controller-policy'] : ['baseline']);
const results = [];
for (const variant of variants) {
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), `clarify-extension-${variant}-`));
run('ruby', [path.join(root, 'scripts/keyboard-extension-project.rb'), root, fixture], { env: { ...process.env, CLARIFY_KEYBOARD_VARIANT: variant } });
const resultPath = path.join(output, `KeyboardExtension-${variant}.xcresult`);
const result = spawnSync('xcodebuild', ['test', '-project', path.join(fixture, 'KeyboardExtension.xcodeproj'),
  '-scheme', 'KeyboardExtension', '-destination', `platform=iOS Simulator,id=${device.udid}`,
  '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never',
  '-test-timeouts-enabled', 'YES', '-maximum-test-execution-time-allowance', '300',
  '-resultBundlePath', resultPath, 'CODE_SIGNING_ALLOWED=NO'], { stdio: 'inherit', timeout: 600000, killSignal: 'SIGINT' });
if (fs.existsSync(resultPath)) run('xcrun', ['xcresulttool', 'export', 'attachments', '--path', resultPath, '--output-path', path.join(output, `extension-captures-${variant}`)]);
const logs = spawnSync('xcrun', ['simctl', 'spawn', device.udid, 'log', 'show', '--style', 'compact', '--last', '15m', '--predicate', 'process == "ClarifyKeyboard"'], { encoding: 'utf8' });
fs.writeFileSync(path.join(output, `extension-log-${variant}.txt`), (logs.stdout ?? '') + (logs.stderr ?? ''));
results.push({ variant, exitCode: result.status ?? 1 });
}
fs.writeFileSync(path.join(output, 'extension-results.json'), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results)); process.exit(results[0].exitCode);
