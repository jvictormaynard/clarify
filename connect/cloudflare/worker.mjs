import {
  CONTROL_URL, Failure, GRANT_TTL, configuration, deadline, decode32, encode64, exact, fail,
  grantInput, hexHash, hostname, owner, random32, readJSON, reply,
} from './protocol.mjs';
import { consume, reserve } from './storage.mjs';
import { provision } from './cloudflare.mjs';

export function createWorker(dependencies = {}) {
  const io = {
    fetch: dependencies.fetch ?? ((...args) => globalThis.fetch(...args)),
    now: dependencies.now ?? (() => Math.floor(Date.now() / 1000)),
    timeoutMs: dependencies.timeoutMs ?? 5000,
  };
  return { async fetch(request, env) {
    try {
      const config = configuration(env);
      const url = new URL(request.url);
      if (url.origin !== CONTROL_URL || url.search || url.hash || url.username || url.password) fail(400, 'invalid_request');
      if (!['/v1/connect/grants', '/v1/connect/claim'].includes(url.pathname)) fail(404, 'not_found');
      if (request.method !== 'POST') fail(405, 'method_not_allowed');
      const value = await deadline(io.timeoutMs, signal => readJSON(request, 4096, signal));
      const db = env.DB; // No Sessions API: all queries execute on D1's primary.
      if (url.pathname === '/v1/connect/grants') {
        const input = grantInput(value);
        const account = await owner(request, config, io);
        const host = await hostname(input.hpke_public_key);
        const grant = random32();
        const now = io.now();
        await reserve(db, input, account, host, await hexHash(grant), now, config.cap);
        return reply(200, { schema_version: 1, grant: encode64(grant), expires_at: now + GRANT_TTL, control_url: CONTROL_URL, hostname: host });
      }
      exact(value, ['grant']);
      const hash = await hexHash(decode32(value.grant));
      const operation = encode64(random32());
      const row = await consume(db, hash, operation, io.now());
      return reply(200, await provision(db, row, operation, config, io));
    } catch (error) {
      // Do not log request bodies, sessions, grants, tokens, or provider errors.
      return reply(error instanceof Failure ? error.status : 503,
        { code: error instanceof Failure ? error.code : 'connect_unavailable' });
    }
  } };
}

export default createWorker();
