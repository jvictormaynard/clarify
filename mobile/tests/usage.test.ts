import assert from 'node:assert/strict';
import test from 'node:test';
import { formatUsageReset, usageProgress } from '../src/usage.ts';

const now = Date.parse('2026-10-25T12:00:00Z');
const weekly = {
  schema_version: 2, period_start: '2026-10-19T00:00:00Z', reset_at: '2026-10-26T00:00:00Z',
  used_percent: 12.5, remaining_percent: 82.5, reserved_percent: 5,
  allocation_status: 'available', hosted_available: true,
};

test('weekly usage preserves server percentages without counting reservations as use', () => {
  assert.deepEqual(usageProgress(weekly, now), weekly);
  assert.deepEqual(usageProgress({ ...weekly, used_percent: 100, remaining_percent: 0, reserved_percent: 0, hosted_available: false }, now),
    { ...weekly, used_percent: 100, remaining_percent: 0, reserved_percent: 0, hosted_available: false });
});

test('legacy minutes and missing or malformed quotas never become a weekly allowance', () => {
  for (const invalid of [undefined, null, [], 0, { used_ms: 450000, limit_ms: 18000000 }, {},
    { ...weekly, schema_version: 1 }, { ...weekly, allocation_status: 'unknown' },
    { ...weekly, allocation_status: { toString: null } },
    { ...weekly, hosted_available: 'true' }, { ...weekly, reset_at: 'not a date' },
    { ...weekly, period_start: '2026-02-30T00:00:00Z' },
    { ...weekly, period_start: weekly.reset_at }, { ...weekly, period_start: '2026-10-27T00:00:00Z' },
    { ...weekly, reset_at: '2026-10-26T00:00:00' }]) {
    assert.equal(usageProgress(invalid, now), null);
  }
  for (const field of ['used_percent', 'remaining_percent', 'reserved_percent']) {
    for (const invalid of [-1, 101, NaN, Infinity, '25', null, undefined]) {
      assert.equal(usageProgress({ ...weekly, [field]: invalid }, now), null);
    }
  }
});

test('a cached allowance expires at its reset rather than promising another week', () => {
  assert.equal(usageProgress(weekly, Date.parse(weekly.reset_at)), null);
});

test('unallocated accounts keep their status and do not receive a fabricated allowance', () => {
  for (const allocation_status of ['waiting', 'unfunded', 'inactive']) {
    const usage = { ...weekly, used_percent: 0, remaining_percent: 0, reserved_percent: 0,
      allocation_status, hosted_available: false };
    assert.deepEqual(usageProgress(usage, now), usage);
  }
});

test('reset time uses the device timezone, including the prior local calendar day', () => {
  const reset = formatUsageReset(weekly.reset_at, 'en', 'America/Los_Angeles');
  assert.match(reset, /Oct 25, 2026/);
  assert.match(reset, /5:00 PM/);
  assert.match(reset, /PDT/);
});
