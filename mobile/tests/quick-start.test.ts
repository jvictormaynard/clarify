import assert from 'node:assert/strict';
import { test } from 'node:test';
import { guideCompletion, guideTransition, initialGuide, practiceResult } from '../src/quick-start.ts';

test('opening or returning from Settings never confirms keyboard installation', () => {
  const progress = initialGuide();
  assert.deepEqual(guideTransition(progress, 'settings-returned', true), progress);
  assert.equal(progress.keyboardConfirmed, false);
});

test('a manual keyboard confirmation leads to the microphone step', () => {
  const progress = guideTransition(initialGuide(), 'confirm-keyboard', false);
  assert.equal(progress.step, 'microphone');
  assert.equal(progress.keyboardConfirmed, true);
  assert.equal(progress.insertionConfirmed, false);
});

test('a denied or inactive microphone cannot be shown as ready for practice', () => {
  const progress = guideTransition(initialGuide(), 'confirm-keyboard', false);
  assert.deepEqual(guideTransition(progress, 'continue-microphone', false), progress);
  assert.equal(guideTransition(progress, 'continue-microphone', true).step, 'practice');
});

test('insertion is confirmed manually only from the practice step', () => {
  assert.equal(guideTransition(initialGuide(), 'confirm-insertion', true).insertionConfirmed, false);
  const microphone = guideTransition(initialGuide(), 'confirm-keyboard', true);
  assert.equal(guideTransition(microphone, 'confirm-insertion', true).insertionConfirmed, false);
  const practice = guideTransition(microphone, 'continue-microphone', true);
  assert.equal(practice.insertionConfirmed, false);
  assert.equal(guideTransition(practice, 'confirm-insertion', true).insertionConfirmed, true);
});

test('going back clears a previous insertion confirmation', () => {
  const practice = { step: 'practice' as const, keyboardConfirmed: true, insertionConfirmed: true };
  assert.deepEqual(guideTransition(practice, 'back', true), { step: 'microphone', keyboardConfirmed: true, insertionConfirmed: false });
});

test('the practice preview accepts only a new completed nonempty dictation', () => {
  assert.equal(practiceResult({ phase: 'ready', operationID: 'new', text: '  Um teste.  ' }, 'old'), 'Um teste.');
  for (const snapshot of [
    { phase: 'ready', operationID: 'old', text: 'A previous result.' },
    { phase: 'transcribing', operationID: 'new', text: 'Partial text' },
    { phase: 'error', operationID: 'new', text: 'Failed text' },
    { phase: 'ready', operationID: 'new', text: '   ' },
    { phase: 'ready', text: 'No operation identity' },
  ]) assert.equal(practiceResult(snapshot, 'old'), null);
});

test('interrupted first-use can open Home without claiming successful insertion', () => {
  const microphone = guideTransition(initialGuide(), 'confirm-keyboard', true);
  const practice = guideTransition(microphone, 'continue-microphone', true);
  assert.equal(guideCompletion(practice, 'home'), false);
  assert.equal(guideCompletion(practice, 'later'), false);
  assert.equal(guideCompletion(practice, 'confirmed'), true);
  assert.equal(guideCompletion(initialGuide(), 'confirmed'), null);
});
