// Runs in a dedicated Chromium/Electron renderer. No provider keys or microphone.
export const MAX_FRAME = 48 * 1024;
export const MAX_BODY = 16 * 1024 * 1024;
const encoder = new TextEncoder();
const bytes = value => encoder.encode(JSON.stringify(value));
const fail = message => new Error(message);
const controlRequest = body => body?.method === 'DELETE' || body?.recognition === 'cancel';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export async function gather(pc, timeout = 10000) {
  if (pc.iceGatheringState === 'complete') return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(fail('ice_timeout')); }, timeout);
    const check = () => { if (pc.iceGatheringState === 'complete') { cleanup(); resolve(); } };
    const cleanup = () => { clearTimeout(timer); pc.removeEventListener('icegatheringstatechange', check); };
    pc.addEventListener('icegatheringstatechange', check); check();
  });
}

// A lost response is uncertain. This object never reconnects or retries RPCs.
export class ComputerChannel {
  constructor(channel, { dispatch, timeout = 120000, onClose } = {}) {
    this.channel = channel; this.dispatch = dispatch; this.timeout = timeout;
    this.onClose = onClose; this.closed = false;
    this.executing = 0;
    this.pending = new Map(); this.incoming = new Map(); this.seen = new Set();
    channel.onmessage = event => this.receive(event.data).catch(() => this.close());
    channel.onclose = () => this.close();
    channel.onerror = () => this.close();
  }
  async send(message) {
    if (this.closed) throw fail('response_uncertain');
    const data = JSON.stringify(message);
    if (encoder.encode(data).length > MAX_FRAME) throw fail('frame_too_large');
    const deadline = Date.now() + 10000;
    while (this.channel.bufferedAmount > 256 * 1024) {
      if (this.closed) throw fail('response_uncertain');
      if (Date.now() > deadline) throw fail('backpressure_timeout');
      await sleep(5);
    }
    if (this.channel.readyState !== 'open') throw fail('response_uncertain');
    this.channel.send(data);
  }
  async chunks(kind, id, body) {
    const raw = JSON.stringify(body);
    if (encoder.encode(raw).length > MAX_BODY) throw fail('body_too_large');
    // Small Unicode chunks also bound JSON escaping and UTF-8 expansion.
    const count = Math.ceil(raw.length / 4000);
    await this.send({kind: 'begin', id, direction: kind, count});
    for (let i = 0; i < count; i++) await this.send({kind: 'chunk', id, index: i, data: raw.slice(i * 4000, (i + 1) * 4000)});
    await this.send({kind: 'end', id});
  }
  async request(body, {timeout = this.timeout} = {}) {
    if (this.closed) throw fail('response_uncertain');
    if (!Number.isFinite(timeout) || timeout < 1 || timeout > 120000) throw fail('invalid_timeout');
    if (this.pending.size >= (controlRequest(body) ? 10 : 8)) throw fail('capacity');
    const id = crypto.randomUUID();
    const result = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(fail('response_uncertain')); }, timeout);
      this.pending.set(id, { resolve, reject, timer });
    });
    this.chunks('request', id, body).catch(error => {
      const item = this.pending.get(id);
      if (item) { clearTimeout(item.timer); this.pending.delete(id); item.reject(error); }
    });
    return result;
  }
  async receive(raw) {
    if (this.closed) throw fail('response_uncertain');
    if (typeof raw !== 'string' || encoder.encode(raw).length > MAX_FRAME) throw fail('invalid_frame');
    const m = JSON.parse(raw);
    if (typeof m.id !== 'string' || !/^[a-f0-9-]{36}$/.test(m.id)) throw fail('invalid_id');
    if (m.kind === 'begin') {
      if (this.incoming.size >= 10 || this.seen.size >= 4096 || this.seen.has(m.id) || !['request','response'].includes(m.direction) || !Number.isInteger(m.count) || m.count < 1 || m.count > 4195) throw fail('invalid_begin');
      this.seen.add(m.id);
      const timer = setTimeout(() => this.close(), 15000);
      this.incoming.set(m.id, {direction: m.direction, count: m.count, parts: [], size: 0, timer});
      return;
    }
    const item = this.incoming.get(m.id);
    if (!item) throw fail('unknown_frame');
    if (m.kind === 'chunk') {
      if (m.index !== item.parts.length || item.parts.length >= item.count || typeof m.data !== 'string') throw fail('invalid_chunk');
      item.size += encoder.encode(m.data).length;
      if (item.size > MAX_BODY) throw fail('body_too_large');
      item.parts.push(m.data); return;
    }
    if (m.kind !== 'end' || item.parts.length !== item.count) throw fail('invalid_end');
    clearTimeout(item.timer); this.incoming.delete(m.id);
    const body = JSON.parse(item.parts.join(''));
    if (item.direction === 'response') {
      const pending = this.pending.get(m.id);
      if (!pending) return;
      clearTimeout(pending.timer); this.pending.delete(m.id); pending.resolve(body);
    } else {
      if (!this.dispatch) throw fail('unexpected_request');
      if (this.executing >= (controlRequest(body) ? 10 : 8)) { await this.chunks('response', m.id, {status:429,body:{error:'busy'}}); return; }
      this.executing++;
      // Dispatch concurrently: a cancel must pass an inference waiting for completion.
      Promise.resolve().then(() => this.dispatch(body)).then(
        response => this.chunks('response', m.id, response),
        () => this.chunks('response', m.id, {status: 500, body: {error: 'internal_error'}}),
      ).catch(() => this.close()).finally(() => { this.executing--; });
    }
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(fail('response_uncertain')); }
    for (const item of this.incoming.values()) clearTimeout(item.timer);
    this.pending.clear(); this.incoming.clear();
    if (this.channel.readyState !== 'closed') this.channel.close();
    this.onClose?.();
  }
}

