// @ts-nocheck -- Inert JSX fixture exercises the shipped UI and command boundary.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = fs.readFileSync(new URL('../src/components/computer-connection.tsx', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
} }).outputText;

function fixture(remoteStatus, { paired = true, signedIn = true, status = 'ready', busy = false, managing = false } = {}) {
  const commands = [];
  const alerts = [];
  const account = { signedIn, busy: false, mode: 'computer', computer: {
    paired, computerName: 'Fixture PC', status, remoteStatus, ready: status === 'ready', busy,
  } };
  const signIn = function AccountSignIn() {};
  const jsx = (type, props) => ({ type, props: props ?? {} });
  const exports = {};
  const sandbox = { exports, module: { exports }, require(name) {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' };
    if (name === 'react') return { useState: () => [managing, () => {}] };
    if (name === 'react-native') return { Text: 'Text', View: 'View', Alert: { alert: (...args) => alerts.push(args) } };
    if (name === './ui') return { Button: 'Button', TextButton: 'TextButton', Card: 'Card',
      ui: { section: {}, body: {}, small: {} }, usePalette: () => ({ text: '#fff', muted: '#aaa' }) };
    if (name === '../i18n') return { t: text => text };
    if (name === '../state/clarify') return { useClarify: () => ({ account, accountBusy: busy,
      accountCommand: async (...args) => { commands.push(['account', ...args]); },
      computerCommand: async (...args) => { commands.push(['computer', ...args]); },
    }), report() {} };
    if (name === '../processing') return { computerStatus: value => value };
    if (name === './account-sign-in') return { AccountSignIn: signIn };
    throw new Error(`Unexpected import: ${name}`);
  } };
  vm.runInNewContext(code, sandbox);
  const nodes = [];
  function walk(node) {
    if (Array.isArray(node)) node.forEach(walk);
    else if (node && typeof node === 'object') {
      if (typeof node.type === 'function' && node.type !== signIn) { walk(node.type(node.props)); return; }
      nodes.push(node); walk(node.props?.children);
    }
  }
  walk(exports.ComputerConnectionCard());
  return { nodes, commands, alerts, signIn, find: id => nodes.find(n => n.props?.testID === id) };
}

test('first connection has one QR action and does not ask for an internet account yet', () => {
  const f = fixture('unavailable', { paired: false, status: 'unpaired', signedIn: false });
  assert.ok(f.find('computer.scan')?.props.primary);
  assert.equal(f.nodes.some(n => n.type === f.signIn), false);
  assert.equal(f.find('computer.authorize-remote'), undefined);
  assert.equal(f.find('computer.remote-status'), undefined);
});

test('retained account needing authorization offers explicit reauthentication, not the same failing activation', async () => {
  const f = fixture('account_required');
  assert.equal(f.find('computer.authorize-remote'), undefined);
  assert.ok(f.find('computer.reauthenticate')?.props.primary);
  await f.find('computer.reauthenticate').props.onPress();
  assert.deepEqual(f.commands, [['account', 'logout']]);
});

test('internet activation is primary only while authorization is needed and LAN is reachable', () => {
  const f = fixture('authorization_required');
  assert.ok(f.find('computer.authorize-remote')?.props.primary);
  assert.equal(f.find('computer.scan'), undefined);
  assert.equal(f.find('computer.disconnect'), undefined);
  const offline = fixture('authorization_required', { status: 'offline' });
  assert.equal(offline.find('computer.authorize-remote'), undefined);
  assert.ok(offline.find('computer.refresh').props.primary);
  const signedOutOffline = fixture('account_required', { status: 'offline', signedIn: false });
  assert.equal(signedOutOffline.nodes.some(n => n.type === signedOutOffline.signIn), false);
  assert.equal(fixture('account_required', { status: 'offline' }).find('computer.reauthenticate'), undefined);
});

test('registered internet access has no repeated activation, QR or login form', () => {
  const f = fixture('registered');
  assert.ok(f.find('computer.remote-status'));
  assert.equal(f.find('computer.authorize-remote'), undefined);
  assert.equal(f.find('computer.scan'), undefined);
  assert.equal(f.nodes.some(n => n.type === f.signIn), false);
});

test('an uncertain activation offers a read-only status check without a second claim', async () => {
  const f = fixture('failed');
  assert.ok(f.find('computer.remote-recover'));
  await f.find('computer.remote-recover').props.onPress();
  assert.deepEqual(f.commands, [['computer', 'refresh']]);
  assert.equal(f.find('computer.authorize-remote'), undefined);
});

test('account entry is confined to remote authorization and in-flight activation cannot be repeated', () => {
  const signedOut = fixture('account_required', { signedIn: false });
  assert.equal(signedOut.nodes.some(n => n.type === signedOut.signIn), true);
  const pending = fixture('registering', { busy: true });
  assert.equal(pending.find('computer.authorize-remote'), undefined);
  assert.ok(pending.find('computer.remote-status'));
});

test('disconnect stays in management and requires a separate destructive confirmation', async () => {
  const f = fixture('registered', { managing: true });
  assert.equal(f.find('computer.manage').props.expanded, true);
  assert.ok(f.find('computer.scan'));
  f.find('computer.disconnect').props.onPress();
  assert.deepEqual(f.commands, []);
  const choices = f.alerts[0][2];
  assert.equal(choices[0].style, 'cancel');
  assert.equal(choices[0].onPress, undefined);
  assert.equal(choices[1].style, 'destructive');
  await choices[1].onPress();
  assert.deepEqual(f.commands, [['computer', 'disconnect']]);
});

test('a paired offline computer keeps read-only recovery and explicit connection management', async () => {
  const f = fixture('registered', { status: 'offline', managing: true });
  assert.equal(f.find('computer.manage').props.disabled, false);
  assert.equal(f.find('computer.scan').props.disabled, false);
  assert.equal(f.find('computer.disconnect').props.disabled, false);
  assert.equal(f.find('computer.authorize-remote'), undefined);
  await f.find('computer.refresh').props.onPress();
  assert.deepEqual(f.commands, [['computer', 'refresh']]);
});
