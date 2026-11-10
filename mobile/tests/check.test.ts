import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';
const { commands, check } = createRequire(import.meta.url)('../scripts/check.cjs');

test('mobile checks use the configured Python and fixed argument arrays', () => {
  const steps = commands('python with spaces.exe', 'node with spaces.exe');
  assert.equal(steps[0][0], 'python with spaces.exe');
  assert.equal(steps[1][0], 'python with spaces.exe');
  assert.ok(steps.slice(2).every((step: string[]) => step[0] === 'node with spaces.exe'));
  assert.ok(steps[4].includes('tests/check.test.ts'));
  assert.deepEqual(steps[5].slice(-2), ['install', '--check']);
});

test('a failed or unavailable mobile check stops later checks', () => {
  for (const result of [{ status: 7 }, { status: null, error: new Error('missing tool') }]) {
    let calls = 0;
    const code = check(() => { calls += 1; return result; }, { CLARIFY_TEST_PYTHON: 'fixture-python' });
    assert.equal(calls, 1);
    assert.notEqual(code, 0);
  }
});

test('mobile checks disable dotenv and preserve the configured interpreter', () => {
  const calls: unknown[][] = [];
  assert.equal(check((...args: unknown[]) => { calls.push(args); return { status: 0 }; }, {
    CLARIFY_TEST_PYTHON: 'fixture-python',
  }), 0);
  assert.equal(calls[0][0], 'fixture-python');
  const options = calls[0][2] as { env: Record<string, string>; windowsHide: boolean };
  assert.equal(options.env.EXPO_NO_DOTENV, '1');
  assert.equal(options.env.EXPO_NO_TELEMETRY, '1');
  assert.equal(options.windowsHide, true);
});
