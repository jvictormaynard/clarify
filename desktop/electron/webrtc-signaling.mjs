import {clientOffer, hostAnswer} from './webrtc-transport.mjs';

// Account credential is supplied by the containing app. No persistent token here.
export function signaling(url, authorization, host) {
  if (!url.startsWith('https://') && !url.startsWith('http://127.0.0.1:')) throw Error('https_required');
  return async (action, fields = {}) => {
    const response = await fetch(url, {method: 'POST', redirect: 'error', cache: 'no-store',
      headers: {'Content-Type': 'application/json', Authorization: authorization},
      body: JSON.stringify({action, host, ...fields}), signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw Error('signaling_rejected');
    const raw = await response.text();
    if (raw.length > 131072) throw Error('signal_too_large');
    return JSON.parse(raw);
  };
}

export async function connectComputer({signal, host, pinnedPublicKey, relay = false, abort, onClose}) {
  const {ticket} = await signal('create', {relay});
  const {iceServers} = await signal('turn', {ticket});
  const client = await clientOffer({iceServers, relay, onClose});
  try {
    await signal('offer', {ticket, payload: client.offer});
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      abort?.throwIfAborted();
      const {answer} = await signal('poll', {ticket});
      if (answer) { await client.accept({ticket, host, answer, pinnedPublicKey}); return client; }
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    throw Error('signaling_timeout');
  } catch (error) { client.pc.close(); throw error; }
}

export async function answerComputer({signal, ticket, host, privateKey, dispatch, relay = false, onClose}) {
  const {offer, relay: forcedRelay} = await signal('poll', {ticket});
  if (!offer) throw Error('offer_missing');
  const {iceServers} = await signal('turn', {ticket});
  const result = await hostAnswer({ticket, host, offer, privateKey, iceServers, relay: relay || forcedRelay, dispatch, onClose});
  try { await signal('answer', {ticket, payload: result.answer}); return result; }
  catch (error) { result.pc.close(); throw error; }
}
