// @ts-nocheck -- Command and state assertions; no native rendering claim.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { outputStyleLabel, outputStyles, visibleOutputStyle } from '../src/output-preferences.ts';
import { targetLanguages } from '../src/text-actions.ts';

function fixture(preferences, { supported = true, fail = false } = {}) {
  const source = fs.readFileSync(new URL('../src/app/output.tsx', import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const slots = [], refs = [], calls = [];
  let index = 0, refIndex = 0, focused = false;
  const jsx = (type, props) => ({ type, props });
  const exports = {};
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' };
    if (name === 'react') return {
      useState(initial) { const i = index++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = value; }]; },
      useRef(initial) { const i = refIndex++; return refs[i] ??= { current: initial }; }, useCallback: fn => fn,
    };
    if (name === 'expo-router') return { router: { back() {} }, useFocusEffect(fn) { if (!focused) { focused = true; fn(); } } };
    if (name === 'react-native') return { ActivityIndicator: 'ActivityIndicator', ScrollView: 'ScrollView', Text: 'Text' };
    if (name === '../components/ui') return { Button: 'Button', ChoiceRow: 'ChoiceRow', Section: 'Section', ui: {}, usePalette: () => ({}) };
    if (name === '../state/clarify') return { useClarify: () => ({ account: { outputPreferencesSupported: supported } }) };
    if (name === '../errors') return { errorMessage: error => error.message };
    if (name === '../output-preferences') return { outputStyleLabel, outputStyles, visibleOutputStyle };
    if (name === '../text-actions') return { targetLanguages };
    if (name === '../i18n') return { t: text => text };
    if (name === '../../modules/clarify-core') return { __esModule: true, default: {
      getOutputPreferences: async () => ({ ...preferences }),
      setOutputPreference: async (key, value) => {
        calls.push([key, value]); if (fail) throw new Error('Save failed');
        preferences = { ...preferences, [key]: value }; return preferences;
      },
    } };
    throw new Error(name);
  } });
  function render() {
    index = 0; refIndex = 0; const nodes = [];
    function walk(node) {
      if (Array.isArray(node)) node.forEach(walk);
      else if (node && typeof node === 'object') { nodes.push(node); walk(node.props?.children); }
    }
    walk(exports.default()); return nodes;
  }
  const find = id => render().find(node => node.props?.testID === id);
  const flush = () => new Promise(resolve => setImmediate(resolve));
  render();
  return { find, render, flush, calls };
}

test('opening preserves legacy style; one language save does not rewrite it', async () => {
  const f = fixture({ language: 'auto', style: 'organized' }); await f.flush();
  assert.deepEqual(f.calls, []);
  assert.ok(f.find('output.language.de'), JSON.stringify(f.render()));
  f.find('output.language.de').props.onPress(); await f.flush();
  assert.deepEqual(f.calls, [['language', 'de']]);
  assert.equal(f.find('output.language.de').props.selected, true);
  assert.ok(f.render().some(node => node.props?.title === 'Organizado' && node.props.selected));
});

test('a failed single-field save keeps the saved value and exposes failure', async () => {
  const f = fixture({ language: 'auto', style: 'default' }, { fail: true }); await f.flush();
  f.find('output.style.formal').props.onPress(); await f.flush();
  assert.deepEqual(f.calls, [['style', 'formal']]);
  assert.equal(f.find('output.style.default').props.selected, true);
  assert.ok(f.find('output.error'));
});

test('unsupported destination cannot write explicit output preferences', async () => {
  const f = fixture({ language: 'auto', style: 'default' }, { supported: false }); await f.flush();
  assert.equal(f.find('output.style.formal').props.disabled, true);
  f.find('output.style.formal').props.onPress(); await f.flush();
  assert.deepEqual(f.calls, []);
});

test('an older destination still allows clearing saved output overrides', async () => {
  const f = fixture({ language: 'en', style: 'formal' }, { supported: false }); await f.flush();
  assert.equal(f.find('output.language.auto').props.disabled, false);
  assert.equal(f.find('output.style.default').props.disabled, false);
  assert.equal(f.find('output.style.casual').props.disabled, true);
  f.find('output.language.auto').props.onPress(); await f.flush();
  f.find('output.style.default').props.onPress(); await f.flush();
  assert.deepEqual(f.calls, [['language', 'auto'], ['style', 'default']]);
  assert.equal(f.find('output.language.auto').props.selected, true);
  assert.equal(f.find('output.style.default').props.selected, true);
});