const signedPayload = (ticket, host, sdp) => bytes({ticket, host, sdp});
export async function hostAnswer({ ticket, host, offer, privateKey, iceServers = [], relay = false, dispatch, onClose }) {
  const pc = new RTCPeerConnection({iceServers, iceTransportPolicy: relay ? 'relay' : 'all'});
  pc.ondatachannel = ({channel}) => {
    if (channel.label !== 'clarify-computer-v1' || !channel.ordered || channel.maxRetransmits !== null || channel.maxPacketLifeTime !== null) { channel.close(); return; }
    if (pc.clarifyChannel) { channel.close(); return; }
    pc.clarifyChannel = new ComputerChannel(channel, {dispatch, onClose: () => { pc.close(); onClose?.(); }});
  };
  try {
    await pc.setRemoteDescription(offer);
    await pc.setLocalDescription(await pc.createAnswer()); await gather(pc);
    const sdp = pc.localDescription.toJSON();
    const signature = Array.from(new Uint8Array(await crypto.subtle.sign({name: 'ECDSA', hash: 'SHA-256'}, privateKey, signedPayload(ticket, host, sdp))));
    return {pc, answer: {sdp, signature}};
  } catch (error) { pc.close(); throw error; }
}

export async function clientOffer({iceServers = [], relay = false, onClose} = {}) {
  const pc = new RTCPeerConnection({iceServers, iceTransportPolicy: relay ? 'relay' : 'all'});
  try {
    const channel = pc.createDataChannel('clarify-computer-v1', {ordered: true});
    const rpc = new ComputerChannel(channel, {onClose: () => { pc.close(); onClose?.(); }});
    pc.addEventListener('connectionstatechange', () => {
      if (['closed', 'failed'].includes(pc.connectionState)) rpc.close();
    });
    await pc.setLocalDescription(await pc.createOffer()); await gather(pc);
    return {pc, rpc, offer: pc.localDescription.toJSON(), async accept({ticket, host, answer, pinnedPublicKey}) {
      const key = await crypto.subtle.importKey('jwk', pinnedPublicKey, {name: 'ECDSA', namedCurve: 'P-256'}, false, ['verify']);
      if (!await crypto.subtle.verify({name: 'ECDSA', hash: 'SHA-256'}, key, new Uint8Array(answer.signature), signedPayload(ticket, host, answer.sdp))) { pc.close(); throw fail('host_key_mismatch'); }
      await pc.setRemoteDescription(answer.sdp);
      const deadline = Date.now() + 15000;
      while (channel.readyState !== 'open') { if (Date.now() > deadline) { pc.close(); throw fail('connect_timeout'); } await sleep(10); }
    }};
  } catch (error) { pc.close(); throw error; }
}
