import {buildNativeWindow} from './build-native-window.mjs';
import {packager} from '@electron/packager';
import {execFileSync} from 'node:child_process';
import {cp, mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const mac = process.platform === 'darwin';
if (!mac && process.platform !== 'win32') throw new Error('Electron packaging requires macOS or Windows.');
const stage = await mkdtemp(join(tmpdir(), 'clarify-electron-package-'));
try {
  const pkg = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  await writeFile(join(stage, 'package.json'), JSON.stringify({name: 'clarify-desktop', version: pkg.version, main: 'electron/main.cjs', private: true}));
  await cp(join(root, 'electron'), join(stage, 'electron'), {recursive: true, filter: source => source !== join(root, 'electron/native')});
  await buildNativeWindow(join(stage, 'electron'));
  await cp(join(root, 'dist-electron'), join(stage, 'dist'), {recursive: true});
  const html = join(stage, 'dist/index.html');
  await writeFile(html, (await readFile(html, 'utf8')).replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; media-src blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'">`));
  await cp(join(root, 'assets/clarify.png'), join(stage, 'icon.png'));
  await cp(join(root, 'licenses'), join(stage, 'licenses'), {recursive: true});
  await mkdir(join(root, 'electron-dist'), {recursive: true});
  const icon = mac ? join(stage, 'icon.icns') : join(root, 'assets/clarify.ico');
  if (mac) execFileSync('/usr/bin/sips', ['-s', 'format', 'icns', join(stage, 'icon.png'), '--out', icon]);
  const paths = await packager({dir: stage, name: 'Clarify Desktop', platform: process.platform, arch: mac ? process.arch : 'x64', electronVersion: pkg.devDependencies.electron,
    out: resolve(root, 'electron-dist'), overwrite: true, asar: false, prune: false, icon,
    ...(mac ? {
      appBundleId: 'com.clarify.desktop.presentation',
      extendInfo: {LSUIElement: true},
      ignore: /^\/icon\.icns$/,
      // Ad hoc signatures for the local build have no Apple Team ID.
      osxSign: {
        identity: '-', identityValidation: false, continueOnError: false,
        optionsForFile: () => ({hardenedRuntime: false, timestamp: 'none'}),
      },
    } : {}),
    download: process.env.CLARIFY_ELECTRON_CACHE ? {cacheRoot: process.env.CLARIFY_ELECTRON_CACHE} : undefined});
  for (const path of paths) console.log(path);
} finally { await rm(stage, {recursive: true, force: true}); }
