'use strict';
// The parent can close its diagnostic pipe before Chromium finishes shutting down.
// Losing stderr must not make Electron show an uncaught exception dialog.
process.stderr.on('error', () => {});
// stdout belongs exclusively to the Python JSON-lines protocol.
console.log = console.info = console.debug = (...args) => console.error(...args);
const electron = require('electron');
const dataDirectory = process.env.CLARIFY_DATA_DIR?.trim();
if (process.platform === 'darwin' && dataDirectory) {
  const chromium = require('node:path').resolve(dataDirectory, 'chromium');
  require('node:fs').mkdirSync(chromium, {recursive: true, mode: 0o700});
  electron.app.setPath('userData', chromium);
  electron.app.setPath('sessionData', chromium);
}
// Electron replaces process.stdin with an EOF stream on Windows. Read the
// inherited QProcess pipe directly through fs, which uses asynchronous I/O.
const input = process.platform === 'win32'
  ? require('node:fs').createReadStream(null, {fd: 0, autoClose: false})
  : process.stdin;
require('./host.cjs').startHost(electron, input).catch(error => { console.error(error); process.exit(1); });
