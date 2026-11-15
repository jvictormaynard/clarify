'use strict';
const {contextBridge, ipcRenderer} = require('electron');
const subscribe = (topic, listener) => {
  const callback = (_event, value) => listener(value);
  ipcRenderer.on(topic, callback);
  return () => ipcRenderer.removeListener(topic, callback);
};
contextBridge.exposeInMainWorld('clarifyDesktop', Object.freeze({
  call: (channel, method, args) => ipcRenderer.invoke('clarify:call', channel, method, args),
  window: (method, value) => ipcRenderer.invoke('clarify:window', method, value),
  subscribe: (listener) => subscribe('clarify:state', listener),
  onWindow: (listener) => subscribe('clarify:window-event', listener),
  ready: () => ipcRenderer.invoke('clarify:renderer-ready'),
}));

ipcRenderer.on('clarify:stop-audio', (_event, lease) => {
  if (typeof lease !== 'string') return;
  // Revoke even a pending Play response before acknowledging capture admission.
  document.dispatchEvent(new CustomEvent('clarify-stop-audio', {detail: lease}));
  for (const audio of document.querySelectorAll('audio')) audio.pause();
  void ipcRenderer.invoke('clarify:call', 'settings', 'endRecordingPlayback', [lease]);
});
