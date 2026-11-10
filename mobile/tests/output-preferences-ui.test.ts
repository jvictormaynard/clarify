// @ts-nocheck -- Command and state assertions; no native rendering claim.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { outputStyleLabel, outputStyles } from '../src/output-preferences.ts';
import { targetLanguages } from '../src/text-actions.ts';

function fixture(preferences, { supported = true, fail = false, mode = 'hosted', freshSupport = supported, refreshFails = false, busy = false, policyOnly = false, processingContract, policyMode = 'legacy' } = {}) {
  const source = fs.readFileSync(new URL(policyOnly ? '../src/components/dictation-policy.tsx' : '../src/app/output.tsx', import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const slots = [], refs = [], memos = [], calls = [], refreshes = [];
  let index = 0, refIndex = 0, memoIndex = 0, focused, cleanup;
  const account = { mode, outputPreferencesSupported: supported, historyContext: 'fixture', textActions: [], processingContract,
    computer: { textActions: [], processingContract } };
  const state = { phase: busy ? 'recording' : 'idle' };
  const refresh = async destination => {
    refreshes.push(destination);
    if (refreshFails) throw new Error('Destination unavailable');
    account.outputPreferencesSupported = freshSupport;
    return account;
  };
  const accountCommand = async action => { assert.equal(action, 'refresh'); return refresh('hosted'); };
  const computerCommand = async action => { assert.equal(action, 'refresh'); return refresh('computer'); };
  const jsx = (type, props) => ({ type, props });
  const exports = {};
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' };
    if (name === 'react') return {
      useState(initial) { const i = index++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = value; }]; },
      useRef(initial) { const i = refIndex++; return refs[i] ??= { current: initial }; },
      useLayoutEffect(fn) { fn(); },
      useCallback(fn, dependencies) {
        const i = memoIndex++;
        if (!memos[i] || dependencies.some((value, index) => !Object.is(value, memos[i].dependencies[index]))) memos[i] = { fn, dependencies };
        return memos[i].fn;
      },
    };
    if (name === 'expo-router') return { router: { back() {} }, useFocusEffect(fn) { if (focused !== fn) { cleanup?.(); focused = fn; cleanup = fn(); } } };
    if (name === 'react-native') return { ActivityIndicator: 'ActivityIndicator', ScrollView: 'ScrollView', Text: 'Text' };
    if (name === '../components/ui' || name === './ui') return { Button: 'Button', TextButton: 'TextButton', ChoiceRow: 'ChoiceRow', Section: 'Section', ui: {}, usePalette: () => ({}) };
    if (name === '../state/clarify') return { isBusy: state => state.phase === 'recording', useClarify: () => ({ account, state, accountBusy: false, accountCommand, computerCommand }) };
    if (name === '../errors') return { errorMessage: error => error.message };
    if (name === '../output-preferences') return { outputStyleLabel, outputStyles };
    if (name === '../text-actions') return { targetLanguages };
    if (name === '../components/dictation-policy') return { DictationPolicyControls: 'DictationPolicyControls' };
    if (name === '../i18n') return { t: text => text };
    if (name === '../../modules/clarify-core') return { __esModule: true, default: {
      getOutputPreferences: async () => ({ ...preferences }),
      getDictationPolicy: async () => ({ mode: policyMode, actionID: '', actionRevision: '', language: 'auto' }),
      setOutputPreference: async (key, value) => {
        calls.push([key, value]); if (fail) throw new Error('Save failed');
        preferences = { ...preferences, [key]: value }; return preferences;
      },
    } };
    throw new Error(name);
  } });
  function render() {
    index = 0; refIndex = 0; memoIndex = 0; const nodes = [];
    function walk(node) {
      if (Array.isArray(node)) node.forEach(walk);
      else if (node && typeof node === 'object') { nodes.push(node); walk(node.props?.children); if (!policyOnly) { walk(node.props?.tone); walk(node.props?.more); } }
    }
    walk(policyOnly ? exports.DictationPolicyControls({ outputLanguage: preferences.language, tone: jsx('Tone', { testID: 'fixture.tone' }), more: jsx('More', { testID: 'fixture.more' }) }) : exports.default()); return nodes;
  }
  const find = id => render().find(node => node.props?.testID === id);
  const flush = () => new Promise(resolve => setImmediate(resolve));
  render();
  return { find, render, flush, calls, refreshes, allowRefresh: () => { refreshFails = false; }, idle: () => { state.phase = 'idle'; } };
}

test('dictation policies keep old destinations usable without detailed capabilities', async () => {
  for (const mode of ['hosted', 'computer']) {
    for (const processingContract of [undefined, {}, { cleanup_levels: ['preserve'], explicit_dictation_policy: true }]) {
      const f = fixture({ language: 'auto', style: 'default' }, { mode, policyOnly: true, processingContract });
      await f.flush();
      f.find('output.more').props.onPress();
      assert.equal(f.find('output.policy.legacy').props.disabled, false);
      assert.equal(f.find('output.policy.preserve').props.disabled, !processingContract?.cleanup_levels?.includes('preserve'));
      assert.equal(f.find('output.policy.light').props.disabled, true);
      assert.equal(f.find('output.policy.action').props.disabled, true);
      assert.deepEqual(f.calls, []);
    }
  }
});

