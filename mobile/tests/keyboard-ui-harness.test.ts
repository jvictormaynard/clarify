import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import type { TestContext } from 'node:test';

const require = createRequire(import.meta.url);
const mobile = fileURLToPath(new URL('../', import.meta.url));
const script = path.join(mobile, 'scripts/test-keyboard-ui.cjs');

function workspace(t: TestContext) {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-ui-harness-test-'));
  t.after(() => fs.rmSync(temporary, { recursive: true, force: true }));
  const root = path.join(temporary, 'mobile');
  for (const directory of ['native/keyboard', 'native/tests', 'modules/clarify-core/ios', 'modules/clarify-core/tests']) {
    fs.cpSync(path.join(mobile, directory), path.join(root, directory), { recursive: true });
  }
  return { temporary, root, fixture: path.join(temporary, 'fixture with spaces'), derived: path.join(temporary, 'derived with spaces') };
}

type Call = { command: string; args: string[]; cwd?: string };
type Options = {
  env?: Record<string, string>;
  platform?: string;
  failure?: string;
  status?: number | null;
  exportStatus?: number;
  zipStatus?: number;
  bundle?: boolean;
};

// Run the CLI with real temporary files and a fake macOS command boundary.
// No simulator, signing identity, account, microphone or provider is accessed.
function run(root: string, options: Options = {}) {
  const calls: Call[] = [];
  const logs: string[] = [];
  const errors: string[] = [];
  let exitCode: number | undefined;
  class Exit extends Error {}
  const spawnSync = (command: string, args: string[], settings: { cwd?: string }) => {
    calls.push({ command, args: Array.from(args), cwd: settings.cwd });
    const operation = command === 'xcrun' ? args[1] : command;
    const status = options.failure === operation ? options.status ?? null
      : operation === 'export' ? options.exportStatus ?? 0
      : command === 'zip' ? options.zipStatus ?? 0 : 0;
    if (command === 'xcodebuild' && options.bundle !== false) {
      const result = args[args.indexOf('-resultBundlePath') + 1];
      fs.mkdirSync(result, { recursive: true });
      fs.writeFileSync(path.join(result, 'test-log.txt'), 'test evidence');
    }
    if (operation === 'export') {
      const captures = args[args.indexOf('--output-path') + 1];
      fs.mkdirSync(captures, { recursive: true });
      fs.writeFileSync(path.join(captures, 'capture.txt'), 'partial attachment evidence');
    }
    if (command === 'zip' && status === 0) fs.writeFileSync(args[1], 'archive evidence');
    const stdout = JSON.stringify({ devices: { 'com.apple.CoreSimulator.SimRuntime.iOS-26-5': [
      { name: 'iPhone Test', udid: 'isolated-simulator' },
    ] } });
    return { status, stdout, stderr: status === 0 ? '' : 'synthetic command failure',
      ...(status === null ? { signal: 'SIGTERM' } : {}) };
  };
  try {
    vm.runInNewContext(fs.readFileSync(script, 'utf8'), {
      require: (name: string) => name === 'node:child_process' ? { spawnSync }
        : name === 'node:os' ? { tmpdir: () => path.dirname(root) } : require(name),
      process: { platform: options.platform ?? 'darwin',
        env: { CLARIFY_NATIVE_TESTS: '1', CLARIFY_IOS_RUNTIME: 'iOS-26-5', ...options.env },
        cwd: () => root, exit: (code: number) => { exitCode = code; throw new Exit(); } },
      console: { log: (...items: unknown[]) => logs.push(items.join(' ')),
        error: (...items: unknown[]) => errors.push(items.join(' ')) },
      Buffer,
    }, { filename: script });
  } catch (error) {
    if (!(error instanceof Exit)) throw error;
  }
  return { exitCode, calls, logs, errors };
}

function timings(root: string) {
  return JSON.parse(fs.readFileSync(path.join(root, 'test-results/keyboard-ui-timings.json'), 'utf8'));
}

test('UIKit CLI uses explicit cache paths and requests the full suite and build timing summary', (t) => {
  const w = workspace(t);
  const result = run(w.root, { env: {
    CLARIFY_IOS_UI_FIXTURE_ROOT: w.fixture, CLARIFY_IOS_UI_DERIVED_DATA: w.derived,
  } });
  assert.equal(result.exitCode, 0);
  const build = result.calls.find(call => call.command === 'xcodebuild')!;
  assert.equal(build.cwd, w.fixture);
  assert.equal(build.args[build.args.indexOf('-derivedDataPath') + 1], w.derived);
  assert.ok(build.args.includes('-showBuildTimingSummary'));
  assert.equal(build.args[0], 'test');
  assert.equal(build.args[build.args.indexOf('-scheme') + 1], 'KeyboardUI');
  assert.equal(build.args[build.args.indexOf('-parallel-testing-enabled') + 1], 'NO');
  assert.ok(!build.args.some(argument => /only-testing|skip-testing/.test(argument)));
  const evidence = timings(w.root);
  assert.equal(evidence.schema, 1);
  assert.equal(evidence.exitCode, 0);
  assert.equal(evidence.fixtureRoot, w.fixture);
  assert.equal(evidence.derivedDataPath, w.derived);
  assert.deepEqual(evidence.stages.slice(0, 4).map((stage: { name: string }) => stage.name),
    ['fixture', 'simulator-selection', 'simulator-boot', 'xcodebuild-test']);
  for (const stage of evidence.stages) {
    assert.ok(Number.isFinite(stage.durationSeconds) && stage.durationSeconds >= 0);
    assert.ok(Number.isFinite(Date.parse(stage.startedAt)));
    assert.equal(stage.exitCode, 0);
  }
  assert.ok(result.logs.some(line => line.startsWith('KEYBOARD_UI_STAGE ')));
});

