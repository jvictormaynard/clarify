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
const device = Object.values(JSON.parse(devices.stdout).devices).flat().find(item => item.name.startsWith('iPhone'));
if (!device) throw new Error('No iPhone simulator.');
const output = path.join(root, 'test-results'); fs.mkdirSync(output, { recursive: true });
const variants = process.argv.includes('--compare') ? ['baseline', 'initial-size', 'constraints'] : ['baseline'];
const results = [];
for (const variant of variants) {
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), `clarify-extension-${variant}-`));
run('ruby', [path.join(root, 'scripts/keyboard-extension-project.rb'), root, fixture], { env: { ...process.env, CLARIFY_KEYBOARD_VARIANT: variant } });
const resultPath = path.join(output, `KeyboardExtension-${variant}.xcresult`);
const result = spawnSync('xcodebuild', ['test', '-project', path.join(fixture, 'KeyboardExtension.xcodeproj'),
  '-scheme', 'KeyboardExtension', '-destination', `platform=iOS Simulator,id=${device.udid}`,
  '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never', '-resultBundlePath', resultPath, 'CODE_SIGNING_ALLOWED=NO'], { stdio: 'inherit' });
if (fs.existsSync(resultPath)) run('xcrun', ['xcresulttool', 'export', 'attachments', '--path', resultPath, '--output-path', path.join(output, `extension-captures-${variant}`)]);
results.push({ variant, exitCode: result.status ?? 1 });
}
fs.writeFileSync(path.join(output, 'extension-results.json'), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results)); process.exit(results[0].exitCode);
