const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

if (process.platform !== 'darwin' || !(process.env.CLARIFY_NATIVE_TESTS === '1' || ['simulator', 'production'].includes(process.env.EAS_BUILD_PROFILE))) {
  console.log('UIKit simulator tests require macOS and CLARIFY_NATIVE_TESTS=1 or an EAS iOS build profile.');
  process.exit(0);
}
const root = process.cwd();
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-keyboard-ui-'));
const sources = path.join(fixture, 'Sources/KeyboardUI');
const tests = path.join(fixture, 'Tests/KeyboardUITests');
fs.mkdirSync(sources, { recursive: true }); fs.mkdirSync(tests, { recursive: true });
for (const name of ['KeyboardViewController.swift', 'DictationEdit.swift', 'KeyGridView.swift', 'KeyPreview.swift', 'TypingAssistant.swift', 'HostActivation.swift']) {
  fs.copyFileSync(path.join(root, 'native/keyboard', name), path.join(sources, name));
}
for (const name of ['KeyboardState.swift', 'SharedState.swift', 'KeyboardVocabulary.swift', 'TypingCorrection.swift', 'HapticFeedback.swift', 'ClarifyMark.swift', 'ActivationRequest.swift', 'LocalLibrary.swift', 'KeyStore.swift', 'MicrophoneFailure.swift', 'Localization.swift', 'KeyboardOpeningDiagnostic.swift']) {
  fs.copyFileSync(path.join(root, 'modules/clarify-core/ios', name), path.join(sources, name));
}
fs.copyFileSync(path.join(root, 'native/tests/KeyboardUITests.swift'), path.join(tests, 'KeyboardUITests.swift'));
fs.copyFileSync(path.join(root, 'native/tests/MicrophoneFailureTests.swift'), path.join(tests, 'MicrophoneFailureTests.swift'));
fs.copyFileSync(path.join(root, 'native/tests/KeyboardOpeningDiagnosticTests.swift'), path.join(tests, 'KeyboardOpeningDiagnosticTests.swift'));
fs.writeFileSync(path.join(tests, 'LibraryTests.swift'), fs.readFileSync(path.join(root, 'modules/clarify-core/tests/LibraryTests.swift'), 'utf8').replace('@testable import ClarifyContracts', '@testable import KeyboardUI'));
const support = path.join(fixture, 'Sources/KeyboardHostSupport');
fs.mkdirSync(path.join(support, 'include'), { recursive: true });
fs.copyFileSync(path.join(root, 'native/keyboard/KBHostArbiterHook.m'), path.join(support, 'KBHostArbiterHook.m'));
fs.copyFileSync(path.join(root, 'native/keyboard/KBHostArbiterHook.h'), path.join(support, 'include/KBHostArbiterHook.h'));
fs.copyFileSync(path.join(root, 'native/keyboard/KeyboardHeightSync.m'), path.join(support, 'KeyboardHeightSync.m'));
fs.copyFileSync(path.join(root, 'native/keyboard/KeyboardHeightSync.h'), path.join(support, 'include/KeyboardHeightSync.h'));
fs.writeFileSync(path.join(fixture, 'Package.swift'), `// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "KeyboardUI", platforms: [.iOS(.v16)],
  products: [.library(name: "KeyboardUI", targets: ["KeyboardUI"])],
  targets: [.target(name: "KeyboardHostSupport"), .target(name: "KeyboardUI", dependencies: ["KeyboardHostSupport"], linkerSettings: [.linkedLibrary("sqlite3")]), .testTarget(name: "KeyboardUITests", dependencies: ["KeyboardUI", "KeyboardHostSupport"])])
`);
const softwareKeyboard = spawnSync('defaults', ['write', 'com.apple.iphonesimulator', 'ConnectHardwareKeyboard', '-bool', 'NO'], { stdio: 'inherit' });
if (softwareKeyboard.status !== 0) process.exit(softwareKeyboard.status ?? 1);
const devices = spawnSync('xcrun', ['simctl', 'list', 'devices', 'available', '--json'], { encoding: 'utf8' });
if (devices.status !== 0) { console.error(devices.stderr); process.exit(1); }
const runtimes = Object.entries(JSON.parse(devices.stdout).devices).filter(([runtime]) => !process.env.CLARIFY_IOS_RUNTIME || runtime.startsWith(`com.apple.CoreSimulator.SimRuntime.${process.env.CLARIFY_IOS_RUNTIME}`));
const device = runtimes.flatMap(([, items]) => items).find((item) => item.name.startsWith('iPhone'));
if (!device) { console.error('No matching iPhone simulator is available.'); process.exit(1); }
console.log(JSON.stringify({ runtime: runtimes.find(([, items]) => items.some(item => item.udid === device.udid))[0], device: device.name }));
const boot = spawnSync('xcrun', ['simctl', 'bootstatus', device.udid, '-b'], { stdio: 'inherit' });
if (boot.status !== 0) process.exit(boot.status ?? 1);
const output = path.join(root, 'test-results'); fs.mkdirSync(output, { recursive: true });
const resultPath = path.join(output, 'KeyboardUI.xcresult');
const result = spawnSync('xcodebuild', ['test', '-scheme', 'KeyboardUI',
  '-destination', `platform=iOS Simulator,id=${device.udid}`, '-parallel-testing-enabled', 'NO',
  '-resultBundlePath', resultPath, 'CODE_SIGNING_ALLOWED=NO'],
{ cwd: fixture, stdio: 'inherit' });
if (fs.existsSync(resultPath)) {
  spawnSync('xcrun', ['xcresulttool', 'export', 'attachments', '--path', resultPath,
    '--output-path', path.join(output, 'keyboard-captures')], { stdio: 'inherit' });
  spawnSync('zip', ['-qr', path.join(output, 'keyboard-ui.zip'), 'KeyboardUI.xcresult', 'keyboard-captures'], { cwd: output, stdio: 'inherit' });
}
process.exit(result.status ?? 1);
