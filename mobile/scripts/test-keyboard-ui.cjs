const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { performance } = require('node:perf_hooks');
const { spawnSync } = require('node:child_process');

if (process.platform !== 'darwin' || !(process.env.CLARIFY_NATIVE_TESTS === '1' || ['simulator', 'production'].includes(process.env.EAS_BUILD_PROFILE))) {
  console.log('UIKit simulator tests require macOS and CLARIFY_NATIVE_TESTS=1 or an EAS iOS build profile.');
  process.exit(0);
}

const fixtureMarker = '.clarify-keyboard-ui-fixture';
const fixtureVersion = 'clarify-keyboard-ui-fixture-v1\n';

function absoluteSetting(name) {
  const value = process.env[name];
  if (!value) return undefined;
  if (!path.isAbsolute(value)) throw new Error(`${name} must be an absolute path.`);
  return path.resolve(value);
}

function contains(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}

function fixtureFiles(root) {
  const files = new Map();
  const copy = (source, destination) => files.set(destination, fs.readFileSync(path.join(root, source)));
  for (const name of ['KeyboardViewController.swift', 'DictationEdit.swift', 'KeyGridView.swift', 'KeyPreview.swift', 'TypingAssistant.swift', 'HostActivation.swift']) {
    copy(`native/keyboard/${name}`, `Sources/KeyboardUI/${name}`);
  }
  for (const name of ['KeyboardState.swift', 'SharedState.swift', 'KeyboardVocabulary.swift', 'TypingCorrection.swift', 'HapticFeedback.swift', 'ClarifyMark.swift', 'ActivationRequest.swift', 'LocalLibrary.swift', 'Snippets.swift', 'KeyStore.swift', 'MicrophoneFailure.swift', 'AudioClipWriter.swift', 'Localization.swift', 'KeyboardOpeningDiagnostic.swift']) {
    copy(`modules/clarify-core/ios/${name}`, `Sources/KeyboardUI/${name}`);
  }
  for (const name of ['KeyboardUITests.swift', 'MicrophoneFailureTests.swift', 'KeyboardOpeningDiagnosticTests.swift']) {
    copy(`native/tests/${name}`, `Tests/KeyboardUITests/${name}`);
  }
  for (const name of ['AudioClipTests.swift', 'LibraryTests.swift']) {
    files.set(`Tests/KeyboardUITests/${name}`, Buffer.from(fs.readFileSync(path.join(root, 'modules/clarify-core/tests', name), 'utf8')
      .replace('@testable import ClarifyContracts', '@testable import KeyboardUI')));
  }
  for (const name of ['KBHostArbiterHook', 'KeyboardHeightSync']) {
    copy(`native/keyboard/${name}.m`, `Sources/KeyboardHostSupport/${name}.m`);
    copy(`native/keyboard/${name}.h`, `Sources/KeyboardHostSupport/include/${name}.h`);
  }
  files.set('Package.swift', Buffer.from(`// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "KeyboardUI", platforms: [.iOS(.v16)],
  products: [.library(name: "KeyboardUI", targets: ["KeyboardUI"])],
  targets: [.target(name: "KeyboardHostSupport"), .target(name: "KeyboardUI", dependencies: ["KeyboardHostSupport"], linkerSettings: [.linkedLibrary("sqlite3")]), .testTarget(name: "KeyboardUITests", dependencies: ["KeyboardUI", "KeyboardHostSupport"])])
`));
  return files;
}

// Only a marked, dedicated fixture can be reused. Remove obsolete inputs,
// including alternate Swift manifests. Unchanged files keep their mtimes.
function synchronizeFixture(fixture, files) {
  if (fs.existsSync(fixture) && (!fs.lstatSync(fixture).isDirectory() || fs.lstatSync(fixture).isSymbolicLink())) {
    throw new Error('The UIKit fixture must be a directory, not a symbolic link.');
  }
  fs.mkdirSync(fixture, { recursive: true });
  const marker = path.join(fixture, fixtureMarker);
  if (fs.readdirSync(fixture).length && (!fs.existsSync(marker) || fs.lstatSync(marker).isSymbolicLink()
      || !fs.lstatSync(marker).isFile() || fs.readFileSync(marker, 'utf8') !== fixtureVersion)) {
    throw new Error('The UIKit fixture directory is not owned by this harness. Use an empty dedicated directory.');
  }
  if (!fs.existsSync(marker)) fs.writeFileSync(marker, fixtureVersion);
  function sync(directory, inventory, preserved = []) {
    const names = new Set(Array.from(inventory.keys(), name => name.split('/')[0]));
    for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
      if (!names.has(item.name) && !(preserved.includes(item.name) && !item.isSymbolicLink())) {
        fs.rmSync(path.join(directory, item.name), { recursive: true, force: true });
      }
    }
    for (const name of names) {
      const target = path.join(directory, name);
      const stat = fs.lstatSync(target, { throwIfNoEntry: false });
      if (inventory.has(name)) {
        const content = inventory.get(name);
        if (stat?.isFile() && !stat.isSymbolicLink() && fs.readFileSync(target).equals(content)) continue;
        if (stat) fs.rmSync(target, { recursive: true, force: true });
        fs.writeFileSync(target, content);
      } else {
        if (stat && (!stat.isDirectory() || stat.isSymbolicLink())) fs.rmSync(target, { recursive: true, force: true });
        fs.mkdirSync(target, { recursive: true });
        sync(target, new Map(Array.from(inventory).filter(([file]) => file.startsWith(`${name}/`))
          .map(([file, content]) => [file.slice(name.length + 1), content])));
      }
    }
  }
  sync(fixture, files, [fixtureMarker, '.build', '.swiftpm']);
}

