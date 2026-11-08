import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';

// Execute the real migration and bound SQL. Only the D1 transport is replaced.
export class LocalD1 {
  constructor() {
    this.sqlite = new DatabaseSync(':memory:');
    this.sqlite.exec(readFileSync(new URL('../migrations/0001_connect.sql', import.meta.url), 'utf8'));
  }
  prepare(sql) {
    const query = this.sqlite.prepare(sql);
    let args = [];
    const execute = () => {
      const results = query.all(...args).map(row => ({ ...row }));
      return { success: true, results, meta: { changes: this.sqlite.prepare('SELECT changes() AS n').get().n } };
    };
    const statement = {
      bind: (...values) => { args = values; return statement; },
      all: async () => execute(),
      run: async () => execute(),
      first: async () => execute().results[0] ?? null,
      execute,
    };
    return statement;
  }
  async batch(statements) {
    this.sqlite.exec('BEGIN IMMEDIATE');
    try {
      const result = statements.map(statement => statement.execute());
      this.sqlite.exec('COMMIT');
      return result;
    } catch (error) {
      this.sqlite.exec('ROLLBACK');
      throw error;
    }
  }
  rows() { return this.sqlite.prepare('SELECT * FROM computers').all().map(row => ({ ...row })); }
  close() { this.sqlite.close(); }
}

export const CONTROL = 'https://clarify-connect.victormaynard.com';
export const API = 'https://clarify-account.example.invalid';
export const OWNER = '11111111-1111-4111-8111-111111111111';
export const TUNNEL = '22222222-2222-4222-8222-222222222222';
export const DNS = 'd'.repeat(32);
export const ACCOUNT = 'a'.repeat(32);
export const ZONE = 'b'.repeat(32);
export const key = seed => Buffer.from(Array.from({ length: 32 }, (_, i) => (seed + i) % 256)).toString('base64url');
export const body = (n = 1) => ({
  computer_id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
  certificate_sha256: 'c'.repeat(64), hpke_public_key: key(n), origin_port: 49321,
});

export function environment(db, extra = {}) {
  return {
    CONNECT_ENABLED: 'true', CONTROL_URL: CONTROL, TUNNEL_DOMAIN: 'victormaynard.com',
    CLARIFY_API_URL: API, CF_ACCOUNT_ID: ACCOUNT, CF_ZONE_ID: ZONE,
    CF_API_TOKEN: 'server-only-test-token', GLOBAL_COMPUTER_LIMIT: '900', DB: db, ...extra,
  };
}

export function request(path, value, headers = {}) {
  return new Request(CONTROL + path, { method: 'POST', headers: {
    'content-type': 'application/json', ...headers,
  }, body: JSON.stringify(value) });
}

export const grantRequest = value => request('/v1/connect/grants', value, { 'X-Session-Token': 'private-session' });
export const claimRequest = grant => request('/v1/connect/claim', { grant });
export const json = (result, extra = {}) => Response.json({ success: true, result, ...extra });

export function cloudflareFake() {
  const calls = [];
  const fake = {
    calls, owner: OWNER, count: 0, missingCount: false, fail: null, auth: null,
    tunnel: null, record: null, config: null,
    async fetch(url, init) {
      calls.push({ url, ...init });
      if (url === API + '/v1/account') {
        return fake.auth ? fake.auth() : Response.json({ id: fake.owner, email: 'do-not-store@example.invalid', usage: {} });
      }
      if (!url.startsWith('https://api.cloudflare.com/client/v4/')) throw new Error('Unexpected network target');
      if (fake.fail) {
        const response = await fake.fail(url, init);
        if (response) return response;
      }
      const path = new URL(url).pathname;
      if (path.endsWith('/tunnels') && init.method === 'GET') {
        return json(fake.tunnel ? [fake.tunnel] : [], {
          result_info: { ...(fake.missingCount ? {} : { total_count: fake.count }) },
        });
      }
      if (path.endsWith('/cfd_tunnel') && init.method === 'POST') {
        const input = JSON.parse(init.body);
        fake.tunnel = { id: TUNNEL, name: input.name, config_src: 'cloudflare', deleted_at: null, account_tag: ACCOUNT };
        fake.count++;
        return json(fake.tunnel);
      }
      if (path.endsWith('/cfd_tunnel/' + TUNNEL) && init.method === 'GET') return json(fake.tunnel);
      if (path.endsWith('/configurations') && init.method === 'PUT') {
        fake.config = JSON.parse(init.body).config;
        return json({ config: fake.config });
      }
      if (path.endsWith('/dns_records') && init.method === 'GET') {
        return json(fake.record ? [fake.record] : [], { result_info: { total_count: fake.record ? 1 : 0 } });
      }
      if (path.endsWith('/dns_records') && init.method === 'POST') {
        fake.record = { id: DNS, ...JSON.parse(init.body) };
        return json(fake.record);
      }
      if (path.endsWith('/token') && init.method === 'GET') return json('connector-test-token');
      throw new Error('Unexpected request: ' + init.method + ' ' + path);
    },
  };
  return fake;
}
