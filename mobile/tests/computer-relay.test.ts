import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { compileModsAsync } = require('expo/config-plugins');
const { getPrebuildConfigAsync } = require('@expo/prebuild-config');
const withComputerRelay = require('../plugins/with-computer-relay.cjs');
const withComputerLinkPrivacy = require('../plugins/with-computer-link-privacy.cjs');
const app = require('../app.json').expo;
const projectRoot = path.resolve(import.meta.dirname, '..');
// Reserved documentation names only. No operator domain is selected here.
const host = 'relay.example.com';
const exception = {
  NSIncludesSubdomains: true,
  NSExceptionAllowsInsecureHTTPLoads: true,
  NSExceptionMinimumTLSVersion: 'TLSv1.2',
  NSExceptionRequiresForwardSecrecy: true,
};

async function evaluate(value: string | undefined, fullPrebuild = false, plistOverrides = {}) {
  const previous = process.env.EXPO_PUBLIC_CLARIFY_CONNECT_RELAY_HOST;
  if (value === undefined) delete process.env.EXPO_PUBLIC_CLARIFY_CONNECT_RELAY_HOST;
  else process.env.EXPO_PUBLIC_CLARIFY_CONNECT_RELAY_HOST = value;
  try {
    let config;
    if (fullPrebuild) ({ exp: config } = await getPrebuildConfigAsync(projectRoot, { platforms: ['ios'] }));
    else {
      config = structuredClone(app);
      Object.assign(config.ios.infoPlist, plistOverrides);
      config = withComputerRelay(config);
      config = withComputerLinkPrivacy(config);
    }
    assert.equal(typeof config.mods.ios.appDelegate, 'function');
    return await compileModsAsync(config, { projectRoot, platforms: ['ios'], introspect: true, ignoreExistingNativeFiles: true });
  } finally {
    if (previous === undefined) delete process.env.EXPO_PUBLIC_CLARIFY_CONNECT_RELAY_HOST;
    else process.env.EXPO_PUBLIC_CLARIFY_CONNECT_RELAY_HOST = previous;
  }
}

test('optional relay config preserves the pinned Expo 57 native plist and LAN exceptions', async () => {
  assert.match(require('expo/package.json').version, /^57\./);
  const result = await evaluate(undefined);
  const plist = result._internal.modResults.ios.infoPlist;
  assert.equal(plist.ClarifyConnectRelayHost, undefined);
  assert.deepEqual(plist.NSAppTransportSecurity, app.ios.infoPlist.NSAppTransportSecurity);
  assert.equal(plist.NSLocalNetworkUsageDescription, app.ios.infoPlist.NSLocalNetworkUsageDescription);
  assert.equal(plist.NSCameraUsageDescription, app.ios.infoPlist.NSCameraUsageDescription);
});

test('relay build config adds only one scoped ATS exception and a native hostname', async () => {
  const result = await evaluate(host);
  const plist = result._internal.modResults.ios.infoPlist;
  assert.equal(plist.ClarifyConnectRelayHost, host);
  assert.deepEqual(plist.NSAppTransportSecurity, {
    ...app.ios.infoPlist.NSAppTransportSecurity,
    NSExceptionDomains: { ...app.ios.infoPlist.NSAppTransportSecurity.NSExceptionDomains, [host]: exception },
  });
  assert.equal(result.version, app.version);
  assert.equal(result.ios.buildNumber, app.ios.buildNumber);
  assert.equal(app.plugins.includes('./plugins/with-computer-relay.cjs'), true);
  assert.equal(app.plugins.includes('./plugins/with-computer-link-privacy.cjs'), true);
});

test('invalid relay build configuration fails closed instead of selecting a broad exception', async () => {
  for (const value of ['', ' relay.example.com', 'relay.example.com ', 'relay.example.com\n', 'relay.example.com\r', 'relay\t.example.com', 'RELAY.example.com', 'https://relay.example.com',
    '*.example.com', 'relay.example.com.', 'relay.example.com:443', 'relay.example.com/path', 'relay.example.com?x=1',
    'user@relay.example.com', '127.0.0.1', '10.0.0.1', 'localhost', 'relay.local', 'relay.internal', 'relay.test',
    'relay.invalid', 'relay.localhost', 'relay.123', 'relay..example.com', '-relay.example.com', 'relay-.example.com',
    'rélais.example.com', 'relay%2eexample.com', `${'a'.repeat(64)}.example.com`,
    ['a'.repeat(63), 'b'.repeat(63), 'c'.repeat(60), 'd'.repeat(12)].join('.'),
    `${'a'.repeat(63)}.${'b'.repeat(63)}.${'c'.repeat(63)}.${'d'.repeat(63)}`]) {
    await assert.rejects(evaluate(value), /relay host/i, value);
  }
});

test('a maximum-length relay hostname reserves a complete certificate namespace', async () => {
  const maximum = ['a'.repeat(63), 'b'.repeat(63), 'c'.repeat(60), 'd'.repeat(11)].join('.');
  assert.equal(maximum.length, 200);
  const result = await evaluate(maximum);
  assert.equal(result._internal.modResults.ios.infoPlist.ClarifyConnectRelayHost, maximum);
  assert.deepEqual(result._internal.modResults.ios.infoPlist.NSAppTransportSecurity.NSExceptionDomains[maximum], exception);
});

test('the complete Expo 57 prebuild config keeps production ATS scoped and the privacy interceptor registered', async () => {
  for (const value of [undefined, host]) {
    const result = await evaluate(value, true);
    const plist = result._internal.modResults.ios.infoPlist;
    const expected = structuredClone(app.ios.infoPlist.NSAppTransportSecurity);
    if (value) Object.assign(expected.NSExceptionDomains, { [value]: exception });
    assert.deepEqual(plist.NSAppTransportSecurity, expected);
    assert.equal(plist.ClarifyConnectRelayHost, value);
    assert.equal(plist.UIApplicationSceneManifest, undefined);
    assert.equal(plist.CFBundleShortVersionString, app.version);
    assert.equal(plist.CFBundleVersion, app.ios.buildNumber);
  }
});

test('stale native scopes and conflicting ATS policies require a clean reviewed build', async () => {
  await assert.rejects(evaluate(undefined, false, { ClarifyConnectRelayHost: host }), /Stale.*relay host/);
  await assert.rejects(evaluate(host, false, { ClarifyConnectRelayHost: 'previous.example.com' }), /Stale.*relay host/);
  await assert.rejects(evaluate(host, false, {
    NSAppTransportSecurity: { NSExceptionDomains: { [host]: { NSExceptionRequiresForwardSecrecy: false } } },
  }), /Conflicting ATS/);
  const result = await evaluate(host, false, {
    ClarifyConnectRelayHost: host,
    NSAppTransportSecurity: { NSExceptionDomains: { [host]: exception } },
  });
  assert.deepEqual(result._internal.modResults.ios.infoPlist.NSAppTransportSecurity.NSExceptionDomains, { [host]: exception });
});
