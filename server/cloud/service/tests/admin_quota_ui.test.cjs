/* Isolated rendering contract: node --test server/cloud/service/tests/admin_quota_ui.test.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; }
  set textContent(value) { this.children = []; this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map((node) => node.textContent).join(' '); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener() {}
}

function descendants(node, predicate) {
  return node.children.flatMap((child) => [
    ...(predicate(child) ? [child] : []), ...descendants(child, predicate),
  ]);
}

function renderer() {
  const elements = new Map();
  const document = {
    createElement: (tag) => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
    getElementById: (id) => {
      if (!elements.has(id)) elements.set(id, new Element('div'));
      return elements.get(id);
    },
    querySelectorAll: () => [],
  };
  const source = fs.readFileSync(path.join(__dirname, '../admin_assets/admin.js'), 'utf8');
  const context = vm.createContext({ document, window: { addEventListener() {} } });
  // Keep all production renderers in their closure; replace only network startup.
  const exposed = source.replace(/  boot\(\);\s*\}\)\(\);\s*$/, '  globalThis.render = { renderUsersTable, renderDetail };\n})();');
  assert.notEqual(exposed, source, 'The harness must replace only the final boot call.');
  vm.runInContext(exposed, context);
  return {
    list(user) {
      const target = new Element('div');
      context.render.renderUsersTable(target, [user]);
      return target;
    },
    detail(user) {
      context.render.renderDetail({ user });
      return document.getElementById('detail-content');
    },
  };
}

const baseQuota = {
  schema_version: 2,
  period_start: '2026-10-26T00:00:00Z',
  reset_at: '2026-11-02T00:00:00Z',
  allocation_status: 'available',
  used_percent: 37.5,
  reserved_percent: 12.5,
  remaining_percent: 50,
};
const user = (quota) => ({
  id: 'fake-account', email: 'fixture@example.test', date_joined: '2026-10-01T00:00:00Z',
  is_active: true, verified: true, funded_access: true, status: 'active',
  operations: 7, audio_minutes: 12, quota,
});
const quotas = (target) => descendants(target, (node) => node.className === 'quota-summary');

test('weekly percentages, reservations and UTC reset match in list and detail', () => {
  const render = renderer();
  const account = user(baseQuota);
  const list = render.list(account);
  assert.match(list.textContent, /Cota da semana/);
  const summary = quotas(list)[0];
  assert.ok(summary, 'The user row must show a weekly quota summary.');
  assert.match(summary.textContent, /Usado 37,5%/);
  assert.match(summary.textContent, /Reservado 12,5%/);
  assert.match(summary.textContent, /Saldo 50%/);
  assert.match(summary.textContent, /Renova em 02\/11\/2026, 00:00 UTC/);
  assert.equal(quotas(render.detail(account))[0].textContent, summary.textContent);
  const segments = descendants(summary, (node) => node.tag === 'rect');
  assert.equal(segments[0].attributes.width, '37.5');
  assert.equal(segments[1].attributes.x, '37.5');
  assert.equal(segments[1].attributes.width, '12.5');
});

test('each allocation state has the same label in list and detail', () => {
  const labels = {
    available: 'Cota atribuída', waiting: 'Aguardando cota', inactive: 'Sem acesso à cota',
    not_requested: 'Não solicitada', not_distributed: 'Ainda não distribuída',
  };
  for (const [allocation_status, label] of Object.entries(labels)) {
    const render = renderer();
    const account = user({ ...baseQuota, allocation_status, used_percent: 0, reserved_percent: 0, remaining_percent: 0 });
    const list = quotas(render.list(account))[0];
    assert.ok(list, allocation_status);
    assert.match(list.textContent, new RegExp(label));
    assert.equal(quotas(render.detail(account))[0].textContent, list.textContent);
    assert.doesNotMatch(list.textContent, /Sem fundos/);
  }
});

test('an exhausted grant stays assigned and an inactive account retains usage', () => {
  const render = renderer();
  const exhausted = quotas(render.list(user({ ...baseQuota, used_percent: 100, reserved_percent: 0, remaining_percent: 0 })))[0];
  assert.ok(exhausted);
  assert.match(exhausted.textContent, /Cota atribuída/);
  assert.match(exhausted.textContent, /Usado 100%/);
  assert.match(exhausted.textContent, /Saldo 0%/);
  const inactive = quotas(render.detail(user({ ...baseQuota, allocation_status: 'inactive' })))[0];
  assert.match(inactive.textContent, /Sem acesso à cota/);
  assert.match(inactive.textContent, /Usado 37,5%/);
});

test('unsupported quota data is unavailable instead of fabricated monthly consumption', () => {
  const render = renderer();
  for (const quota of [undefined, { used_ms: 60000, limit_ms: 120000 }, { ...baseQuota, schema_version: 3 }]) {
    const account = user(quota);
    for (const target of [render.list(account), render.detail(account)]) {
      const summary = quotas(target)[0];
      assert.ok(summary);
      assert.match(summary.textContent, /Cota indisponível/);
      assert.doesNotMatch(summary.textContent, /Usado|Saldo|50%/);
    }
  }
});
