import {answerComputer} from './webrtc-signaling.mjs';
const bridge = window.computerWebRTC;
const {host, privateJwk} = await bridge.start();
const privateKey = await crypto.subtle.importKey('jwk', privateJwk, {name:'ECDSA', namedCurve:'P-256'}, false, ['sign']);
const signal = (action, fields) => bridge.signal(action, fields);
const peers = new Map();
let stopped = false;
window.addEventListener('pagehide', () => { stopped=true; for (const peer of [...peers.values()]) peer.close(); });
while (!stopped) {
  try {
    for (const [ticket, peer] of peers) {
      try { await signal('poll', {ticket}); }
      catch { peer.close(); }
    }
    const {tickets} = await signal('pending');
    for (const ticket of tickets) {
      if (peers.has(ticket) || peers.size >= 8) continue;
      let peer, retired = false;
      const close = () => {
        if (retired) return;
        retired = true; peers.delete(ticket);
        peer?.pc.clarifyChannel?.close(); peer?.pc.close();
        void Promise.resolve(bridge.closePeer(ticket)).catch(() => {});
      };
      // The authenticated poll renews a bounded session lease. Setup ticket
      // age must not interrupt an accepted 300-second recording.
      peer = await answerComputer({signal, ticket, host, privateKey,
        dispatch: request => bridge.dispatch({ticket, request}), onClose: close});
      if (retired) { peer.pc.close(); continue; }
      peer.close = close; peers.set(ticket, peer);
      peer.pc.addEventListener('connectionstatechange', () => {
        if (['closed', 'failed'].includes(peer.pc.connectionState)) close();
      });
    }
  } catch {
    // Loss of account authority closes all established peers, without replay.
    for (const peer of [...peers.values()]) peer.close();
  }
  await new Promise(resolve => setTimeout(resolve, 1000));
}
