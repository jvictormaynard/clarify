const {contextBridge, ipcRenderer} = require('electron');
const channel = process.argv.find(value => value.startsWith('--clarify-webrtc-channel='))?.split('=')[1];
if (!channel) throw Error('missing_channel');
contextBridge.exposeInMainWorld('computerWebRTC', Object.freeze({
  start: () => ipcRenderer.invoke(channel, 'start'),
  signal: (action, fields) => ipcRenderer.invoke(channel, 'signal', {action, fields}),
  closePeer: ticket => ipcRenderer.invoke(channel, 'close-peer', ticket),
  dispatch: value => ipcRenderer.invoke(channel, 'dispatch', value),
}));
