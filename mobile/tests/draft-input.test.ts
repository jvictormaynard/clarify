// @ts-nocheck -- Inert JSX checks draft and command ownership; native typing stays in XCTest.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import ts from 'typescript';
import * as guide from '../src/quick-start.ts';

function fixture(file, modules = {}) {
  const source = fs.readFileSync(new URL(`../src/components/${file}.tsx`, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const slots = [], refs = [];
  let stateIndex = 0, refIndex = 0;
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const exports = {};
  vm.runInNewContext(code, { exports, require(name) {
    if (name in modules) return modules[name];
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' };
    if (name === 'react') return {
      useState(initial) {
        const i = stateIndex++;
        if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
        return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
      },
      useRef(initial) { return refs[refIndex++] ??= { current: initial }; },
    };
    if (name === 'react-native') return { TextInput: 'TextInput', Text: 'Text', View: 'View' };
    if (name === '../i18n') return { t: text => text };
    if (name === './ui') return { Button: 'Button', TextButton: 'TextButton', StepContent: 'StepContent', Title: 'Title', ui: {}, usePalette: () => ({}) };
    if (name === './draft-text-input') return { DraftTextInput: 'DraftTextInput' };
    throw new Error(`Unexpected fixture dependency: ${name}`);
  } });
  return (name, props) => { stateIndex = 0; refIndex = 0; return exports[name](props); };
}

function find(tree, id) {
  if (Array.isArray(tree)) return tree.map(node => find(node, id)).find(Boolean);
  if (!tree || typeof tree !== 'object') return undefined;
  return tree.props?.testID === id ? tree : find(tree.props?.children, id);
}

// This adapter models TextInput's documented defaultValue/clear contract.
// It does not simulate UIKit event delivery or prove the native regression fixed.
function nativeField() {
  let mounted = false, props;
  const field = { text: '', focused: true, clears: 0,
    clear() { this.text = ''; this.clears++; },
    type(text) { this.text = text; props.onChangeText?.(text); },
  };
  return { field, render(element) {
    props = element.props;
    if (!mounted) { field.text = props.defaultValue ?? ''; mounted = true; }
    if (typeof props.value === 'string') field.text = props.value;
    if (props.ref) props.ref.current = field;
    return props;
  } };
}

test('a complete native burst survives delayed draft and snapshot renders', () => {
  const render = fixture('draft-text-input'), native = nativeField(), changes = [];
  const props = { initialValue: 'saved', testID: 'input', keyboardType: 'email-address', onChangeText: value => changes.push(value) };
  native.render(render('DraftTextInput', props));
  assert.equal(native.field.text, 'saved');
  native.field.type('clarify-e2e@example.test');
  const updated = native.render(render('DraftTextInput', { ...props, initialValue: 'cl', editable: false }));
  assert.equal(native.field.text, 'clarify-e2e@example.test');
  assert.deepEqual(changes, ['clarify-e2e@example.test']);
  assert.equal(native.field.focused, true);
  assert.equal(updated.testID, 'input');
  assert.equal(updated.keyboardType, 'email-address');
  assert.equal(updated.editable, false);
});

test('new mounts seed a selected draft and explicit clear keeps the same field', () => {
  const inputRef = { current: null }, native = nativeField(), render = fixture('draft-text-input');
  native.render(render('DraftTextInput', { initialValue: 'selected entry', inputRef }));
  assert.equal(native.field.text, 'selected entry');
  inputRef.current.clear();
  native.render(render('DraftTextInput', { initialValue: 'delayed old entry', inputRef }));
  assert.equal(native.field.text, '');
  assert.equal(native.field.clears, 1);
  assert.equal(native.field.focused, true);
  const reopened = nativeField(), remount = fixture('draft-text-input');
  reopened.render(remount('DraftTextInput', { initialValue: 'another selected entry' }));
  assert.equal(reopened.field.text, 'another selected entry');
});

test('code confirmation submits the complete draft once and clears native and JS state', () => {
  const calls = [], native = nativeField();
  const render = fixture('account-sign-in', { '../state/clarify': { report: error => { throw error; } } });
  const props = { account: { pending: 'login', email: 'clarify-e2e@example.test' }, busy: false,
    command: async (...args) => { calls.push(args); } };
  const tree = () => render('AccountSignIn', props);
  find(tree(), 'account.code').props.inputRef.current = native.field;
  find(tree(), 'account.code').props.onChangeText('123456');
  find(tree(), 'account.verifyCode').props.onPress();
  assert.deepEqual(calls, [['confirm', '123456']]);
  assert.equal(native.field.clears, 1);
  assert.equal(find(tree(), 'account.verifyCode').props.disabled, true);
  find(tree(), 'account.code').props.onChangeText('654321');
  find(tree(), 'account.verifyCode').props.onPress();
  assert.deepEqual(calls, [['confirm', '123456'], ['confirm', '654321']]);
  assert.equal(native.field.clears, 2);
});

test('email draft survives account snapshots and returning from code entry', () => {
  const calls = [];
  const render = fixture('account-sign-in', { '../state/clarify': { report: error => { throw error; } } });
  const props = { account: { pending: '', email: 'saved@example.test', endpoint: 'https://fixture.invalid' }, busy: false,
    command: async (...args) => { calls.push(args); } };
  const tree = () => render('AccountSignIn', props);
  find(tree(), 'account.email').props.onChangeText('complete@example.test');
  props.account = { ...props.account };
  find(tree(), 'account.requestCode').props.onPress();
  assert.deepEqual(calls, [['login', 'complete@example.test']]);
  props.account = { ...props.account, pending: 'login' }; tree();
  props.account = { ...props.account, pending: '' };
  assert.equal(find(tree(), 'account.email').props.initialValue, 'complete@example.test');
});

function practiceFixture(onFinish) {
  const errors = [], native = nativeField();
  const render = fixture('quick-start-guide', {
    '../quick-start': guide,
    '../state/clarify': { isBusy: () => false, report: error => errors.push(error), useClarify: () => ({ state: { sessionActive: true } }) },
    'react-native': { Text: 'Text', View: 'View', Keyboard: { dismiss() {} } },
  });
  const tree = () => render('QuickStartGuide', { onFinish });
  find(tree(), 'onboarding.continue').props.onPress();
  find(tree(), 'onboarding.continue').props.onPress();
  find(tree(), 'onboarding.practiceInput').props.inputRef.current = native.field;
  find(tree(), 'onboarding.practiceInput').props.onChangeText('complete practice');
  native.field.text = 'complete practice';
  return { tree, native, errors };
}

test('failed guide completion retains the draft and back clears it deliberately', async () => {
  const f = practiceFixture(async () => { throw new Error('fixture completion failure'); });
  find(f.tree(), 'onboarding.continue').props.onPress();
  await new Promise(setImmediate);
  assert.equal(f.errors.length, 1);
  assert.equal(f.native.field.text, 'complete practice');
  assert.equal(f.native.field.clears, 0);
  assert.equal(find(f.tree(), 'onboarding.continue').props.disabled, false);
  find(f.tree(), 'onboarding.back').props.onPress();
  assert.equal(f.native.field.clears, 1);
  find(f.tree(), 'onboarding.continue').props.onPress();
  assert.equal(find(f.tree(), 'onboarding.practiceInput').props.initialValue, '');
});

test('successful guide completion clears only after the completion callback resolves', async () => {
  let complete;
  const f = practiceFixture(() => new Promise(resolve => { complete = resolve; }));
  find(f.tree(), 'onboarding.continue').props.onPress();
  assert.equal(f.native.field.clears, 0);
  assert.equal(find(f.tree(), 'onboarding.continue').props.loading, true);
  complete(); await new Promise(setImmediate);
  assert.equal(f.native.field.clears, 1);
  assert.equal(find(f.tree(), 'onboarding.practiceInput').props.initialValue, '');
});
