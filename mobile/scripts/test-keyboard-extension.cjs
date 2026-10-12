const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
if (process.platform !== 'darwin') throw new Error('The installed extension test requires macOS.');
const root = process.cwd(), fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-extension-'));
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.status !== 0) process.exit(result.status ?? 1);
  return result;
}
run('ruby', [path.join(root, 'scripts/keyboard-extension-project.rb'), root, fixture]);
const devices = spawnSync('xcrun', ['simctl', 'list', 'devices', 'available', '--json'], { encoding: 'utf8' });
if (devices.status !== 0) throw new Error(devices.stderr);
const device = Object.values(JSON.parse(devices.stdout).devices).flat().find(item => item.name.startsWith('iPhone'));
if (!device) throw new Error('No iPhone simulator.');
const output = path.join(root, 'test-results'); fs.mkdirSync(output, { recursive: true });
const resultPath = path.join(output, 'KeyboardExtension.xcresult');
const result = spawnSync('xcodebuild', ['test', '-project', path.join(fixture, 'KeyboardExtension.xcodeproj'),
  '-scheme', 'KeyboardExtension', '-destination', `platform=iOS Simulator,id=${device.udid}`,
  '-parallel-testing-enabled', 'NO', '-resultBundlePath', resultPath, 'CODE_SIGNING_ALLOWED=NO'], { stdio: 'inherit' });
if (fs.existsSync(resultPath)) run('xcrun', ['xcresulttool', 'export', 'attachments', '--path', resultPath, '--output-path', path.join(output, 'extension-captures')]);
process.exit(result.status ?? 1);
