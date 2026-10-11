import assert from 'node:assert/strict';
import { test } from 'node:test';
import { activationSource, activationToken, systemPath } from '../src/activation-link.ts';

test('keyboard activation is distinct from the existing Live Activity link', () => {
  for (const url of ['clarify://keyboard', 'clarify://keyboard/']) assert.equal(activationSource(url), 'keyboard');
  for (const url of ['clarify://activate', 'clarify://activate/']) assert.equal(activationSource(url), 'activity');
});
test('return handoff accepts only a single UUID nonce on the keyboard URL', () => {
  const token = '6B667449-1E17-49EC-BBC1-A49847972C12';
  const url = `clarify://keyboard?token=${token}`;
  assert.equal(activationSource(url), 'keyboard');
  assert.equal(activationToken(url), token);
  for (const invalid of ['clarify://activate?token=' + token, url + '&return=whatsapp://', 'clarify://keyboard?token=com.whatsapp', url + '&token=' + token]) assert.equal(activationToken(invalid), null);
});
test('unrelated links cannot activate a microphone session', () => {
  for (const url of ['', 'https://clarify.example/keyboard', 'other://keyboard', 'clarify://keyboard?return=app://', 'clarify://keyboard/other']) {
    assert.equal(activationSource(url), null);
  }
});
test('external paths are bounded and restricted before reaching the router decoder', () => {
  assert.equal(systemPath('clarify://dictionary', '1'), '/dictionary');
  assert.equal(systemPath('clarify://settings', '1'), '/settings');
  assert.equal(systemPath('clarify://keyboard', '2'), '/?activate=keyboard&request=2');
  for (const path of ['clarify://%C0%AF%ED%A0%80', 'clarify://dictionary?key=secret', '%'.repeat(10000), 'https://example.com', '/other']) assert.equal(systemPath(path, '1'), '/');
});
