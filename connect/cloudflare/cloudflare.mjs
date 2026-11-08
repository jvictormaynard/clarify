import { CF_ID, UUID, deadline, fail, object, readJSON } from './protocol.mjs';
import { checkpoint, finish, stop } from './storage.mjs';

function validTunnel(value, row, config) {
  return object(value) && UUID.test(value.id ?? '') && value.name === row.hostname.split('.')[0] &&
    value.config_src === 'cloudflare' && value.deleted_at === null && value.account_tag === config.account;
}
function validDNS(value, row, tunnel) {
  return object(value) && CF_ID.test(value.id ?? '') && value.type === 'CNAME' &&
    value.name === row.hostname && value.content === tunnel + '.cfargotunnel.com' && value.proxied === true;
}

function confirmedIngress(value, row) {
  if (!Array.isArray(value) || value.length !== 2) return false;
  const [route, fallback] = value;
  const safeFields = item => object(item) && Object.keys(item).every(key =>
    ['hostname', 'service', 'path', 'originRequest'].includes(key)) &&
    (item.path === undefined || item.path === null || item.path === '') &&
    (item.originRequest === undefined || (object(item.originRequest) && Object.keys(item.originRequest).length === 0));
  return safeFields(route) && safeFields(fallback) && route.hostname === row.hostname &&
    route.service === `http://127.0.0.1:${row.origin_port}` && fallback.service === 'http_status:404' &&
    (fallback.hostname === undefined || fallback.hostname === '');
}

export async function provision(db, row, operation, config, io) {
  let mutated = false;
  const accountPath = `/accounts/${config.account}`;
  const tunnelPath = accountPath + '/cfd_tunnel';
  const dnsPath = `/zones/${config.zone}/dns_records`;
  async function call(method, path, body) {
    // No caller value can select an API origin, account, zone, or path prefix.
    if (!path.startsWith(accountPath + '/') && !path.startsWith(`/zones/${config.zone}/`)) fail(502, 'invalid_upstream');
    if (method !== 'GET') mutated = true; // Set before fetch, including synchronous throws.
    return deadline(io.timeoutMs, async signal => {
      const response = await io.fetch('https://api.cloudflare.com/client/v4' + path, {
        method, redirect: 'manual', signal,
        headers: { Authorization: 'Bearer ' + config.token, Accept: 'application/json', 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      if (response.status < 200 || response.status >= 300) {
        if (response.body) void response.body.cancel().catch(() => {});
        fail(502, 'invalid_upstream');
      }
      const value = await readJSON(response, 2 * 1024 * 1024, signal, true);
      if (!object(value) || value.success !== true || !Object.hasOwn(value, 'result')) fail(502, 'invalid_upstream');
      return value;
    });
  }
  try {
    let tunnel = row.tunnel_id;
    if (tunnel) {
      if (!UUID.test(tunnel)) fail(502, 'invalid_upstream');
      const current = (await call('GET', tunnelPath + '/' + tunnel)).result;
      if (!validTunnel(current, row, config) || current.id !== tunnel) fail(502, 'invalid_upstream');
    } else {
      // All tunnel types count. No name filter can hide other operators' tunnels.
      const inventory = await call('GET', accountPath + '/tunnels?is_deleted=false&page=1&per_page=1000');
      const count = inventory.result_info?.total_count;
      if (!Number.isInteger(count) || count < 0 || count >= config.cap || !Array.isArray(inventory.result) ||
          inventory.result.length !== count || inventory.result.some(item =>
            !object(item) || !UUID.test(item.id ?? '') || typeof item.name !== 'string' ||
            item.name === row.hostname.split('.')[0])) fail(502, 'capacity_unavailable');
    }

    // Inspect before any mutation. A foreign record is never replaced.
    const records = await call('GET', dnsPath + '?name=' + encodeURIComponent(row.hostname) + '&page=1&per_page=100');
    if (!Array.isArray(records.result) || !Number.isInteger(records.result_info?.total_count) ||
        records.result_info.total_count !== records.result.length || records.result.length > 1) fail(502, 'invalid_upstream');
    let dns = records.result[0];
    if (dns && (!tunnel || !validDNS(dns, row, tunnel) || dns.id !== row.dns_id)) fail(502, 'dns_conflict');
    if (!dns && row.dns_id) fail(502, 'dns_conflict');

    if (!tunnel) {
      const created = (await call('POST', tunnelPath, { name: row.hostname.split('.')[0], config_src: 'cloudflare' })).result;
      if (!validTunnel(created, row, config)) fail(502, 'invalid_upstream');
      tunnel = created.id;
      await checkpoint(db, row.computer_id, operation, 'tunnel_id', tunnel, io.now());
    }
    const configBody = { ingress: [
      { hostname: row.hostname, service: `http://127.0.0.1:${row.origin_port}` },
      { service: 'http_status:404' },
    ] };
    const configured = (await call('PUT', tunnelPath + '/' + tunnel + '/configurations', { config: configBody })).result;
    // Require provider confirmation of the exact ingress before issuing a token.
    if (!object(configured) || !confirmedIngress(configured.config?.ingress, row)) fail(502, 'invalid_upstream');
    if (!dns) {
      dns = (await call('POST', dnsPath, {
        type: 'CNAME', name: row.hostname, content: tunnel + '.cfargotunnel.com', proxied: true, ttl: 1,
      })).result;
      if (!validDNS(dns, row, tunnel)) fail(502, 'invalid_upstream');
      await checkpoint(db, row.computer_id, operation, 'dns_id', dns.id, io.now());
    }
    const token = (await call('GET', tunnelPath + '/' + tunnel + '/token')).result;
    if (typeof token !== 'string' || !/^[A-Za-z0-9_+\/=.-]{16,8192}$/.test(token) || token === config.token) fail(502, 'invalid_upstream');
    await finish(db, row.computer_id, operation, io.now());
    return { schema_version: 1, hostname: row.hostname, token, origin_port: row.origin_port };
  } catch {
    // If this write also fails, the earlier claiming row and lock remain durable.
    try { await stop(db, row.computer_id, operation, io.now(), mutated); } catch { /* Keep the original barrier. */ }
    fail(502, mutated ? 'allocation_uncertain' : 'allocation_blocked');
  }
}
