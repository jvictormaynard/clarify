import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { getConfig } = require('expo/config');
const withClarifyKeyboard = require('../plugins/with-clarify-keyboard.cjs');

test('keyboard source composition excludes account credential access', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-keyboard-sources-'));
  try {
    const config = withClarifyKeyboard(structuredClone(require('../app.json').expo));
    const modRequest = { projectRoot: process.cwd(), platformProjectRoot: root };
    await config.mods.ios.dangerous({ ...config, modRequest });
    let sources: string[] = [];
    const project = {
      pbxTargetByName: () => null,
      addTarget: () => ({ uuid: 'keyboard-target' }),
      addPbxGroup: () => ({ uuid: 'keyboard-group' }),
      addToPbxGroup() {},
      getFirstProject: () => ({ firstProject: { mainGroup: 'main-group' } }),
      addBuildPhase(files: string[], type: string) { if (type === 'PBXSourcesBuildPhase') sources = files; },
      pbxXCBuildConfigurationSection: () => ({}),
    };
    await config.mods.ios.xcodeproj({ ...config, modRequest, modResults: project });
    const swift = sources.filter(file => file.endsWith('.swift')).map(file => fs.readFileSync(path.join(root, file), 'utf8')).join('\n');
    assert.doesNotMatch(swift, /enum KeyStore\b|SecItemCopyMatching|AccountCredential/, 'The keyboard must not receive credential access to obtain an error type');
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('EAS config declares both targets with the same app group', () => {
  const { exp } = getConfig(process.cwd());
  const group = 'group.com.jvictormaynard.clarify';
  const extension = exp.extra.eas.build.experimental.ios.appExtensions[0];
  assert.equal(extension.bundleIdentifier, 'com.jvictormaynard.clarify.keyboard');
  assert.deepEqual(extension.entitlements['com.apple.security.application-groups'], [group]);
  assert.deepEqual(exp.ios.entitlements['com.apple.security.application-groups'], [group]);
  assert.ok(exp.ios.infoPlist.UIBackgroundModes.includes('audio'));
  const activity = exp.extra.eas.build.experimental.ios.appExtensions.find((item: { targetName: string }) => item.targetName === 'ClarifyActivity');
  assert.equal(activity?.bundleIdentifier, 'com.jvictormaynard.clarify.activity');
  assert.equal(exp.ios.infoPlist.NSSupportsLiveActivities, true);
});

test('computer pairing requests camera and LAN access with only private-network ATS exceptions', () => {
  const { exp } = getConfig(process.cwd());
  assert.match(exp.ios.infoPlist.NSCameraUsageDescription, /QR/);
  assert.match(exp.ios.infoPlist.NSLocalNetworkUsageDescription, /computador/);
  const ats = exp.ios.infoPlist.NSAppTransportSecurity;
  assert.equal(ats.NSAllowsArbitraryLoads, undefined);
  assert.equal(ats.NSAllowsArbitraryLoadsInWebContent, undefined);
  assert.equal(ats.NSAllowsLocalNetworking, true);
  assert.deepEqual(Object.keys(ats.NSExceptionDomains).sort(), ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']);
});
