import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { protectComputerLinks } = require('../plugins/with-computer-link-privacy.cjs');

test('the pinned Expo template filters initial and runtime computer URLs before JavaScript', () => {
  const template = path.join(path.dirname(require.resolve('expo/package.json')), 'template.tgz');
  const source = execFileSync('tar', ['-xOzf', template, 'package/ios/HelloWorld/AppDelegate.swift'], { encoding: 'utf8' });
  const result = protectComputerLinks(source);
  assert.match(result, /clarifyLaunchOptions\?\.removeValue\(forKey: \.url\)/);
  assert.match(result, /launchOptions: clarifyLaunchOptions/);
  assert.match(result, /didFinishLaunchingWithOptions: clarifyLaunchOptions/);
  assert.doesNotMatch(result, /(?:launchOptions|didFinishLaunchingWithOptions): launchOptions/);
  const runtime = result.slice(result.indexOf('// Linking API'));
  assert.ok(runtime.indexOf('url.host?.lowercased() == "computer" { return true }') < runtime.indexOf('RCTLinkingManager.application'));
  assert.match(runtime, /super\.application\(app, open: url, options: options\) \|\| RCTLinkingManager/);
  assert.equal(protectComputerLinks(result), result);
});

test('a changed Expo native template cannot silently bypass privacy filtering', () => {
  assert.throws(() => protectComputerLinks('class AppDelegate {}'), /Unsupported Expo/);
});
