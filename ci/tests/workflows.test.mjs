import { runInNewContext } from 'node:vm';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { parseDocument } from 'yaml';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const workflows = new Map(readdirSync(resolve(root, '.github/workflows'))
  .filter(name => /\.ya?ml$/.test(name)).map(name => {
    const doc = parseDocument(readFileSync(resolve(root, '.github/workflows', name), 'utf8'), { uniqueKeys: true });
    assert.deepEqual(doc.errors, [], name);
    return [name, doc.toJS()];
  }));
const ci = workflows.get('ci.yml');
const tasks = JSON.parse(execFileSync(process.env.CLARIFY_TEST_PYTHON || 'python', ['scripts/ci.py', '--list-tasks'], { cwd: root }));

test('workflow references, needs and action pins are valid', () => {
  for (const [name, workflow] of workflows) {
    assert.ok(workflow.on && workflow.jobs, name);
    const active = new Set();
    function visit(id) {
      assert.ok(workflow.jobs[id], `${name}: missing job ${id}`);
      assert.ok(!active.has(id), `${name}: dependency cycle at ${id}`);
      active.add(id);
      const needs = workflow.jobs[id].needs || [];
      for (const need of Array.isArray(needs) ? needs : [needs]) visit(need);
      active.delete(id);
    }
    for (const [id, job] of Object.entries(workflow.jobs)) {
      visit(id);
      assert.doesNotMatch(JSON.stringify(job.env || {}), /\$\{\{[^}]*\brunner\./,
        `${name}/${id}: runner context is only available after the job starts`);
      for (const step of job.steps || []) {
        if (step.uses?.startsWith('./')) assert.ok(existsSync(resolve(root, step.uses)), step.uses);
        else if (step.uses) assert.match(step.uses, /@[a-f0-9]{40}$/, `${name}/${id}: action must be pinned`);
      }
      if (job.uses?.startsWith('./')) assert.ok(existsSync(resolve(root, job.uses)), job.uses);
    }
  }
});

test('component locks match their declarations and keep runtime inputs inside the component', () => {
  for (const component of ['ci', 'desktop', 'mobile']) {
    const pkg = JSON.parse(readFileSync(resolve(root, component, 'package.json'), 'utf8'));
    const lock = JSON.parse(readFileSync(resolve(root, component, 'package-lock.json'), 'utf8'));
    for (const key of ['dependencies', 'devDependencies', 'optionalDependencies']) {
      assert.deepEqual(lock.packages[''][key] || {}, pkg[key] || {}, `${component}: ${key}`);
    }
    for (const [path, value] of Object.entries(lock.packages)) {
      assert.ok(path !== '..' && !path.startsWith('../'), `${component}: external lock entry ${path}`);
      if (value.link) assert.ok(value.resolved !== '..' && !value.resolved.startsWith('../'), `${component}: parent package link`);
    }
  }
});

test('every selected task has a job and a mandatory terminal result', () => {
  const jobs = tasks.filter(task => task !== 'policy');
  assert.deepEqual(Object.keys(ci.jobs), ['plan', 'policy', ...jobs, 'required'].sort((a,b) => Object.keys(ci.jobs).indexOf(a)-Object.keys(ci.jobs).indexOf(b)));
  assert.deepEqual(new Set(ci.jobs.required.needs), new Set(['plan', 'policy', ...jobs]));
  assert.equal(ci.jobs.required.name, 'CI required');
  assert.equal(ci.jobs.required.if, 'always()');
  for (const id of jobs) {
    assert.equal(ci.jobs[id].if, `needs.plan.outputs.${id} == 'true'`);
    assert.equal(ci.jobs.plan.outputs[id], '$' + '{{ steps.plan.outputs.' + id + ' }}');
  }
  assert.ok(ci.jobs.required.steps.some(step => step.run === 'python scripts/ci.py --check-results'));
});

test('PRs, main, scheduled and manual CI share one entry point', () => {
  assert.deepEqual(ci.on.pull_request.branches, ['main']);
  assert.deepEqual(ci.on.push.branches, ['main']);
  assert.ok(ci.on.schedule.length);
  assert.ok(Object.hasOwn(ci.on, 'workflow_dispatch'));
  assert.ok(!Object.hasOwn(ci.on, 'pull_request_target'));
  assert.deepEqual(ci.permissions, { contents: 'read' });
});

test('Python shards and Qt tests cover Linux and Windows independently', () => {
  assert.deepEqual(ci.jobs.python.strategy.matrix.platform, ['linux', 'windows']);
  assert.deepEqual(ci.jobs.python.strategy.matrix.shard, ['1/2', '2/2']);
  assert.equal(ci.jobs.python.strategy['fail-fast'], false);
  assert.deepEqual(ci.jobs.qt.strategy.matrix.platform, ['linux', 'windows']);
  assert.equal(ci.jobs.qt.strategy['fail-fast'], false);
  assert.ok(ci.jobs.python.steps.some(step => step.run?.includes('scripts/ci.py --task python --shard')));
  assert.ok(ci.jobs.qt.steps.some(step => step.run === 'python scripts/ci.py --task qt'));
});

test('Settings unit tests need neither Qt nor a browser', () => {
  assert.ok(ci.jobs.settings_unit.steps.some(step => step.run === 'python scripts/ci.py --task settings_unit'));
  assert.ok(!ci.jobs.settings_unit.steps.some(step => /playwright|python-env|settings-build/.test(step.uses || step.run || '')));
  const step = ci.jobs.settings_browser.steps.find(step => step.uses === './.github/actions/settings-build');
  assert.equal(step.with.native, 'false');
});

test('Windows builds embed the complete Electron shell without a Rust toolchain', () => {
  const action = parseDocument(readFileSync(resolve(root, '.github/actions/settings-build/action.yml'), 'utf8')).toJS();
  const commands = action.runs.steps.map(step => step.run || '').join('\n');
  for (const command of ['npm ci', 'npm audit', 'npm run build',
    '../scripts/ci.py --task settings_browser',
    'build-desktop.ps1 -Python $env:BUILD_PYTHON -SkipInstall']) assert.ok(commands.includes(command), command);
  for (const job of [ci.jobs.package, workflows.get('release.yml').jobs.build_candidate]) {
    const settings = job.steps.findIndex(step => step.uses === './.github/actions/settings-build');
    const packaging = job.steps.findIndex(step => step.run?.includes('scripts\\build.ps1') || step.run?.includes('scripts/build.ps1'));
    assert.ok(settings >= 0 && settings < packaging);
    assert.ok(job.steps[packaging].run.includes('-DesktopShellDirectory dist\\desktop-shell'));
  }
  assert.ok(!commands.includes('--task settings_unit'), 'Browser/build action must not repeat the independent unit lane');
});

test('Electron native validation is selected, isolated and retains failure evidence', () => {
  const job = ci.jobs.desktop_shell;
  assert.equal(job['runs-on'], 'windows-2025');
  const cache = job.steps.findIndex(step => step.uses === './.github/actions/electron-runtime-cache');
  const node = job.steps.findIndex(step => step.uses?.startsWith('actions/setup-node@'));
  const install = job.steps.findIndex(step => step.run === 'npm ci --no-fund');
  assert.ok(node >= 0 && node < cache && cache < install);
  assert.ok(job.steps.some(step => step.uses === './.github/actions/python-env' && step.with.platform === 'windows' && step.with.qt === 'true'));
  assert.ok(job.steps.some(step => step.run === 'npm ci --no-fund' && step['working-directory'] === 'desktop'));
  assert.ok(job.steps.some(step => step.run === 'python scripts/ci.py --task desktop_shell'));
  const smoke = job.steps.find(step => step.run === 'python scripts/ci.py --task desktop_shell');
  assert.equal(smoke.env.CLARIFY_TEST_ARTIFACTS_DIR, '$' + '{{ runner.temp }}/clarify-electron-evidence');
  const evidence = job.steps.find(step => step.uses?.startsWith('actions/upload-artifact@'));
  assert.equal(evidence.if, 'always()');
  assert.ok(evidence.with.path.includes('clarify-electron-evidence'));
  const action = parseDocument(readFileSync(resolve(root, '.github/actions/settings-build/action.yml'), 'utf8')).toJS();
  assert.ok(!action.runs.steps.some(step => /cargo|rustc|src-tauri/.test(step.run || JSON.stringify(step.with || {}))));
  assert.ok(!action.runs.steps.some(step => /--task desktop_shell|npm run test:electron$/.test(step.run || '')));
  assert.equal(ci.jobs.package.steps.find(step => step.uses === './.github/actions/settings-build').with.test, 'false');
  const release = workflows.get('release.yml').jobs.build_candidate.steps.find(step => step.uses === './.github/actions/settings-build');
  assert.equal(release.with.smoke, 'true');
  assert.ok(action.runs.steps.some(step => step.if?.includes("inputs.smoke == 'true'") && step.run?.includes('npm run test:electron:smoke')));
});

test('destructive installer tests stay on disposable GitHub Windows', () => {
  assert.equal(ci.jobs.installer['runs-on'], 'windows-2025');
  assert.deepEqual(new Set(ci.jobs.installer.needs), new Set(['plan', 'package']));
  assert.equal(ci.jobs.package['runs-on'], 'windows-2025');
  assert.ok(ci.jobs.installer.steps.some(step => step.run?.includes('test-installer.ps1')));
  const script = readFileSync(resolve(root, 'scripts/test-installer.ps1'), 'utf8');
  assert.match(script, /GitHub|GITHUB/);
});

test('native iOS validation includes app, keyboard, library and unsigned compilation', () => {
  const ios = workflows.get('ios-validation.yml');
  assert.match(ios.jobs.native['runs-on'], /CLARIFY_IOS_RUNNER/);
  assert.ok(ios.jobs.native.steps.some(step => step.run?.includes('swift test')));
  assert.ok(ios.jobs.native.steps.some(step => step.run?.includes('test-keyboard-ui.cjs')));
  assert.ok(ios.jobs.native.steps.some(step => step.run === 'node scripts/test-keyboard-extension.cjs'),
    'Installed fixture must remain available for explicit acceptance');
  assert.ok(ios.jobs.build.steps.some(step => step.run?.includes('CODE_SIGNING_ALLOWED=NO')));
  assert.ok(ios.jobs.app.steps.some(step => step.run === 'node scripts/test-app-ui.cjs'));
  assert.deepEqual(ios.jobs.app.strategy?.matrix.profile, ['regular', 'compact']);
  assert.equal(ios.jobs.app.strategy['fail-fast'], false);
  assert.equal(ios.jobs.app.env.CLARIFY_APP_UI_PROFILE, '$' + '{{ matrix.profile }}');
  const appEvidence = ios.jobs.app.steps.find(step => step.uses?.startsWith('actions/upload-artifact@'));
  assert.ok(appEvidence.with.name.includes('$' + '{{ matrix.profile }}'));
  assert.deepEqual(ios.permissions, { contents: 'read' });
  assert.deepEqual(new Set(ios.jobs.validate.needs), new Set(['native', 'build', 'app']));
  const fixtureSetup = './.github/actions/ios-fixture-toolchain';
  assert.ok(ios.jobs.native.steps.some(step => step.uses === fixtureSetup));
  const signed = workflows.get('ios-testflight.yml').jobs.publish.steps;
  const setupIndex = signed.findIndex(step => step.uses === fixtureSetup);
  const fixtureIndex = signed.findIndex(step => step.name === 'Test installed keyboard typing and activation');
  assert.ok(setupIndex >= 0 && setupIndex < fixtureIndex);
  assert.equal(signed[setupIndex].if, signed[fixtureIndex].if);
});

test('focused installed-keyboard validation is manual and cannot report full acceptance', () => {
  const ios = workflows.get('ios-validation.yml');
  assert.equal(ios.on.workflow_dispatch.inputs.activation_only.type, 'boolean');
  assert.equal(ios.on.workflow_dispatch.inputs.activation_only.default, false);
  const full = "github.event_name != 'workflow_dispatch' || inputs.activation_only != true";
  for (const id of ['build', 'app']) assert.equal(ios.jobs[id].if, full);
  assert.equal(ios.jobs.validate.if, `always() && (${full})`);
  const steps = ios.jobs.native.steps;
  for (const step of steps.filter(step => /swift test|test-keyboard-ui.cjs/.test(step.run || ''))) {
    assert.equal(step.if, full);
  }
  const installed = steps.find(step => step.run === 'node scripts/test-keyboard-extension.cjs');
  assert.equal(installed.if, undefined);
  assert.equal(ios.on.workflow_dispatch.inputs.manual_return.default, false);
  for (const manual_return of [false, true]) {
    assert.equal(runInNewContext(installed.env.CLARIFY_INTERNAL_MANUAL_RETURN.slice(3, -2), {
      github: {event_name: 'workflow_dispatch'}, inputs: {activation_only: true, manual_return},
    }), manual_return ? '1' : '0');
  }
  assert.equal(runInNewContext(installed.env.CLARIFY_INTERNAL_MANUAL_RETURN.slice(3, -2), {
    github: {event_name: 'workflow_dispatch'}, inputs: {activation_only: false, manual_return: false},
  }), '0');
  assert.ok(steps.some(step => step.run?.includes('REVIEWED_SOURCE') && step.run.includes('GITHUB_SHA')));
  assert.deepEqual(ios.permissions, { contents: 'read' });
  assert.deepEqual(ios.on.workflow_call, {});
});

test('desktop publication consumes a sealed candidate across a permission boundary', () => {
  const release = workflows.get('release.yml');
  assert.deepEqual(Object.keys(release.on), ['workflow_dispatch']);
  const inputs = release.on.workflow_dispatch.inputs;
  assert.deepEqual(inputs.action.options, ['build-candidate', 'publish-candidate']);
  assert.equal(inputs.action.default, 'build-candidate');
  assert.deepEqual(inputs.channel.options, ['preview', 'stable']);
  assert.equal(inputs.channel.default, 'preview');
  assert.equal(release.jobs.build_candidate.permissions.contents, 'read');
  const publish = release.jobs.publish_candidate;
  assert.equal(publish.environment, 'desktop-publication');
  assert.equal(publish.permissions.contents, 'write');
  assert.ok(!Object.hasOwn(publish.permissions, 'id-token'));
  assert.match(publish.if, /inputs.action == 'publish-candidate'/);
  assert.match(publish.if, /CLARIFY_RELEASE_PUBLICATION_ENABLED == 'true'/);
  assert.match(publish.if, /github.ref == 'refs\/heads\/main'/);
  assert.equal(publish.steps.find(step => step.uses?.startsWith('actions/checkout@')).with.ref,
    '$' + '{{ github.workflow_sha }}');
  assert.ok(!publish.steps.some(step => /npm |pip install|build\.ps1|cargo build|create_portable_update_manifest/.test(step.run || '')));
  const names = release.jobs.build_candidate.steps.map(step => step.name);
  const required = JSON.parse(execFileSync(process.env.CLARIFY_TEST_PYTHON || 'python', [
    '-c', 'import json; from scripts.release_candidate import producer_steps; print(json.dumps({c:producer_steps(c) for c in ("preview","stable")}))',
  ], { cwd: root }));
  for (const expected of Object.values(required)) for (const name of expected) {
    assert.equal(names.filter(value => value === name).length, 1, name);
  }
  assert.ok(names.indexOf('Seal desktop candidate') < names.indexOf('Attest candidate provenance'));
  assert.ok(names.indexOf('Attest candidate provenance') < names.indexOf('Upload desktop candidate'));
  assert.equal(release.concurrency.queue, 'max');
  assert.equal(release.concurrency['cancel-in-progress'], false);
});

test('the server recovery workflow validates by default and publishes only on explicit request', () => {
  const recovery = workflows.get('server-recovery.yml');
  assert.deepEqual(Object.keys(recovery.on), ['workflow_dispatch']);
  assert.equal(recovery.on.workflow_dispatch.inputs.publish_server_image.default, false);
  assert.deepEqual(Object.keys(recovery.jobs), ['server-image']);
  const job = recovery.jobs['server-image'];
  assert.match(job.if, /refs\/heads\/main/);
  for (const name of ['Login with the temporary workflow token', 'Push the verified unique image and record its digest']) {
    assert.equal(job.steps.find(step => step.name === name).if, 'inputs.publish_server_image == true');
  }
  assert.ok(!workflows.has('shared-account.yml'));
  assert.ok(!workflows.has('ios-audio-contracts.yml'));
  assert.ok(!workflows.has('ios-qa.yml'));
  assert.ok(!workflows.has('community-release.yml'));
});

test('TestFlight and App Store use separate explicit actions and one Apple build', () => {
  const flight = workflows.get('ios-testflight.yml');
  assert.deepEqual(Object.keys(flight.on), ['workflow_dispatch']);
  assert.deepEqual(flight.on.workflow_dispatch.inputs.mode.options, ['validate', 'testflight', 'status', 'availability']);
  assert.equal(flight.on.workflow_dispatch.inputs.mode.default, 'validate');
  assert.equal(flight.on.workflow_dispatch.inputs.internal_testing.default, false);
  for (const [job, mode, result] of [
    ['publish', 'testflight', 'publish'], ['publish', 'validate', ''],
    ['availability', 'availability', 'availability'],
  ]) {
    for (const isCancelled of [false, true]) {
      assert.equal(runInNewContext(flight.jobs[job].if, {
        github: { repository: 'jvictormaynard/clarify' }, inputs: { mode },
        needs: { release_gate: { outputs: { result } } },
        always: () => true, cancelled: () => isCancelled,
      }), !isCancelled, `${job} must stop after cancellation and allow its normal path`);
    }
  }
  const appFlow = Object.values(flight.jobs).flatMap(job => job.steps || [])
    .find(step => step.run === 'node scripts/test-app-ui.cjs');
  assert.equal(appFlow.env.CLARIFY_APP_UI_PROFILE,
    "$" + "{{ inputs.mode == 'validate' && inputs.app_ui_compact_only && 'compact' || 'all' }}");
  for (const mode of ['validate', 'testflight', 'status', 'availability']) {
    for (const internal of [false, true]) for (const diagnostic of [false, true]) {
      const inputs = { mode, internal_testing: internal, extension_diagnostic: diagnostic };
      assert.equal(runInNewContext(appFlow.if.slice(3, -2), { inputs }, { timeout: 100 }),
        mode === 'testflight' ? !internal : mode === 'validate' && !diagnostic);
    }
  }
  const flightSteps = Object.values(flight.jobs).flatMap(job => job.steps || []);
  const repeated = ['npm run check', 'npx --yes expo-doctor', 'npm run test:native',
    'node scripts/test-keyboard-ui.cjs'];
  const installed = flightSteps.find(step => step.name === 'Test installed keyboard typing and activation');
  for (const step of [...flightSteps.filter(step => repeated.includes(step.run)), installed]) {
    for (const reuse_ci of [undefined, 'false', 'true']) {
      for (const mode of ['validate', 'testflight']) {
        const expression = step.if.slice(3, -2);
        assert.equal(runInNewContext(expression, {
          inputs: {mode, extension_diagnostic: false}, steps: {resume: {outputs: {reuse_ci}}},
        }), reuse_ci !== 'true');
      }
    }
  }
  const resume = flightSteps.find(step => step.id === 'resume');
  assert.ok(resume.run.includes('--reuse-internal-ci'));
  const native = workflows.get('ios-validation.yml').jobs.native;
  const coverage = native.steps.find(step => step.name === installed.name);
  assert.equal(coverage.if, undefined);
  assert.equal(coverage.run, 'node scripts/test-keyboard-extension.cjs');
  assert.equal(runInNewContext(coverage.env.CLARIFY_INTERNAL_MANUAL_RETURN.slice(3, -2), {
    github: {event_name: 'push'}, inputs: {},
  }), '1');
  const manual = flightSteps.find(step => step.name === 'Test installed keyboard typing and activation').env.CLARIFY_INTERNAL_MANUAL_RETURN;
  for (const mode of ['validate', 'testflight', 'status', 'availability']) for (const internal_testing of [true, false]) {
    assert.equal(runInNewContext(manual.slice(3, -2), {inputs: {mode, internal_testing}}),
      mode === 'testflight' && internal_testing ? '1' : '0');
  }
  for (const name of ['Verify signed app and both extensions', 'Upload directly to App Store Connect',
    'Verify processing and publish to the existing internal group']) {
    const matching = flightSteps.filter(step => step.name === name);
    assert.ok(matching.length > 0, name);
    assert.ok(matching.every(step => !(step.if || '').includes('internal_testing')), name);
  }
  const store = workflows.get('ios-app-store.yml');
  assert.deepEqual(Object.keys(store.on), ['workflow_dispatch']);
  assert.deepEqual(store.on.workflow_dispatch.inputs.action.options, ['prepare-submission', 'prepare-release']);
  for (const name of ['testflight_run_id', 'testflight_run_attempt', 'artifact_id', 'artifact_digest', 'apple_build_id']) {
    assert.equal(store.on.workflow_dispatch.inputs[name].required, true, name);
  }
  assert.ok(Object.values(store.permissions).every(value => value === 'read'));
  assert.ok(!store.jobs.handoff.steps.some(step => /xcodebuild|npm |pod install|upload.*ipa/.test(step.run || '')));
  assert.equal(flight.concurrency.queue, 'max');
  assert.equal(flight.concurrency['cancel-in-progress'], false);
  assert.equal(store.concurrency.group, 'clarify-ios-testflight');
});

// Exercise the trust boundary and toolchain pair, not only a label's presence.
test('optional Bitrise iOS routing isolates forks and selects the matching Xcode', () => {
  function value(expression, github, setting) {
    return runInNewContext(expression.slice(3, -2), { github, vars: { CLARIFY_IOS_RUNNER: setting } }, { timeout: 100 });
  }
  const canonical = 'jvictormaynard/clarify';
  const context = (event, repository = canonical, head = canonical, ref = 'refs/heads/main') => ({
    repository, event_name: event, ref, event: { pull_request: { head: { repo: { full_name: head } } } },
  });
  const validation = workflows.get('ios-validation.yml');
  for (const job of [validation.jobs.native, validation.jobs.build, validation.jobs.app]) {
    for (const [github, setting, bitrise] of [
      [context('push'), 'bitrise', true],
      [context('pull_request'), 'bitrise', true],
      [context('workflow_dispatch'), 'bitrise', true],
      [context('pull_request', canonical, 'external/fork'), 'bitrise', false],
      [context('pull_request_target'), 'bitrise', false],
      [context('push', canonical, canonical, 'refs/heads/other'), 'bitrise', false],
      [context('workflow_dispatch', 'external/fork'), 'bitrise', false],
      [context('push'), '', false],
      [context('push'), 'unknown', false],
    ]) {
      assert.equal(value(job['runs-on'], github, setting), bitrise ? 'bitrise-runner-clarify-ios-validation' : 'macos-26');
      assert.equal(value(job.env.DEVELOPER_DIR, github, setting), bitrise ? '/Applications/Xcode-26.6.0.app/Contents/Developer' : '/Applications/Xcode_26.6.app/Contents/Developer');
    }
  }
  const publish = workflows.get('ios-testflight.yml').jobs.publish;
  for (const [github, setting, bitrise] of [
    [context('workflow_dispatch'), 'bitrise', true],
    [context('workflow_dispatch', 'external/fork'), 'bitrise', false],
    [context('pull_request'), 'bitrise', false],
    [context('workflow_dispatch'), '', false],
  ]) {
    assert.equal(value(publish['runs-on'], github, setting), bitrise ? 'bitrise-runner-clarify-ios-validation' : 'macos-26');
    assert.equal(value(publish.env.DEVELOPER_DIR, github, setting), bitrise ? '/Applications/Xcode-26.6.0.app/Contents/Developer' : '/Applications/Xcode_26.6.app/Contents/Developer');
  }
  const cache = validation.jobs.native.steps.find(step => step.id === 'native-cache');
  assert.match(cache.with.key, /ios-tests-v2-/);
  assert.ok(cache.with.key.includes('env.DEVELOPER_DIR'));
  assert.ok(cache.with['restore-keys'].includes('env.DEVELOPER_DIR'));
});

test('PR and main proof upload is last and authentication has read-only access', () => {
  for (const id of ['plan', 'required']) {
    assert.deepEqual(ci.jobs[id].permissions, {contents: 'read', actions: 'read', 'pull-requests': 'read'});
    assert.equal(ci.jobs[id].steps.find(s => s.uses?.startsWith('actions/checkout@')).with['fetch-depth'], 0);
    const command = ci.jobs[id].steps.find(s => s.run?.includes(id === 'plan' ? '--github-plan' : '--check-results'));
    assert.equal(command.env.GH_TOKEN, '$' + '{{ github.token }}');
  }
  assert.equal(ci.jobs.plan.outputs.reuse, '$' + '{{ steps.plan.outputs.reuse }}');
  const steps = ci.jobs.required.steps;
  assert.ok(steps.at(-3).run.includes('--check-results'));
  assert.ok(steps.at(-2).run.includes('--emit-proof'));
  const upload = steps.at(-1);
  assert.match(upload.uses, /^actions\/upload-artifact@/);
  assert.equal(upload.if, "github.event_name == 'pull_request' || (github.event_name == 'push' && github.repository == 'jvictormaynard/clarify')");
  assert.equal(steps.at(-2).if, upload.if);
  assert.equal(upload.with.name, 'ci-proof-$' + '{{ github.run_id }}-$' + '{{ github.run_attempt }}');
  assert.equal(upload.with['if-no-files-found'], 'error');
});
