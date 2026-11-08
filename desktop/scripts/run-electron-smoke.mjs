import {fileURLToPath} from 'node:url';
import {spawnOwned, stopProcessTree} from './stop-process-tree.mjs';

// The owner covers Chromium and the Python launcher's descendants, including
// a failed assertion or CI cancellation. The inner probe needs their real PIDs.
let child;
const stop = () => { if (child) stopProcessTree(child); };
try {
  child = spawnOwned(process.execPath, [fileURLToPath(new URL('./test-electron.mjs', import.meta.url))], {
    env: process.env, stdio: 'inherit', windowsHide: true, ownDetached: true,
  });
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  process.exitCode = await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', code => resolve(code ?? 1));
  });
} finally {
  process.removeListener('SIGINT', stop);
  process.removeListener('SIGTERM', stop);
  if (child && (child.exitCode === null || process.platform !== 'win32')) stop();
}
