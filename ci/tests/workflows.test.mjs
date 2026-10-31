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

test('Windows builds validate Settings and embed the resulting native executable', () => {
  const action = parseDocument(readFileSync(resolve(root, '.github/actions/settings-build/action.yml'), 'utf8')).toJS();
  const commands = action.runs.steps.map(step => step.run || '').join('\n');
  for (const command of ['npm ci', 'npm audit', 'npm run build',
    '../scripts/ci.py --task settings_unit', '../scripts/ci.py --task settings_browser',
    'cargo build --locked']) assert.ok(commands.includes(command), command);
  for (const job of [ci.jobs.package, workflows.get('release.yml').jobs.build_candidate]) {
    const settings = job.steps.findIndex(step => step.uses === './.github/actions/settings-build');
    const packaging = job.steps.findIndex(step => step.run?.includes('scripts\\build.ps1') || step.run?.includes('scripts/build.ps1'));
    assert.ok(settings >= 0 && settings < packaging);
    assert.ok(job.steps[packaging].run.includes('-SettingsExecutable dist\\clarify-settings.exe'));
  }
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
  assert.equal(ios.jobs.native['runs-on'], 'macos-26');
  assert.ok(ios.jobs.native.steps.some(step => step.run?.includes('swift test')));
  assert.ok(ios.jobs.native.steps.some(step => step.run?.includes('test-keyboard-ui.cjs')));
  assert.ok(ios.jobs.build.steps.some(step => step.run?.includes('CODE_SIGNING_ALLOWED=NO')));
  assert.ok(ios.jobs.app.steps.some(step => step.run === 'node scripts/test-app-ui.cjs'));
  assert.deepEqual(ios.permissions, { contents: 'read' });
  assert.deepEqual(new Set(ios.jobs.validate.needs), new Set(['native', 'build', 'app']));
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
