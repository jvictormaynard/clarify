import assert from 'node:assert/strict';
import { test } from 'node:test';
import { PressToTalk } from '../src/press-to-talk.ts';

test('leaving a page cancels only a held clip and preserves a locked clip', () => {
  const actions: string[] = [];
  const control = new PressToTalk((action) => actions.push(action));
  control.press(); control.cancelHeld(); control.release();
  assert.deepEqual(actions, ['start', 'cancel']);
  actions.length = 0;
  control.press(); control.move(-28); control.cancelHeld(); control.release();
  assert.deepEqual(actions, ['start', 'lock']);
  control.press();
  assert.deepEqual(actions, ['start', 'lock', 'finish']);
});

test('release ends a held recording exactly once', () => {
  const calls: string[] = [];
  const control = new PressToTalk((action) => calls.push(action));
  control.press(); control.release(); control.release();
  assert.deepEqual(calls, ['start', 'finish']);
});

test('small upward swipe locks; release keeps recording; next press finishes', () => {
  const calls: string[] = [];
  const control = new PressToTalk((action) => calls.push(action));
  control.press(); control.move(-27); control.move(-28); control.move(-80);
  control.release();
  assert.deepEqual(calls, ['start', 'lock']);
  control.press(); control.release();
  assert.deepEqual(calls, ['start', 'lock', 'finish']);
});

test('downward movement does not lock and system cancellation discards', () => {
  const calls: string[] = [];
  const control = new PressToTalk((action) => calls.push(action));
  control.press(); control.move(90); control.cancel(); control.release();
  assert.deepEqual(calls, ['start', 'cancel']);
});

test('blocked input cannot start another recording', () => {
  const calls: string[] = [];
  const control = new PressToTalk((action) => calls.push(action));
  control.press(false); control.release();
  assert.deepEqual(calls, []);
});
