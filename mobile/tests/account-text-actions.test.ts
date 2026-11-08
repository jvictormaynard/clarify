import assert from 'node:assert/strict';
import test from 'node:test';
import { actionReplacement, ownsActionLibrary } from '../src/account-text-actions.ts';
import type { AccountTextActionLibrary } from '../modules/clarify-core/index.ts';

const action = { id: 'one', name: 'One', prompt: 'Keep meaning', kind: 'custom' as const, enabled: true, revision: '9223372036854775807' };
const base: AccountTextActionLibrary = { context: 'account-generation', lease: 'lease', revision: '9007199254740993', actions: [action] };
test('management replacements strip server revisions and retain unrelated definitions', () => {
  const changed = { ...action, name: 'Edited', enabled: false };
  const result = actionReplacement(base, changed, action.id);
  assert.deepEqual(result, [{ id: 'one', name: 'Edited', prompt: 'Keep meaning', kind: 'custom', enabled: false }]);
  assert.equal(base.actions[0].name, 'One');
  assert.deepEqual(actionReplacement(base, action, action.id, true), []);
  assert.equal(actionReplacement(base, { ...action, id: 'copy' }, null).length, 2);
  assert.equal('revision' in actionReplacement(base, { ...action, id: 'copy' }, null)[1], false);
  assert.throws(() => actionReplacement({ ...base, actions: [] }, changed, action.id));
});
test('management rejects old account generations, computer mode, and signed-out snapshots', () => {
  assert.equal(ownsActionLibrary(base, base.context, false, true), true);
  for (const [context, computer, signedIn] of [['new-generation', false, true], [base.context, true, true], [base.context, false, false]] as const)
    assert.equal(ownsActionLibrary(base, context, computer, signedIn), false);
});
