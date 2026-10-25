import assert from 'node:assert/strict';
import { test } from 'node:test';
import { guideCompletion, guideTransition, initialGuide } from '../src/quick-start.ts';

const practiceStep = () => guideTransition(guideTransition(initialGuide(), 'confirm-keyboard', false), 'continue-microphone', true);

test('opening or returning from Settings never confirms keyboard installation', () => {
  const progress = initialGuide();
  assert.deepEqual(guideTransition(progress, 'settings-returned', true), progress);
  assert.equal(progress.keyboardConfirmed, false);
});

test('a manual keyboard confirmation leads to the microphone step', () => {
  const progress = guideTransition(initialGuide(), 'confirm-keyboard', false);
  assert.equal(progress.step, 'microphone');
  assert.equal(progress.keyboardConfirmed, true);
});

test('a denied or inactive microphone cannot be shown as ready for practice', () => {
  const progress = guideTransition(initialGuide(), 'confirm-keyboard', false);
  assert.deepEqual(guideTransition(progress, 'continue-microphone', false), progress);
  assert.equal(guideTransition(progress, 'continue-microphone', true).step, 'practice');
});

test('practice needs nonempty text from its own input before continuing', () => {
  const practice = practiceStep();
  assert.equal(guideCompletion(practice, 'confirmed', ''), null);
  assert.equal(guideCompletion(practice, 'confirmed', '   \n\t'), null);
  assert.equal(guideCompletion(practice, 'confirmed', '  Oi, tudo bem?  '), true);
});

test('editing or clearing the practice input recalculates readiness', () => {
  const practice = practiceStep();
  assert.equal(guideCompletion(practice, 'confirmed', 'Um teste'), true);
  assert.equal(guideCompletion(practice, 'confirmed', ' '), null);
  assert.equal(guideCompletion(practice, 'confirmed', ''), null);
  assert.equal(guideCompletion(practice, 'confirmed', 'Outro teste'), true);
});

test('input cannot complete a keyboard or microphone setup step', () => {
  const microphone = guideTransition(initialGuide(), 'confirm-keyboard', true);
  assert.equal(guideCompletion(initialGuide(), 'confirmed', 'Um teste'), null);
  assert.equal(guideCompletion(microphone, 'confirmed', 'Um teste'), null);
  assert.equal(guideTransition(practiceStep(), 'back', true).step, 'microphone');
});

test('leaving the guide does not claim successful practice', () => {
  assert.equal(guideCompletion(practiceStep(), 'later', ''), false);
  assert.equal(guideCompletion(practiceStep(), 'later', 'Um teste'), false);
  assert.equal(guideCompletion(initialGuide(), 'later', ''), false);
});
