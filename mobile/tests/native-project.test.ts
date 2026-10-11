import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { getConfig } = require('expo/config');

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
