// @ts-nocheck -- Native menu presentation and gesture recognition remain an iOS gate.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

test('history hides controls, exposes failed retry and keeps actions in the native context menu', async () => {
  const slots = [], refs = [], calls = [], alerts = [];
  let slot = 0, ref = 0, finish;
  const waiting = new Promise(resolve => { finish = resolve; });
  const recording = { id: 'saved-audio', createdAt: 100, duration: 181, status: 'failed', processing: false };
  const entry = { id: 'audio:saved-audio', context: 'owner', text: '', transcript: '', rewritten: false, createdAt: 100, sourceDevice: 'mobile', recording, audioOnly: true };
  const state = { state: { configured: true, phase: 'idle', libraryRevision: 0 }, account: { historyContext: 'owner' },
    accountBusy: false, refresh: async () => {} };
  const core = {
    playRecoveryRecording: async (...args) => { calls.push(['play', ...args]); return true; },
    exportRecoveryRecording: async (...args) => { calls.push(['export', ...args]); },
    undoRecoveryEdit: async (...args) => { calls.push(['undo', ...args]); },
    copyText: async (...args) => { calls.push(['copy', ...args]); },
    reprocessRecording: async (...args) => { calls.push(['reprocess', ...args]); await waiting; },
    deleteRecoveryRecording: async (...args) => { calls.push(['delete', ...args]); },
  };
  const jsx = (type, props) => ({ type, props: props ?? {} }), exports = {};
  const source = fs.readFileSync(new URL('../src/components/history-item.tsx', import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports, require(name) {
      if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
      if (name === 'react') return {
        useState(initial) { const i = slot++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = value; }]; },
        useRef(initial) { return refs[ref++] ??= { current: initial }; },
      };
      if (name === 'expo') return { requireNativeView: () => 'ContextMenu' };
      if (name === 'react-native') return { Pressable: 'Button', Text: 'Text', View: 'View', Alert: { alert: (...args) => alerts.push(args) } };
      if (name === 'expo-symbols') return { SymbolView: 'Symbol' };
      if (name === '../../modules/clarify-core') return { __esModule: true, default: core };
      if (name === '../i18n') return { t: (value, values = {}) => value.replace(/\{(\w+)\}/g, (_, key) => values[key]), uiLanguage: 'en' };
      if (name === '../history') return { historyTime: () => '9:41' };
      if (name === '../state/clarify') return { useClarify: () => state, isBusy: s => s.phase === 'transcribing', report: error => { throw error; } };
      if (name === './ui') return { TableRow: 'TableRow', ui: {}, usePalette: () => ({}) };
      throw new Error(name);
    },
  });
  function nodes(tree) {
    if (Array.isArray(tree)) return tree.flatMap(nodes);
    if (!tree || typeof tree !== 'object') return [];
    return [tree, ...nodes(tree.props?.children)];
  }
  const render = () => { slot = 0; ref = 0; return nodes(exports.HistoryItem({ entry, first: true, last: true, onOpen() {}, onDelete() { calls.push(['delete-entry']); } })); };
  const menu = () => render().find(node => node.type === 'ContextMenu');
  const retryButton = () => render().find(node => node.type === 'Button' && node.props.accessibilityLabel === 'Tentar transcrição novamente');
  const choose = id => { const node = menu(); node.props.onAction({ nativeEvent: { id, menuID: node.props.menuID } }); };
  const flush = () => new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, []);
  assert.ok(render().some(node => node.type === 'Text' && node.props.children === 'Mobile'));
  assert.ok(render().some(node => node.props.accessibilityLabel?.includes('Mobile')));
  assert.equal(render().filter(node => node.type === 'Symbol' && node.props.name === 'arrow.clockwise').length, 1, 'Only failed retry has a visible action icon');
  assert.equal(menu().props.actions.find(action => action.id === 'copy'), undefined);
  assert.ok(render().some(node => node.type === 'Text' && node.props.children.includes?.('3:01')));
  choose('play'); await flush();
  assert.deepEqual(calls, [['play', 'saved-audio']], 'Listening is available through the context menu');
  state.state.playingRecordingID = recording.id;
  assert.equal(menu().props.actions.find(action => action.id === 'play').title, 'Pausar áudio');
  retryButton().props.onPress(); retryButton().props.onPress();
  assert.deepEqual(calls[1], ['reprocess', 'saved-audio', 'owner']); assert.equal(calls.length, 2);
  assert.equal(retryButton().props.disabled, true);
  finish(); await flush(); await flush();
  recording.processing = true;
  assert.equal(retryButton(), undefined, 'Processing does not display a retry control');
  choose('delete'); assert.equal(alerts.length, 0, 'In-flight audio must not be deleted');
  recording.processing = false; recording.status = 'complete'; entry.audioOnly = false;
  entry.text = 'Edited text'; entry.transcript = 'Original text'; entry.rewritten = true; entry.sourceDevice = 'desktop';
  assert.ok(render().some(node => node.type === 'Text' && node.props.children === 'Desktop'));
  assert.ok(render().some(node => node.props.accessibilityLabel?.includes('Desktop')));
  assert.equal(retryButton(), undefined);
  assert.equal(render().filter(node => node.type === 'Symbol' && node.props.name === 'arrow.clockwise').length, 0, 'Processed items have no visible controls');
  choose('copy'); await flush(); assert.deepEqual(calls[2], ['copy', 'Edited text']);
  choose('export'); await flush(); assert.deepEqual(calls[3], ['export', 'saved-audio']);
  choose('undo'); await flush(); assert.deepEqual(calls[4], ['undo', 'saved-audio', 'owner']);
  const oldMenu = menu();
  oldMenu.props.onAction({ nativeEvent: { id: 'delete', menuID: 'unrelated-row' } });
  assert.equal(calls.length, 5, 'A menu cannot act on a recycled row');
  state.account.historyContext = 'other-owner'; choose('play'); await flush();
  assert.equal(calls.length, 5, 'An old menu cannot act after an account change');
  state.account.historyContext = 'owner';
  entry.audioOnly = true; recording.status = 'failed'; choose('delete');
  assert.equal(alerts[0][2][0].style, 'cancel');
  alerts[0][2][1].onPress(); alerts[0][2][1].onPress(); await flush();
  assert.deepEqual(calls[5], ['delete', 'saved-audio']); assert.equal(calls.length, 6);
  entry.audioOnly = false; delete entry.recording;
  assert.deepEqual(Array.from(menu().props.actions, action => action.id), ['copy', 'delete']);
});