function command(name, args, options = {}) {
  const result = spawnSync(name, args, { stdio: 'inherit', ...options });
  if (result.status !== 0) {
    if (result.stderr) console.error(result.stderr);
    throw Object.assign(new Error(`${name} failed (${result.status ?? result.signal ?? result.error?.message ?? 'no exit status'}).`),
      { exitCode: result.status ?? 1 });
  }
  return result;
}

function main() {
  const root = process.cwd();
  const output = path.join(root, 'test-results');
  const resultPath = path.join(output, 'KeyboardUI.xcresult');
  const captures = path.join(output, 'keyboard-captures');
  const archive = path.join(output, 'keyboard-ui.zip');
  const timingsPath = path.join(output, 'keyboard-ui-timings.json');
  // Do not mix a previous run's evidence with this run.
  if ([resultPath, captures, archive, timingsPath].some(file => fs.existsSync(file))) {
    console.error('UIKit evidence already exists. Move the previous keyboard test outputs before another run.');
    return 1;
  }
  fs.mkdirSync(output, { recursive: true });
  const evidence = { schema: 1, startedAt: new Date().toISOString(), stages: [], exitCode: 0 };
  const code = error => Number.isInteger(error.exitCode) && error.exitCode > 0 ? error.exitCode : 1;
  function measure(name, operation) {
    const stage = { name, startedAt: new Date().toISOString(), exitCode: 0 };
    const start = performance.now();
    console.log(`KEYBOARD_UI_STAGE ${JSON.stringify({ name, event: 'start', startedAt: stage.startedAt })}`);
    try { return operation(); }
    catch (error) { stage.exitCode = code(error); throw error; }
    finally {
      stage.durationSeconds = (performance.now() - start) / 1000;
      evidence.stages.push(stage);
      console.log(`KEYBOARD_UI_STAGE ${JSON.stringify({ ...stage, event: 'end' })}`);
    }
  }
  function attempt(name, operation) {
    try { return measure(name, operation); }
    catch (error) {
      console.error(error.message);
      if (evidence.exitCode === 0) evidence.exitCode = code(error);
    }
  }
  try {
    const fixture = measure('fixture', () => {
      const stable = absoluteSetting('CLARIFY_IOS_UI_FIXTURE_ROOT');
      const derived = absoluteSetting('CLARIFY_IOS_UI_DERIVED_DATA');
      const directory = stable ?? fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-keyboard-ui-'));
      if (contains(directory, root) || (derived && (contains(directory, derived) || contains(derived, directory)))) {
        throw new Error('The UIKit fixture must be separate from the source root and DerivedData.');
      }
      evidence.fixtureRoot = directory;
      evidence.derivedDataPath = derived ?? null;
      synchronizeFixture(directory, fixtureFiles(root));
      return directory;
    });
    const device = measure('simulator-selection', () => {
      command('defaults', ['write', 'com.apple.iphonesimulator', 'ConnectHardwareKeyboard', '-bool', 'NO']);
      const devices = command('xcrun', ['simctl', 'list', 'devices', 'available', '--json'], { encoding: 'utf8', stdio: 'pipe' });
      const runtimes = Object.entries(JSON.parse(devices.stdout).devices).filter(([runtime]) => !process.env.CLARIFY_IOS_RUNTIME || runtime.startsWith(`com.apple.CoreSimulator.SimRuntime.${process.env.CLARIFY_IOS_RUNTIME}`));
      const selected = runtimes.flatMap(([, items]) => items).find(item => item.name.startsWith('iPhone'));
      if (!selected) throw new Error('No matching iPhone simulator is available.');
      evidence.simulator = { runtime: runtimes.find(([, items]) => items.some(item => item.udid === selected.udid))[0], device: selected.name, udid: selected.udid };
      console.log(JSON.stringify(evidence.simulator));
      return selected;
    });
    measure('simulator-boot', () => command('xcrun', ['simctl', 'bootstatus', device.udid, '-b']));
    const derivedArgs = evidence.derivedDataPath ? ['-derivedDataPath', evidence.derivedDataPath] : [];
    measure('xcodebuild-test', () => command('xcodebuild', ['test', '-scheme', 'KeyboardUI',
      '-destination', `platform=iOS Simulator,id=${device.udid}`, '-parallel-testing-enabled', 'NO',
      ...derivedArgs, '-showBuildTimingSummary', '-resultBundlePath', resultPath, 'CODE_SIGNING_ALLOWED=NO'], { cwd: fixture }));
  } catch (error) {
    evidence.exitCode = code(error);
    console.error(error.message);
  } finally {
    // Export and archive after test failure too. Keep the original bundle and
    // any partial attachments even if either artifact command fails.
    if (fs.existsSync(resultPath)) {
      attempt('attachments', () => command('xcrun', ['xcresulttool', 'export', 'attachments', '--path', resultPath, '--output-path', captures]));
      attempt('archive', () => command('zip', ['-qr', archive, 'KeyboardUI.xcresult',
        ...(fs.existsSync(captures) ? ['keyboard-captures'] : [])], { cwd: output }));
    }
    try { fs.writeFileSync(timingsPath, `${JSON.stringify(evidence, null, 2)}\n`); }
    catch (error) {
      console.error(`Could not save UIKit timings: ${error.message}`);
      if (evidence.exitCode === 0) evidence.exitCode = 1;
    }
    console.log(`KEYBOARD_UI_RESULT ${JSON.stringify(evidence)}`);
  }
  return evidence.exitCode;
}

process.exit(main());