test('a reused fixture removes stale build inputs, refreshes changes and preserves unchanged mtimes', (t) => {
  const w = workspace(t);
  const options = { env: { CLARIFY_IOS_UI_FIXTURE_ROOT: w.fixture } };
  assert.equal(run(w.root, options).exitCode, 0);
  const manifest = path.join(w.fixture, 'Package.swift');
  const unchanged = path.join(w.fixture, 'Tests/KeyboardUITests/KeyboardOpeningDiagnosticTests.swift');
  const originalTime = new Date('2020-01-02T03:04:05Z');
  for (const file of [manifest, unchanged]) fs.utimesSync(file, originalTime, originalTime);
  fs.writeFileSync(path.join(w.fixture, 'Sources/KeyboardUI/Obsolete.swift'), 'stale source');
  fs.writeFileSync(path.join(w.fixture, 'Package@swift-6.0.swift'), 'stale manifest');
  fs.mkdirSync(path.join(w.fixture, 'Tests/ObsoleteTests'), { recursive: true });
  fs.writeFileSync(path.join(w.fixture, 'Tests/ObsoleteTests/OldTests.swift'), 'stale test');
  fs.mkdirSync(path.join(w.fixture, '.build'), { recursive: true });
  fs.writeFileSync(path.join(w.fixture, '.build/cache-token'), 'cached build');
  const changed = '/* changed source */\n' + fs.readFileSync(path.join(w.root, 'native/keyboard/KeyPreview.swift'), 'utf8');
  fs.writeFileSync(path.join(w.root, 'native/keyboard/KeyPreview.swift'), changed);
  fs.renameSync(path.join(w.root, 'test-results'), path.join(w.root, 'first-test-results'));
  assert.equal(run(w.root, options).exitCode, 0);
  for (const file of [manifest, unchanged]) assert.equal(fs.statSync(file).mtimeMs, originalTime.getTime());
  for (const file of ['Sources/KeyboardUI/Obsolete.swift', 'Package@swift-6.0.swift', 'Tests/ObsoleteTests']) {
    assert.equal(fs.existsSync(path.join(w.fixture, file)), false);
  }
  assert.equal(fs.readFileSync(path.join(w.fixture, 'Sources/KeyboardUI/KeyPreview.swift'), 'utf8'), changed);
  assert.equal(fs.readFileSync(path.join(w.fixture, '.build/cache-token'), 'utf8'), 'cached build');
  assert.equal(fs.readFileSync(unchanged, 'utf8'), fs.readFileSync(path.join(w.root, 'native/tests/KeyboardOpeningDiagnosticTests.swift'), 'utf8'));
  assert.match(fs.readFileSync(path.join(w.fixture, 'Tests/KeyboardUITests/AudioClipTests.swift'), 'utf8'), /@testable import KeyboardUI/);
});

test('UIKit setup failures retain the command exit code and do not start tests', (t) => {
  for (const [failure, status] of [['defaults', 9], ['list', 10], ['bootstatus', 11]] as const) {
    const w = workspace(t);
    const result = run(w.root, { failure, status });
    assert.equal(result.exitCode, status, failure);
    assert.ok(!result.calls.some(call => call.command === 'xcodebuild'));
    const evidence = timings(w.root);
    assert.equal(evidence.exitCode, status);
    assert.equal(evidence.stages.at(-1).exitCode, status);
  }
});

test('failed tests retain the xcresult and partial attachments even when artifact commands fail', (t) => {
  const w = workspace(t);
  const result = run(w.root, { failure: 'xcodebuild', status: 65, exportStatus: 12, zipStatus: 13 });
  assert.equal(result.exitCode, 65);
  assert.ok(result.calls.some(call => call.command === 'xcrun' && call.args[0] === 'xcresulttool'));
  assert.ok(result.calls.some(call => call.command === 'zip'));
  assert.equal(fs.readFileSync(path.join(w.root, 'test-results/KeyboardUI.xcresult/test-log.txt'), 'utf8'), 'test evidence');
  assert.equal(fs.readFileSync(path.join(w.root, 'test-results/keyboard-captures/capture.txt'), 'utf8'), 'partial attachment evidence');
  const evidence = timings(w.root);
  assert.equal(evidence.exitCode, 65);
  assert.equal(evidence.stages.find((stage: { name: string }) => stage.name === 'xcodebuild-test').exitCode, 65);
});

