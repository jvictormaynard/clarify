// Main-only private-pipe channel. No Settings/pill IPC route exposes this API.
const {startComputerWebRTC} = require('./webrtc-host.cjs');
function computerWebRTCPipe(electron, send) {
  let peer, generation = 0, next = 0;
  const pending = new Map();
  const stop = () => {
    generation++; peer?.stop(); peer = undefined;
    for (const p of pending.values()) { clearTimeout(p.timer); p.reject(Error('response_uncertain')); }
    pending.clear();
  };
  const call = (kind, value) => {
    const control = kind !== 'dispatch' || value?.request?.method === 'DELETE' || value?.request?.recognition === 'cancel';
    if (pending.size >= (control ? 40 : 32)) return Promise.reject(Error('capacity'));
    const requestID = ++next;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(requestID); reject(Error('response_uncertain')); }, 120000);
      pending.set(requestID, {resolve, reject, timer});
      send({event:'computer-webrtc', requestID, kind, value});
    });
  };
  function receive(message) {
    if (message.event === 'computer-webrtc-reply') {
      const p = pending.get(message.requestID);
      if (p) { pending.delete(message.requestID); clearTimeout(p.timer); message.error ? p.reject(Error('connection_unavailable')) : p.resolve(message.result); }
      return true;
    }
    if (message.event !== 'computer-webrtc-config') return false;
    stop(); const owner = generation;
    if (message.config) void startComputerWebRTC({...electron, ...message.config,
      signal:(action, fields) => call('signal', {action, fields}),
      dispatch:(request, ticket) => call('dispatch', {request, ticket}),
      closePeer:ticket => { void call('close-peer', ticket).catch(() => {}); },
    }).then(value => {
      if (owner !== generation) { value.stop(); return; }
      peer = value; send({event:'computer-webrtc-state', connected:true});
    }).catch(() => { if (owner === generation) send({event:'computer-webrtc-state', connected:false}); });
    else send({event:'computer-webrtc-state', connected:false});
    return true;
  }
  return {receive, stop};
}
module.exports = {computerWebRTCPipe};
