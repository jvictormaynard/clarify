export const CONTROL_URL = 'https://clarify-connect.victormaynard.com';
export const TUNNEL_DOMAIN = 'victormaynard.com';
// Clients accept at most five minutes. A four-minute issued lifetime leaves
// room for a small clock difference without extending server authorization.
export const GRANT_TTL = 240;
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const CF_ID = /^[0-9a-f]{32}$/;
const encoder = new TextEncoder();

export class Failure extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
export const fail = (status, code) => { throw new Failure(status, code); };
export const reply = (status, value) => Response.json(value, {
  status, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' },
});
export const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export function exact(value, keys) {
  if (!object(value) || Object.keys(value).length !== keys.length || !keys.every(key => Object.hasOwn(value, key))) {
    fail(400, 'invalid_request');
  }
}

export function encode64(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}
export function decode32(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(value)) fail(400, 'invalid_request');
  const bytes = Uint8Array.from(atob(value.replaceAll('-', '+').replaceAll('_', '/') + '='), char => char.charCodeAt(0));
  if (bytes.length !== 32 || encode64(bytes) !== value) fail(400, 'invalid_request');
  return bytes;
}
export const random32 = () => crypto.getRandomValues(new Uint8Array(32));
export const sha256 = async bytes => new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
export const hexHash = async bytes => [...await sha256(bytes)].map(byte => byte.toString(16).padStart(2, '0')).join('');

export async function hostname(publicKey) {
  const digest = await sha256(decode32(publicKey));
  let value = 0;
  let bits = 0;
  let result = '';
  for (const byte of digest) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      result += 'abcdefghijklmnopqrstuvwxyz234567'[(value >>> bits) & 31];
    }
  }
  if (bits) result += 'abcdefghijklmnopqrstuvwxyz234567'[(value << (5 - bits)) & 31];
  return `c-${result}.${TUNNEL_DOMAIN}`;
}

export function grantInput(value) {
  exact(value, ['computer_id', 'certificate_sha256', 'hpke_public_key', 'origin_port']);
  if (typeof value.computer_id !== 'string' || !UUID.test(value.computer_id) ||
      typeof value.certificate_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.certificate_sha256) ||
      !Number.isInteger(value.origin_port) || value.origin_port < 1 || value.origin_port > 65535 ||
      !decode32(value.hpke_public_key).some(byte => byte !== 0)) fail(400, 'invalid_request');
  return value;
}

export function configuration(env) {
  if (env.CONNECT_ENABLED !== 'true') fail(503, 'connect_disabled');
  let auth;
  try { auth = new URL(env.CLARIFY_API_URL); } catch { fail(503, 'invalid_configuration'); }
  const cap = Number(env.GLOBAL_COMPUTER_LIMIT);
  if (env.CONTROL_URL !== CONTROL_URL || env.TUNNEL_DOMAIN !== TUNNEL_DOMAIN ||
      auth.protocol !== 'https:' || auth.origin !== env.CLARIFY_API_URL || auth.username || auth.password ||
      auth.port || !/^[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/.test(auth.hostname) ||
      !CF_ID.test(env.CF_ACCOUNT_ID ?? '') || /^0+$/.test(env.CF_ACCOUNT_ID) ||
      !CF_ID.test(env.CF_ZONE_ID ?? '') || /^0+$/.test(env.CF_ZONE_ID) ||
      typeof env.CF_API_TOKEN !== 'string' || !/^[\x21-\x7e]{16,512}$/.test(env.CF_API_TOKEN) ||
      !/^[1-9][0-9]{0,2}$/.test(env.GLOBAL_COMPUTER_LIMIT ?? '') || !Number.isInteger(cap) || cap > 900 ||
      typeof env.DB?.prepare !== 'function' || typeof env.DB?.batch !== 'function') fail(503, 'invalid_configuration');
  return { account: env.CF_ACCOUNT_ID, zone: env.CF_ZONE_ID, token: env.CF_API_TOKEN, api: auth.origin, cap };
}

// The deadline includes fetch and body reads. Cancellation is never awaited.
export async function deadline(milliseconds, action) {
  const controller = new AbortController();
  let timer;
  const expired = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Failure(504, 'upstream_timeout'));
    }, milliseconds);
  });
  try { return await Promise.race([action(controller.signal), expired]); }
  finally { clearTimeout(timer); controller.abort(); }
}

export async function readJSON(message, limit, signal, upstream = false) {
  const invalid = () => fail(upstream ? 502 : 400, upstream ? 'invalid_upstream' : 'invalid_request');
  const oversized = () => fail(upstream ? 502 : 413, upstream ? 'invalid_upstream' : 'body_too_large');
  let reader;
  const cancel = () => { if (reader) void reader.cancel().catch(() => {}); };
  try {
    const type = message.headers.get('content-type') ?? '';
    if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(type)) {
      fail(upstream ? 502 : 415, upstream ? 'invalid_upstream' : 'json_required');
    }
    const length = message.headers.get('content-length');
    if (length !== null && !/^\d+$/.test(length)) invalid();
    if (length !== null && Number(length) > limit) oversized();
    if (!message.body) invalid();
    reader = message.body.getReader();
    signal.addEventListener('abort', cancel, { once: true });
    if (signal.aborted) invalid();
    const chunks = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) oversized();
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { invalid(); }
  } finally {
    signal.removeEventListener('abort', cancel);
    cancel();
    // Reject bodies without acquiring a reader too (for example declared overflow).
    if (!reader && message.body) void message.body.cancel().catch(() => {});
  }
}

export async function owner(request, config, io) {
  const session = request.headers.get('X-Session-Token');
  if (!session || !/^[\x21-\x7e]{1,1024}$/.test(session)) fail(401, 'authentication_required');
  const account = await deadline(io.timeoutMs, async signal => {
    const response = await io.fetch(config.api + '/v1/account', {
      method: 'GET', redirect: 'manual', signal,
      headers: { Accept: 'application/json', 'X-Session-Token': session },
    });
    if (response.status !== 200) {
      if (response.body) void response.body.cancel().catch(() => {});
      fail([401, 403].includes(response.status) ? 401 : 502, 'authentication_required');
    }
    return readJSON(response, 16 * 1024, signal, true);
  });
  // AccountView already enforces an active user and a verified primary email.
  if (!object(account) || typeof account.id !== 'string' || !UUID.test(account.id)) fail(502, 'invalid_upstream');
  return hexHash(encoder.encode(account.id));
}