test('artifact failures cannot turn a successful test command into a successful harness', (t) => {
  for (const options of [{ exportStatus: 12 }, { zipStatus: 13 }]) {
    const w = workspace(t);
    const result = run(w.root, options);
    assert.equal(result.exitCode, options.exportStatus ?? options.zipStatus);
    assert.ok(result.calls.some(call => call.command === 'zip'));
    assert.equal(timings(w.root).exitCode, result.exitCode);
  }
});

test('a terminated test command fails and saves timings without requiring an xcresult', (t) => {
  const w = workspace(t);
  const result = run(w.root, { failure: 'xcodebuild', status: null, bundle: false });
  assert.equal(result.exitCode, 1);
  assert.ok(!result.calls.some(call => call.command === 'zip'));
  assert.equal(timings(w.root).exitCode, 1);
  assert.ok(result.errors.some(line => line.includes('SIGTERM')));
});

test('a stable fixture refuses a nonempty directory that the harness does not own', (t) => {
  const w = workspace(t);
  fs.mkdirSync(w.fixture);
  const sentinel = path.join(w.fixture, 'keep.txt');
  fs.writeFileSync(sentinel, 'unrelated files');
  const result = run(w.root, { env: { CLARIFY_IOS_UI_FIXTURE_ROOT: w.fixture } });
  assert.equal(result.exitCode, 1);
  assert.equal(fs.readFileSync(sentinel, 'utf8'), 'unrelated files');
  assert.equal(result.calls.length, 0);
});

test('invalid or overlapping cache paths fail before commands or source changes', (t) => {
  const w = workspace(t);
  const source = path.join(w.root, 'native/keyboard/KeyPreview.swift');
  const content = fs.readFileSync(source, 'utf8');
  const invalidSettings: Record<string, string>[] = [
    { CLARIFY_IOS_UI_FIXTURE_ROOT: 'relative-fixture' },
    { CLARIFY_IOS_UI_DERIVED_DATA: 'relative-derived' },
    { CLARIFY_IOS_UI_FIXTURE_ROOT: w.root },
    { CLARIFY_IOS_UI_FIXTURE_ROOT: w.fixture, CLARIFY_IOS_UI_DERIVED_DATA: path.join(w.fixture, 'DerivedData') },
  ];
  for (const env of invalidSettings) {
    const result = run(w.root, { env });
    assert.equal(result.exitCode, 1);
    assert.equal(result.calls.length, 0);
    assert.equal(fs.readFileSync(source, 'utf8'), content);
    fs.renameSync(path.join(w.root, 'test-results'), path.join(w.temporary, `evidence-${Math.random()}`));
  }
});

test('reusing a fixture does not follow source directory links outside the fixture', (t) => {
  const w = workspace(t);
  const options = { env: { CLARIFY_IOS_UI_FIXTURE_ROOT: w.fixture } };
  assert.equal(run(w.root, options).exitCode, 0);
  const source = path.join(w.fixture, 'Sources/KeyboardUI');
  const outside = path.join(w.temporary, 'outside-sources');
  fs.renameSync(source, outside);
  const sentinel = path.join(outside, 'keep.txt');
  fs.writeFileSync(sentinel, 'outside fixture');
  fs.symlinkSync(outside, source, process.platform === 'win32' ? 'junction' : 'dir');
  fs.renameSync(path.join(w.root, 'test-results'), path.join(w.root, 'first-test-results'));
  assert.equal(run(w.root, options).exitCode, 0);
  assert.equal(fs.lstatSync(source).isSymbolicLink(), false);
  assert.equal(fs.readFileSync(sentinel, 'utf8'), 'outside fixture');
  assert.equal(fs.existsSync(path.join(source, 'keep.txt')), false);
});

test('a second run preserves existing evidence and requires a separate output set', (t) => {
  const w = workspace(t);
  assert.equal(run(w.root).exitCode, 0);
  const previous = fs.readFileSync(path.join(w.root, 'test-results/keyboard-ui-timings.json'), 'utf8');
  const result = run(w.root);
  assert.equal(result.exitCode, 1);
  assert.equal(result.calls.length, 0);
  assert.equal(fs.readFileSync(path.join(w.root, 'test-results/keyboard-ui-timings.json'), 'utf8'), previous);
});

test('default invocation retains temporary fixture isolation and the existing platform gate', (t) => {
  const w = workspace(t);
  const result = run(w.root);
  assert.equal(result.exitCode, 0);
  const build = result.calls.find(call => call.command === 'xcodebuild')!;
  assert.ok(build.cwd!.startsWith(path.join(w.temporary, 'clarify-keyboard-ui-')));
  assert.ok(!build.args.includes('-derivedDataPath'));
  t.after(() => fs.rmSync(build.cwd!, { recursive: true, force: true }));
  const skipped = run(w.root, { platform: 'linux' });
  assert.equal(skipped.exitCode, 0);
  assert.equal(skipped.calls.length, 0);
});
