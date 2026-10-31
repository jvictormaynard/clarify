import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { getStateFromPath } = require('expo-router/build/react-navigation/core/getStateFromPath');
const { getPathFromState } = require('expo-router/build/react-navigation/core/getPathFromState');
const linking = { screens: { Action: 'actions' } };

function cliModule(name: string) {
  const root = dirname(require.resolve('@expo/cli/package.json'));
  return require(join(root, 'build/src/start/server', name));
}

test('Router preserves Unicode, spaces, percent signs and repeated query parameters', () => {
  const state = getStateFromPath('/actions?q=Ol%C3%A1+Stra%C3%9Fe&tag=first&tag=second&literal=%25zz', linking);
  assert.equal(state.routes[0].name, 'Action');
  assert.equal(state.routes[0].params.q, 'Olá Straße');
  assert.deepEqual(state.routes[0].params.tag, ['first', 'second']);
  assert.equal(state.routes[0].params.literal, '%zz');
  const path = getPathFromState({ routes: [{ name: 'Action', params: { q: 'Olá Straße', literal: '%zz' } }] }, linking);
  const restored = getStateFromPath(path, linking);
  assert.equal(restored.routes[0].params.q, 'Olá Straße');
  assert.equal(restored.routes[0].params.literal, '%zz');
});

test('Router decoding has a bounded response for many malformed percent runs', () => {
  const result = spawnSync(process.execPath, ['-e', `
    const { getStateFromPath } = require('expo-router/build/react-navigation/core/getStateFromPath');
    let input = '';
    for (let i = 0; i < 32000; i++) input += '%' + Math.floor(i / 256).toString(16).padStart(2, '0') + '%' + (i % 256).toString(16).padStart(2, '0') + 'x';
    input += '%zz';
    const state = getStateFromPath('/actions?q=' + input, { screens: { Action: 'actions' } });
    if (typeof state?.routes[0].params.q !== 'string') throw new Error('Missing decoded query');
  `], { cwd: process.cwd(), timeout: 5000, encoding: 'utf8', windowsHide: true });
  assert.equal(result.error, undefined, String(result.error));
  assert.equal(result.status, 0, result.stderr);
});

test('Expo validates plugin inputs and outputs with the patched Zod dependency', () => {
  const { PluginSchema, DevToolsPluginOutputSchema } = cliModule('DevToolsPlugin.schema.js');
  const plugin = { packageName: 'offline-test', packageRoot: '/fixture' };
  assert.equal(PluginSchema.safeParse(plugin).success, true);
  assert.equal(PluginSchema.safeParse({ ...plugin, packageName: 42 }).success, false);
  assert.equal(DevToolsPluginOutputSchema.safeParse([{ type: 'text', text: 'offline', level: 'info' }]).success, true);
  assert.equal(DevToolsPluginOutputSchema.safeParse([{ type: 'image', url: false }]).success, false);
});

test('Expo MCP advertises complete command schemas without starting a tunnel', async () => {
  const { TunnelMcpServerProxy } = await import('@expo/mcp-tunnel');
  const { addMcpCapabilities } = cliModule('MCPDevToolsPluginCLIExtensions.js');
  const proxy = new TunnelMcpServerProxy('ws://127.0.0.1:1', {
    projectRoot: '/fixture', devServerUrl: 'http://127.0.0.1:1',
  });
  const plugin = {
    packageName: 'offline-test', packageRoot: '/fixture',
    cliExtensions: { description: 'Offline fixture', entryPoint: 'unused.cjs', commands: [
      { name: 'inspect', title: 'Inspect fixture', environments: ['mcp'], parameters: [
        { name: 'text', type: 'text', description: 'Input text' },
        { name: 'count', type: 'number', description: 'Item count' },
        { name: 'confirmed', type: 'confirm', description: 'Consent' },
      ] },
      { name: 'cli-only', title: 'Private CLI command', environments: ['cli'] },
    ] },
  };
  try {
    await addMcpCapabilities(proxy, { devtoolsPluginManager: { queryPluginsAsync: async () => [plugin] } });
    const tool = proxy.getRegisteredTools().get('offline-test');
    assert.ok(tool);
    const schema = tool.inputSchema as { required: string[]; properties: Record<string, any> };
    assert.deepEqual(schema.required, ['parameters']);
    const parameters = schema.properties.parameters;
    assert.deepEqual(parameters.required, ['command']);
    assert.deepEqual(parameters.properties.command.enum, ['inspect']);
    for (const [key, type] of [['text', 'string'], ['count', 'number'], ['confirmed', 'boolean']]) {
      assert.equal(parameters.properties[key].type, type);
      assert.ok(parameters.properties[key].description.length > 0);
    }
    assert.equal(parameters.additionalProperties, false);
    assert.equal(proxy.connected, false);
  } finally { await proxy.close(); }
});