for (const mode of ['hosted', 'computer']) {
  test(`opening refreshes ${mode} support before enabling explicit output choices`, async () => {
    const f = fixture({ language: 'auto', style: 'default' }, { supported: false, freshSupport: true, mode });
    await f.flush();
    assert.deepEqual(f.refreshes, [mode]);
    assert.equal(f.find('output.language.de').props.disabled, false);
    assert.equal(f.find('output.style.formal').props.disabled, false);
    assert.deepEqual(f.calls, []);
    f.render(); await f.flush();
    assert.deepEqual(f.refreshes, [mode], 'rendering must not start another refresh');
  });
}

test('failed capability refresh stays blocked and can recover without changing preferences', async () => {
  const f = fixture({ language: 'auto', style: 'default' }, { supported: false, freshSupport: true, refreshFails: true });
  await f.flush();
  assert.ok(f.find('output.error'));
  assert.equal(f.find('output.style.formal').props.disabled, true);
  f.allowRefresh(); f.find('output.refresh').props.onPress(); await f.flush();
  assert.equal(f.find('output.style.formal').props.disabled, false);
  assert.deepEqual(f.refreshes, ['hosted', 'hosted']);
  assert.deepEqual(f.calls, []);
});

test('opening during dictation does not start account work; explicit refresh works after stopping', async () => {
  const f = fixture({ language: 'auto', style: 'default' }, { supported: false, freshSupport: true, busy: true });
  await f.flush();
  assert.deepEqual(f.refreshes, []);
  assert.equal(f.find('output.refresh').props.disabled, true);
  f.idle(); f.find('output.refresh').props.onPress(); await f.flush();
  assert.deepEqual(f.refreshes, ['hosted']);
  assert.equal(f.find('output.style.formal').props.disabled, false);
});

test('opening preserves legacy style; one language save does not rewrite it', async () => {
  const f = fixture({ language: 'auto', style: 'organized' }); await f.flush();
  assert.deepEqual(f.calls, []);
  assert.ok(f.find('output.language.de'), JSON.stringify(f.render()));
  f.find('output.language.de').props.onPress(); await f.flush();
  assert.deepEqual(f.calls, [['language', 'de']]);
  assert.equal(f.find('output.language.de').props.selected, true);
  assert.equal(f.render().find(node => node.type === 'DictationPolicyControls').props.outputLanguage, 'de', 'Saved translation actions use the same output language');
  assert.ok(f.render().some(node => node.props?.title === 'Organizado' && node.props.selected));
});

test('a failed single-field save keeps the saved value and exposes failure', async () => {
  const f = fixture({ language: 'auto', style: 'default' }, { fail: true }); await f.flush();
  f.find('output.style.formal').props.onPress(); await f.flush();
  assert.deepEqual(f.calls, [['style', 'formal']]);
  assert.ok(f.render().some(node => node.props?.title === 'Padrão' && node.props.selected));
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
  assert.equal(f.find('output.style.casual').props.disabled, true);
  f.find('output.language.auto').props.onPress(); await f.flush();
  assert.equal(f.find('output.style.default').props.disabled, false);
  f.find('output.style.default').props.onPress(); await f.flush();
  assert.deepEqual(f.calls, [['language', 'auto'], ['style', 'default']]);
  assert.equal(f.find('output.language.auto').props.selected, true);
  assert.equal(f.find('output.style.default').props.selected, true);
});

test('tone is hidden for preserve, light and destinations without clarity; more options remain collapsed', async () => {
  for (const policyMode of ['clarity', 'preserve', 'light', 'legacy']) {
    for (const allowed of [true, false]) {
      const f = fixture({ language: 'auto', style: 'natural' }, { policyOnly: true, policyMode,
        processingContract: { cleanup_levels: allowed ? ['clarity', 'preserve', 'light'] : ['preserve'], explicit_dictation_policy: true } });
      await f.flush();
      assert.equal(!!f.find('fixture.tone'), allowed && !['preserve', 'light'].includes(policyMode));
      assert.equal(f.find('fixture.more'), undefined);
      assert.ok(f.find('output.policy.clarity'));
      assert.ok(f.find('output.policy.preserve'));
      f.find('output.more').props.onPress();
      assert.ok(f.find('fixture.more'));
      assert.ok(f.find('output.policy.legacy'));
    }
  }
});


test('paired tone uses advertised editing readiness instead of recognition readiness', async () => {
  for (const allowed of [false, true]) {
    const f = fixture({ language: 'auto', style: 'natural' }, { policyOnly: true, policyMode: 'clarity', mode: 'computer',
      processingContract: { cleanup_levels: ['clarity', 'preserve'], explicit_dictation_policy: true,
        dictation_editing: { legacy: allowed, natural: allowed, clarity: allowed, action: allowed } } });
    await f.flush();
    assert.equal(!!f.find('fixture.tone'), allowed);
    assert.ok(f.find('output.policy.clarity'));
  }
  for (const policyMode of ['natural', 'legacy']) {
    for (const language of ['auto', 'es']) {
      const f = fixture({ language, style: 'formal' }, { policyOnly: true, policyMode, mode: 'computer',
        processingContract: { cleanup_levels: ['clarity', 'preserve'], explicit_dictation_policy: true,
          dictation_editing: { legacy: true, natural: true, clarity: false, action: true,
            legacy_translated: false, natural_translated: false } } });
      await f.flush();
      assert.equal(!!f.find('fixture.tone'), language === 'auto');
    }
  }
});
