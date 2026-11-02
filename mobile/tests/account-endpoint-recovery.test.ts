// @ts-nocheck -- Isolated command/consent test; no native rendering claim.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

test('endpoint recovery requires explicit confirmation and respects busy state', async () => {
  const source = fs.readFileSync(new URL('../src/components/account-endpoint-recovery.tsx', import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {}, calls = [], alerts = [];
  vm.runInNewContext(code, { exports, URL, require(name) {
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
    if (name === 'react-native') return { Text: 'Text', View: 'View', Alert: { alert: (...args) => alerts.push(args) } };
    if (name === '../i18n') return { t: (text, values) => values ? text.replace('{v0}', values.v0) : text };
    if (name === '../state/clarify') return { report: error => { throw error; } };
    if (name === './ui') return { Button: 'Button', ui: {}, usePalette: () => ({}) };
    throw new Error(name);
  } });
  const account = { endpoint: 'https://clarify-api-dev-dev.up.railway.app', endpointRecovery: 'https://clarify-api.victormaynard.com' };
  const render = (busy = false) => exports.AccountEndpointRecovery({ account, busy, command: async (...args) => { calls.push(args); } });
  assert.equal(render(true).props.children[1].props.disabled, true);
  const tree = render();
  assert.match(tree.props.children[0].props.children, /clarify-api-dev-dev\.up\.railway\.app/);
  tree.props.children[1].props.onPress();
  assert.deepEqual(calls, []);
  assert.equal(alerts[0][2][0].style, 'cancel');
  await alerts[0][2][1].onPress();
  assert.deepEqual(calls, [['recover-endpoint']]);
  account.endpointRecovery = '';
  assert.equal(render(), null);
});
