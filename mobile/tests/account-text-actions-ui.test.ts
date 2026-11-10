// @ts-nocheck -- Inert JSX tests handlers; UIKit remains a native gate.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { actionReplacement, ownsActionLibrary } from '../src/account-text-actions.ts';
import { actionChoices } from '../src/text-actions.ts';

test('failed action save keeps draft and exact CAS; context change blocks save', async () => {
  const row = { id: 'one', name: 'Original', prompt: 'Original prompt', kind: 'custom', enabled: true, revision: '1' };
  const base = { context: 'owner', lease: 'lease', revision: '9007199254740993', actions: [row] };
  let nativeCatalog = {};
  const state = { account: { historyContext: 'owner', signedIn: true, mode: 'hosted', textActionsStatus: 'unavailable', textActions: [] },
    state: {}, refresh: async () => {}, refreshAccount: async () => Object.assign(state.account, nativeCatalog) };
  const slots = [], refs = [], calls = [];
  let slot = 0, ref = 0, reject = true, effect;
  const core = { getAccountTextActions: async () => {
    nativeCatalog = { textActionsStatus: 'ready', textActions: [{ ...row, ready: true }] };
    return base;
  }, newOperationID: () => 'copy',
    saveAccountTextActions: async (...args) => { calls.push(args); if (reject) throw new Error('Conflict'); return base; } };
  const jsx = (type, props) => ({ type, props: props ?? {} }), exports = {};
  const source = fs.readFileSync(new URL('../src/components/account-text-actions.tsx', import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, { exports, require(name) {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' };
    if (name === 'react') return {
      useState(initial) { const i = slot++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
      useRef(initial) { return refs[ref++] ??= { current: initial }; }, useEffect(fn) { effect ??= fn; }, useLayoutEffect(effect) { effect(); },
    };
    if (name === 'expo-router') return { useIsFocused: () => true };
    if (name === 'react-native') return { Text: 'Text', View: 'View', Switch: 'Switch', Alert: { alert() {} } };
    if (name === '../../modules/clarify-core') return { __esModule: true, default: core };
    if (name === '../account-text-actions') return { actionReplacement, ownsActionLibrary };
    if (name === '../i18n') return { t: value => value };
    if (name === '../state/clarify') return { useClarify: () => state, isBusy: () => false, report() {} };
    if (name === './draft-text-input') return { DraftTextInput: 'Input' };
    if (name === './ui') return { Button: 'Button', Card: 'Card', ChoiceRow: 'ChoiceRow', NativeSheet: 'Sheet', ui: {}, usePalette: () => ({}) };
    throw new Error(name);
  } });
  const render = () => { slot = 0; ref = 0; return exports.AccountTextActions(); };
  function all(tree, type) {
    if (Array.isArray(tree)) return tree.flatMap(item => all(item, type));
    if (!tree || typeof tree !== 'object') return [];
    return [...(tree.type === type ? [tree] : []), ...all(tree.props?.children, type)];
  }
  const button = (tree, label) => all(tree, 'Button').find(node => node.props.children === label);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  render();
  assert.equal(actionChoices(state.account).length, 0);
  effect(); await settle();
  assert.equal(actionChoices(state.account)[0]?.key, 'saved:one:1', 'Initial management discovery must update the composer catalog');
  state.account.textActionsStatus = 'unavailable';
  button(render(), 'Atualizar lista').props.onPress(); await settle();
  assert.equal(actionChoices(state.account)[0]?.key, 'saved:one:1', 'Reload must also update the composer catalog');
  button(render(), 'Original').props.onPress();
  const editor = render();
  all(editor, 'Input')[1].props.onChangeText('Retained instructions');
  all(editor, 'Switch')[0].props.onValueChange(false);
  button(render(), 'Salvar').props.onPress(); await settle();
  assert.equal(all(render(), 'Sheet')[0].props.visible, true);
  assert.equal(calls[0][0][0].prompt, 'Retained instructions');
  assert.equal(calls[0][0][0].enabled, false);
  assert.equal(calls[0][1], '9007199254740993');
  assert.equal(calls[0][2], 'lease');
  state.account.historyContext = 'other-owner';
  assert.equal(button(render(), 'Salvar').props.disabled, true);
  state.account.historyContext = 'owner'; reject = false;
  button(render(), 'Salvar').props.onPress(); await settle();
  assert.equal(calls[1][0][0].prompt, 'Retained instructions');
  assert.equal(all(render(), 'Sheet')[0].props.visible, false);
});
