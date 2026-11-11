import {buildPassiveWindow} from './build-passive-window.mjs';
import {packager} from '@electron/packager';
import {cp, mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const stage = await mkdtemp(join(tmpdir(), 'clarify-electron-package-'));
try {
  const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  await writeFile(join(stage, 'package.json'), JSON.stringify({name: 'clarify-desktop', version: pkg.version, main: 'electron/main.cjs', private: true}));
  await cp(join(root, 'electron'), join(stage, 'electron'), {recursive: true, filter: source => source !== join(root, 'electron/native')});
  await buildPassiveWindow(join(stage, 'electron/passive_window.node'));
  await cp(join(root, 'dist-electron'), join(stage, 'dist'), {recursive: true});
  const html = join(stage, 'dist/index.html');
  await writeFile(html, (await readFile(html, 'utf8')).replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'">`));
  await cp(join(root, 'src-tauri/icons/clarify.png'), join(stage, 'icon.png'));
  await cp(join(root, 'licenses'), join(stage, 'licenses'), {recursive: true});
  await mkdir(join(root, 'electron-dist'), {recursive: true});
  const paths = await packager({dir: stage, name: 'Clarify Desktop', platform: 'win32', arch: 'x64', electronVersion: pkg.devDependencies.electron,
    out: resolve(root, 'electron-dist'), overwrite: true, asar: false, prune: false, icon: join(root, 'src-tauri/icons/clarify.ico'),
    download: process.env.CLARIFY_ELECTRON_CACHE ? {cacheRoot: process.env.CLARIFY_ELECTRON_CACHE} : undefined});
  for (const path of paths) console.log(path);
} finally { await rm(stage, {recursive: true, force: true}); }
