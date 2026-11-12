import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const require = createRequire(import.meta.url);
const { getConfig } = require('expo/config');
const withClarifyKeyboard = require('../plugins/with-clarify-keyboard.cjs');
const withClarifySounds = require('../plugins/with-clarify-sounds.cjs');

test('iPhone Settings includes localized setup help once in the app resources', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-settings-'));
  try {
    const template = path.join(path.dirname(require.resolve('expo/package.json')), 'template.tgz');
    const projectFile = path.join(root, 'project.pbxproj');
    fs.writeFileSync(projectFile, execFileSync('tar', ['-xOzf', template, 'package/ios/HelloWorld.xcodeproj/project.pbxproj']));
    const project = require('xcode').project(projectFile);
    project.parseSync();
    const config = require('../plugins/with-clarify-settings.cjs')(structuredClone(require('../app.json').expo));
    const modRequest = { projectRoot: process.cwd(), platformProjectRoot: root };
    for (let i = 0; i < 2; i++) {
      await config.mods.ios.dangerous({ ...config, modRequest });
      await config.mods.ios.xcodeproj({ ...config, modRequest, modResults: project });
    }
    const resources = project.pbxResourcesBuildPhaseObj(project.getFirstTarget().uuid).files;
    assert.equal(resources.filter((file: { comment: string }) => file.comment === 'Settings.bundle in Resources').length, 1);
    const plist = require('@expo/plist').default;
    const bundle = path.join(root, 'Settings.bundle');
    const schema = plist.parse(fs.readFileSync(path.join(bundle, 'Root.plist'), 'utf8'));
    assert.equal(schema.StringsTable, 'Root');
    assert.equal(schema.PreferenceSpecifiers.length, 2);
    for (const locale of ['pt', 'en', 'es']) {
      const content = fs.readFileSync(path.join(bundle, `${locale}.lproj`, 'Root.strings'), 'utf8');
      assert.ok(content.includes('Clarify'));
      assert.ok(content.includes('\\n'), 'multiline instructions must remain valid strings');
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('the containing app bundles the shared dictation sounds once', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-sounds-'));
  try {
    const template = path.join(path.dirname(require.resolve('expo/package.json')), 'template.tgz');
    const projectFile = path.join(root, 'project.pbxproj');
    fs.writeFileSync(projectFile, execFileSync('tar', ['-xOzf', template, 'package/ios/HelloWorld.xcodeproj/project.pbxproj']));
    const project = require('xcode').project(projectFile);
    project.parseSync();
    const config = withClarifySounds(structuredClone(require('../app.json').expo));
    const modRequest = { projectRoot: process.cwd(), platformProjectRoot: root };
    await config.mods.ios.dangerous({ ...config, modRequest });
    for (let i = 0; i < 2; i++) {
      await config.mods.ios.xcodeproj({ ...config, modRequest, modResults: project });
    }
    const resources = project.pbxResourcesBuildPhaseObj(project.getFirstTarget().uuid).files;
    for (const name of ['dictation-start.wav', 'dictation-stop.wav']) {
      const copied = fs.readFileSync(path.join(root, 'ClarifySounds', name));
      assert.deepEqual(copied, fs.readFileSync(path.resolve('../assets/sounds', name)));
      assert.equal(resources.filter((file: { comment: string }) => file.comment === `${name} in Resources`).length, 1);
      const file = project.hasFile(`ClarifySounds/${name}`);
      assert.ok(file, 'the resource path must resolve from the generated iOS project');
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

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
