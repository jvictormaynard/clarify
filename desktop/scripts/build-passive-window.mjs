import {spawnSync} from 'node:child_process';
import {cp, mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

export async function buildPassiveWindow(destination) {
  if (process.platform !== 'win32') throw new Error('The Windows desktop package requires a Windows build host.');
  const root = fileURLToPath(new URL('..', import.meta.url));
  const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  const stage = await mkdtemp(join(tmpdir(), 'clarify-passive-window-'));
  try {
    await cp(join(root, 'electron/native'), stage, {recursive: true});
    const result = spawnSync(process.execPath, [join(root, 'node_modules/node-gyp/bin/node-gyp.js'), 'rebuild',
      '--directory', stage, '--target=' + pkg.devDependencies.electron,
      '--dist-url=https://electronjs.org/headers', '--arch=x64'], {stdio: 'inherit', windowsHide: true});
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error('Windows passive input helper build failed.');
    await cp(join(stage, 'build/Release/passive_window.node'), destination);
  } finally { await rm(stage, {recursive: true, force: true}); }
}
