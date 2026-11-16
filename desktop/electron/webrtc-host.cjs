// Electron main-process owner. The Python bridge callback must run on its worker
// pool so a cancellation request can pass an inference waiting for completion.
const path = require('node:path');
const crypto = require('node:crypto');
const {fileURLToPath} = require('node:url');

async function startComputerWebRTC({BrowserWindow, ipcMain, session, host, privateJwk, signal, dispatch, closePeer = () => {}}) {
  const channel = 'clarify-webrtc-' + crypto.randomUUID();
  const isolated = session.fromPartition(channel);
  isolated.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  isolated.setPermissionCheckHandler(() => false);
  const assets = new Set(['webrtc-host.html', 'webrtc-worker.mjs', 'webrtc-transport.mjs', 'webrtc-signaling.mjs'].map(name => path.join(__dirname, name)));
  isolated.webRequest.onBeforeRequest((details, callback) => {
    let allowed = false;
    try { allowed = assets.has(fileURLToPath(details.url)); } catch {}
    callback({cancel: !allowed});
  });
  const window = new BrowserWindow({show: false, webPreferences: {
    session: isolated, preload: path.join(__dirname, 'webrtc-preload.cjs'),
    contextIsolation: true, nodeIntegration: false, sandbox: true,
    backgroundThrottling: false, devTools: false, webSecurity: true,
    additionalArguments: ['--clarify-webrtc-channel=' + channel],
  }});
  window.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
  window.webContents.on('will-navigate', event => event.preventDefault());
  const peers = new Set();
  ipcMain.handle(channel, async (event, kind, value) => {
    if (event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) throw Error('unauthorized_sender');
    if (Buffer.byteLength(JSON.stringify(value ?? null)) > 17 * 1024 * 1024) throw Error('body_too_large');
    if (kind === 'start') return {host, privateJwk};
    if (kind === 'signal') return signal(value.action, value.fields);
    if (kind === 'dispatch') {
      if (typeof value?.ticket !== 'string' || value.ticket.length !== 43) throw Error('invalid_peer');
      if (!peers.has(value.ticket) && peers.size >= 8) throw Error('capacity');
      peers.add(value.ticket);
      return dispatch(value.request, value.ticket);
    }
    if (kind === 'close-peer') { peers.delete(value); return closePeer(value); }
    throw Error('invalid_command');
  });
  const cleanup = () => { ipcMain.removeHandler(channel); for (const ticket of peers) closePeer(ticket); peers.clear(); };
  const stop = () => { cleanup(); if (!window.isDestroyed()) window.destroy(); };
  window.once('closed', cleanup);
  try { await window.loadFile(path.join(__dirname, 'webrtc-host.html')); }
  catch (error) { stop(); throw error; }
  return {stop};
}
module.exports = {startComputerWebRTC};
