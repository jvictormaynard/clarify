'use strict';
// stdout belongs exclusively to the Python JSON-lines protocol.
console.log = console.info = console.debug = (...args) => console.error(...args);
// Electron replaces process.stdin with an EOF stream on Windows. Read the
// inherited QProcess pipe directly through fs, which uses asynchronous I/O.
const input = process.platform === 'win32'
  ? require('node:fs').createReadStream(null, {fd: 0, autoClose: false})
  : process.stdin;
require('./host.cjs').startHost(require('electron'), input).catch(error => { console.error(error); process.exit(1); });
