import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const withPatchedReactNative = require('../plugins/with-patched-react-native.cjs');
const app = require('../app.json').expo;
const { configurePodfile, sourcePath, verifyPods, verifySource } = require('../scripts/verify-react-native-source.cjs');

test('generated Podfile compiles the patched React core without changing dependency binaries', async () => {
  const original = "require 'react_native_pods'\nENV['RCT_USE_RN_DEP'] ||= '1'\nuse_react_native!\n";
  const config = withPatchedReactNative(structuredClone(app));
  const request = { ...config, modRequest: { projectRoot: process.cwd(), platformProjectRoot: '/fixture/ios' }, modResults: { contents: original, language: 'rb' } };
  const result = await config.mods.ios.podfile(request);
  assert.equal(result.modResults.contents, "ENV['RCT_USE_PREBUILT_RNCORE'] = '0'\n" + original);
  const again = await config.mods.ios.podfile({ ...result, modResults: { ...result.modResults } });
  assert.equal(again.modResults.contents, result.modResults.contents);
  assert.ok(app.plugins.includes('./plugins/with-patched-react-native.cjs'));
});

test('native build rejects an unsupported version, changed source and prebuilt CocoaPods', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-native-source-'));
  const packageFile = path.join(root, 'node_modules/react-native/package.json');
  const nativeFile = path.join(root, sourcePath);
  try {
    fs.mkdirSync(path.dirname(nativeFile), { recursive: true });
    fs.copyFileSync(sourcePath, nativeFile);
    fs.writeFileSync(packageFile, JSON.stringify({ version: '0.86.3' }));
    fs.mkdirSync(path.join(root, 'ios'));
    fs.writeFileSync(path.join(root, 'ios/Podfile'), configurePodfile("require 'react_native_pods'\n"));
    fs.writeFileSync(path.join(root, 'ios/Podfile.lock'), 'PODS:\n  - React-RCTFabric (0.86.3)\n');
    assert.doesNotThrow(() => verifyPods(root));
    fs.appendFileSync(path.join(root, 'ios/Podfile.lock'), '  - React-Core-prebuilt (0.86.3)\n');
    assert.throws(() => verifyPods(root), /CocoaPods/);
    fs.writeFileSync(path.join(root, 'ios/Podfile.lock'), 'PODS:\n  - React-RCTFabric (0.86.3)\n');
    fs.writeFileSync(path.join(root, 'ios/Podfile'), "require 'react_native_pods'\n");
    assert.throws(() => verifyPods(root), /source compilation/);
    fs.appendFileSync(nativeFile, '\nchanged source\n');
    assert.throws(() => verifySource(root), /patch is absent or changed/);
    fs.copyFileSync(sourcePath, nativeFile);
    fs.writeFileSync(packageFile, JSON.stringify({ version: '0.86.4' }));
    assert.throws(() => verifySource(root), /Revalidate/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
