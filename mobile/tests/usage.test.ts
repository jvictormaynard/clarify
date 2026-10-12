import assert from 'node:assert/strict';
import test from 'node:test';
import { usageProgress } from '../src/usage.ts';

test('usage reports actual fractional minutes and keeps a bounded progress bar', () => {
  assert.deepEqual(usageProgress(7.5 * 60000, 300 * 60000), { usedMinutes: 7.5, limitMinutes: 300, percent: 2.5 });
  assert.deepEqual(usageProgress(0, 300 * 60000), { usedMinutes: 0, limitMinutes: 300, percent: 0 });
  assert.deepEqual(usageProgress(310 * 60000, 300 * 60000), { usedMinutes: 310, limitMinutes: 300, percent: 100 });
});

test('missing or invalid quota values never create NaN or a negative bar', () => {
  assert.deepEqual(usageProgress(), { usedMinutes: 0, limitMinutes: 0, percent: 0 });
  for (const invalid of [0, -1, NaN, Infinity]) {
    assert.deepEqual(usageProgress(invalid, invalid), { usedMinutes: 0, limitMinutes: 0, percent: 0 });
    assert.equal(usageProgress(60000, invalid).percent, 0);
  }
});
