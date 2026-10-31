// Run mobile checks with the caller's Python interpreter on every platform.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

function commands(python, node = process.execPath, root = path.resolve(__dirname, '..')) {
  const tests = fs.readdirSync(path.join(root, 'tests')).filter(name => name.endsWith('.test.ts')).sort();
  return [
    [python, '../scripts/sync_locales.py', '--check'],
    [python, 'scripts/sync-prompts.py', '--check'],
    [node, 'node_modules/typescript/bin/tsc', '--noEmit'],
    [node, 'node_modules/expo/bin/cli', 'lint'],
    [node, '--experimental-strip-types', '--test', ...tests.map(name => `tests/${name}`)],
    [node, 'node_modules/expo/bin/cli', 'install', '--check'],
  ];
}

function check(run = spawnSync, environment = process.env) {
  const python = environment.CLARIFY_TEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  for (const [executable, ...args] of commands(python)) {
    const result = run(executable, args, {
      cwd: path.resolve(__dirname, '..'), stdio: 'inherit', windowsHide: true,
      env: { ...environment, EXPO_NO_DOTENV: '1', EXPO_NO_TELEMETRY: '1' },
    });
    if (result.error || result.status !== 0) return result.status || 1;
  }
  return 0;
}

module.exports = { commands, check };
if (require.main === module) process.exitCode = check();
