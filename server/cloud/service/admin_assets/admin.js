/* Clarify admin: same-origin, cookie-authenticated, read-only analytics. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const nf = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
  const whole = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
  const money = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 });
  const shortDate = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', timeZone: 'UTC' });
  const fullDate = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeZone: 'UTC' });
  const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' });
  const names = { overview: 'Visão geral', users: 'Usuários', usage: 'Uso e custos' };
  const subtitles = { overview: 'O que está acontecendo com seu produto.', users: 'Conheça quem usa o Clarify e encontre oportunidades de ativação.', usage: 'Acompanhe volume, conclusão e orçamento com contexto.' };
  const statusNames = { active: 'Ativo', inactive: 'Sem uso confirmado', unverified: 'Não verificado' };
  const state = { page: 'overview', days: 30, userPage: 1, users: null, overview: null, chart: 'active_users', load: 0, userLoad: 0, detailLoad: 0, authEpoch: 0, signedIn: false, authBusy: false };
  let userTimer;
  let resizeTimer;
  let detailTrigger;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function svgEl(tag, attrs) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  const num = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const fmt = (value) => value === null || value === undefined ? '—' : nf.format(num(value));
  const count = (value) => value === null || value === undefined ? '—' : whole.format(num(value));
  const usd = (value) => value === null || value === undefined ? '—' : money.format(num(value));
  const validDate = (value) => value && Number.isFinite(new Date(value).getTime());
  const when = (value) => validDate(value) ? fullDate.format(new Date(value)) : '—';
  const initials = (email) => String(email || '?').slice(0, 2);

  function csrf() {
    const cookie = document.cookie.split('; ').find((item) => item.startsWith('csrftoken='));
    return cookie ? decodeURIComponent(cookie.slice(10)) : document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  }

  async function request(path, options = {}) {
    const authEpoch = state.authEpoch;
    const response = await fetch(path, {
      credentials: 'same-origin', cache: 'no-store', ...options,
      headers: { 'Accept': 'application/json', ...(options.body ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() } : {}), ...(options.headers || {}) },
    });
    let data;
    try { data = await response.json(); } catch { data = {}; }
    return { response, data, authEpoch };
  }

  async function api(path) {
    const { response, data, authEpoch } = await request(path);
    if (authEpoch !== state.authEpoch || !state.signedIn) throw new Error('stale');
    if (response.status === 401 || response.status === 403) {
      showAuth(response.status === 403 ? 'denied' : 'expired');
      throw new Error('session');
    }
    if (!response.ok) throw new Error(response.status === 429 ? 'rate' : 'load');
    return data;
  }

  function showAuth(reason) {
    state.authEpoch += 1;
    clearTimeout(userTimer);
    authBusy(false);
    state.signedIn = false;
    state.load += 1; state.userLoad += 1; state.detailLoad += 1;
    state.overview = null; state.users = null;
    $('app').hidden = true; $('boot-screen').hidden = true; $('auth-screen').hidden = false;
    if ($('user-dialog').open) $('user-dialog').close();
    $('access-denied').hidden = reason !== 'denied';
    $('email-form').hidden = reason === 'denied';
    $('code-form').hidden = true;
    $('auth-title').textContent = reason === 'denied' ? 'Acesso restrito' : 'Acesse seu painel';
    $('auth-description').hidden = reason === 'denied';
    $('auth-message').textContent = reason === 'expired' ? 'Sua sessão expirou. Entre novamente para continuar.' : '';
    $('auth-message').classList.remove('error');
    $('login-code').value = '';
    ['overview-kpis', 'usage-kpis', 'overview-users', 'users-table', 'daily-table', 'detail-content'].forEach((id) => $(id).replaceChildren());
    $('session-email').textContent = ''; $('nav-user-count').textContent = '—';
  }

  function authBusy(busy) {
    state.authBusy = busy;
    document.querySelectorAll('#email-form button, #code-form button, #auth-signout, #logout, #logout-mobile').forEach((button) => { button.disabled = busy; });
  }

  function authError(message) { $('auth-message').textContent = message; $('auth-message').classList.add('error'); }

  async function signOut() {
    if (state.authBusy) return;
    const epoch = state.authEpoch;
    authBusy(true);
    try {
      const { response } = await request('/admin/api/logout', { method: 'POST', body: '{}' });
      if (epoch !== state.authEpoch) return;
      if (!response.ok && response.status !== 401) throw new Error('logout');
      showAuth();
      $('login-email').focus();
    } catch { if (epoch === state.authEpoch) { showError('Não foi possível encerrar a sessão. Tente novamente.'); authError('Não foi possível encerrar a sessão. Tente novamente.'); } }
    finally { if (epoch === state.authEpoch) authBusy(false); }
  }

  async function boot() {
    const epoch = state.authEpoch;
    try {
      const { response, data } = await request('/admin/api/session');
      if (epoch !== state.authEpoch) return;
      if (response.status === 401 || response.status === 403) { showAuth(response.status === 403 ? 'denied' : undefined); return; }
      if (!response.ok) throw new Error('session');
      state.authEpoch += 1; state.signedIn = true; authBusy(false);
      $('boot-screen').hidden = true; $('auth-screen').hidden = true; $('app').hidden = false;
      $('session-email').textContent = data.email || '';
      navigate();
    } catch {
      if (epoch !== state.authEpoch) return;
      showAuth();
      authError('Não foi possível conectar ao painel. Atualize a página para tentar novamente.');
    }
  }

  function showError(text) { $('global-error-text').textContent = text; $('global-error').hidden = false; }
  function loadError(error) {
    if (error.message === 'session' || error.message === 'stale') return;
    document.querySelectorAll('.query-placeholder').forEach((node) => { node.textContent = 'Dados indisponíveis para este filtro.'; });
    $('updated-at').textContent = 'Dados não carregados para este filtro';
    showError(error.message === 'rate' ? 'Muitas atualizações em pouco tempo. Aguarde um minuto e tente novamente.' : 'Não foi possível atualizar os dados. Tente novamente.');
  }

  function navigate() {
    clearTimeout(userTimer);
    const page = window.location.hash.slice(1);
    state.page = Object.hasOwn(names, page) ? page : 'overview';
    document.querySelectorAll('[data-page]').forEach((link) => {
      if (link.dataset.page === state.page) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    ['overview', 'users', 'usage'].forEach((key) => { $(`${key}-page`).hidden = key !== state.page; });
    $('page-title').textContent = names[state.page]; $('breadcrumb-page').textContent = names[state.page];
    $('page-subtitle').textContent = subtitles[state.page];
    document.title = `${names[state.page]} · Clarify Admin`;
    if (state.signedIn) load();
  }

  async function load() {
    if (!state.signedIn) return;
    const version = ++state.load;
    state.userLoad += 1;
    $('global-error').hidden = true; $('loading').hidden = false; $('refresh').disabled = true;
    $('updated-at').textContent = 'Carregando dados do filtro selecionado…';
    if (state.page === 'users') clearUsers(); else clearAnalytics();
    try {
      if (state.page === 'users') {
        await loadUsers();
      } else {
        const data = await api(`/admin/api/overview?days=${state.days}`);
        if (version !== state.load || !state.signedIn) return;
        state.overview = data;
        renderOverview(data); renderUsage(data);
        if (state.page === 'overview') {
          const users = await api(`/admin/api/users?days=${state.days}&page=1&segment=active`);
          if (version !== state.load || !state.signedIn) return;
          renderUsersTable($('overview-users'), (users.results || []).slice(0, 5), true);
        }
      }
    } catch (error) { if (version === state.load) loadError(error); }
    finally { if (version === state.load) { $('loading').hidden = true; $('refresh').disabled = false; } }
  }

  function placeholder(target) {
    target.replaceChildren(el('div', 'empty-state query-placeholder', 'Carregando dados…'));
  }

  function clearUsers() {
    state.users = null;
    placeholder($('users-table'));
    $('users-count').textContent = '— usuários'; $('pagination-info').textContent = '—';
    $('previous-page').disabled = true; $('next-page').disabled = true;
  }

  function clearAnalytics() {
    state.overview = null;
    const groups = [
      ['overview-kpis', ['Usuários cadastrados', 'Usuários ativos', 'Áudio processado', 'Custo no período']],
      ['usage-kpis', ['Operações', 'Áudio processado', 'Conclusão confirmada', 'Custo no período']],
    ];
    groups.forEach(([id, labels]) => {
      const target = $(id); target.replaceChildren();
      labels.forEach((label) => {
        const card = el('article', 'metric'); card.append(el('span', 'metric-label', label));
        const amount = el('div', 'metric-value'); amount.append(el('strong', '', '—')); card.append(amount, el('span', 'metric-bottom query-placeholder', 'Carregando dados…')); target.append(card);
      });
    });
    ['activity-chart', 'funnel', 'insights', 'overview-users', 'daily-table', 'quality'].forEach((id) => placeholder($(id)));
    ['chart-total', 'budget-spent', 'budget-accounted', 'budget-reserved', 'budget-remaining', 'budget-projected'].forEach((id) => { $(id).textContent = '—'; });
    $('budget-limit').textContent = 'Orçamento ainda não carregado';
    $('budget-month').textContent = 'Mês atual · independente do filtro de período';
    $('budget-meter').value = 0; $('budget-meter').textContent = '—'; $('budget-meter').setAttribute('aria-valuetext', 'Orçamento ainda não carregado');
  }

  function icon(kind) {
    const paths = {
      users: ['M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2', 'M16 3a4 4 0 0 1 0 8', 'M22 21v-2a4 4 0 0 0-3-3.9'],
      active: ['M3 12h4l3-8 4 16 3-8h4'],
      audio: ['M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4'],
      cost: ['M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6'],
      operations: ['M5 4h14v16H5zM9 8h6M9 12h6M9 16h3'],
    };
    const node = svgEl('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' });
    (paths[kind] || paths.active).forEach((d) => node.append(svgEl('path', { d })));
    if (kind === 'users') node.append(svgEl('circle', { cx: 9, cy: 7, r: 4 }));
    return node;
  }

  function delta(current, previous) {
    if (previous === null || previous === undefined) return { text: 'Sem comparação', tone: 'neutral', note: 'histórico disponível: 31 dias' };
    if (num(previous) === 0) return { text: num(current) > 0 ? 'Novo uso' : 'Sem variação', tone: 'neutral', note: 'vs. período anterior' };
    const change = ((num(current) - num(previous)) / num(previous)) * 100;
    return { text: `${change > 0 ? '↗ +' : change < 0 ? '↘ ' : ''}${fmt(change)}%`, tone: change < 0 ? 'down' : change === 0 ? 'neutral' : '', note: 'vs. período anterior' };
  }

  function metric(target, { label, value, unit, kind, comparison, note }) {
    const card = el('article', 'metric'); const top = el('div', 'metric-top');
    top.append(el('span', 'metric-label', label)); const symbol = el('span', 'metric-icon'); symbol.append(icon(kind)); top.append(symbol);
    const amount = el('div', 'metric-value'); amount.append(el('strong', '', value)); if (unit) amount.append(el('small', '', unit));
    const bottom = el('div', 'metric-bottom');
    if (comparison) bottom.append(el('span', `metric-delta ${comparison.tone}`, comparison.text));
    bottom.append(el('span', '', note || comparison?.note || 'No período selecionado'));
    card.append(top, amount, bottom); target.append(card);
  }

  function renderOverview(data) {
    const m = data.metrics || {}; const p = m.previous || {}; const cards = $('overview-kpis'); cards.replaceChildren();
    metric(cards, { label: 'Usuários cadastrados', value: count(m.total_users), kind: 'users', note: `+${count(m.new_users)} novos neste período` });
    metric(cards, { label: 'Usuários ativos', value: count(m.active_users), kind: 'active', comparison: delta(m.active_users, p.active_users) });
    metric(cards, { label: 'Áudio processado', value: fmt(m.audio_minutes), unit: 'min', kind: 'audio', comparison: delta(m.audio_minutes, p.audio_minutes) });
    metric(cards, { label: 'Custo no período', value: usd(m.cost_usd), kind: 'cost', note: 'USD · custo contabilizado' });
    $('nav-user-count').textContent = count(m.total_users);
    renderChart(); renderFunnel(data.funnel || {}); renderInsights(data.insights || []);
    updateTimestamp(data.updated_at);
  }

  function updateTimestamp(value) {
    $('updated-at').textContent = validDate(value) ? `Atualizado em ${dateTime.format(new Date(value))} UTC` : 'Dados atualizados';
  }

  function renderChart() {
    if (!state.overview) return;
    const rows = state.overview.trend || []; const metrics = state.overview.metrics || {};
    const key = state.chart;
    const labels = { active_users: 'usuários ativos no período', audio_minutes: 'minutos de áudio no período', operations: 'operações no período' };
    $('chart-total').textContent = key === 'audio_minutes' ? fmt(metrics[key]) : count(metrics[key]);
    $('chart-total-label').textContent = labels[key];
    document.querySelectorAll('[data-chart]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.chart === key)));
    const target = $('activity-chart'); target.replaceChildren();
    if (!rows.length || !rows.some((row) => num(row[key]) > 0)) {
      target.append(el('p', 'empty-chart', 'O uso aparecerá aqui após a primeira operação no período.')); return;
    }
    const width = Math.max(300, Math.min(800, target.clientWidth)); const height = 190; const pad = { left: 36, right: 12, top: 10, bottom: 30 };
    const availableW = width - pad.left - pad.right; const availableH = height - pad.top - pad.bottom;
    const max = Math.max(...rows.map((row) => num(row[key])), 1);
    const step = 10 ** Math.floor(Math.log10(max));
    const ceiling = Math.ceil(max / step) * step;
    const chart = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': `${labels[key]}. Gráfico diário do período selecionado.` });
    const title = svgEl('title'); title.textContent = `Atividade diária: ${labels[key]}`; chart.append(title);
    for (let tick = 0; tick <= 4; tick += 1) {
      const y = pad.top + (tick / 4) * availableH;
      chart.append(svgEl('line', { x1: pad.left, x2: width - pad.right, y1: y, y2: y, class: 'chart-grid' }));
      const label = svgEl('text', { x: pad.left - 9, y: y + 3, 'text-anchor': 'end', class: 'chart-axis' });
      label.textContent = fmt(ceiling * (1 - tick / 4)); chart.append(label);
    }
    const points = rows.map((row, index) => ({ x: pad.left + (index / Math.max(rows.length - 1, 1)) * availableW, y: pad.top + availableH * (1 - num(row[key]) / ceiling), row }));
    const line = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
    chart.append(svgEl('path', { d: `${line} L ${points[points.length - 1].x} ${pad.top + availableH} L ${points[0].x} ${pad.top + availableH} Z`, class: 'chart-area' }));
    chart.append(svgEl('path', { d: line, class: 'chart-line' }));
    const labelIndexes = new Set([0, Math.floor((rows.length - 1) / 3), Math.floor((rows.length - 1) * 2 / 3), rows.length - 1]);
    points.forEach((point, index) => {
      const dot = svgEl('circle', { cx: point.x, cy: point.y, r: 3, class: 'chart-dot' });
      const tip = svgEl('title'); tip.textContent = `${when(point.row.date)}: ${fmt(point.row[key])}${key === 'audio_minutes' ? ' min' : ''}`; dot.append(tip); chart.append(dot);
      if (labelIndexes.has(index)) { const label = svgEl('text', { x: point.x, y: height - 5, 'text-anchor': index === 0 ? 'start' : index === rows.length - 1 ? 'end' : 'middle', class: 'chart-axis' }); label.textContent = validDate(point.row.date) ? shortDate.format(new Date(point.row.date)) : ''; chart.append(label); }
    });
    target.append(chart);
  }

  function bar(value, maximum, className) {
    const svg = svgEl('svg', { viewBox: '0 0 100 7', preserveAspectRatio: 'none', class: className, 'aria-hidden': 'true' });
    svg.append(svgEl('rect', { x: 0, y: 0, width: Math.max(0, Math.min(100, maximum > 0 ? num(value) / maximum * 100 : 0)), height: 7, rx: 2 }));
    return svg;
  }

  function renderFunnel(data) {
    const target = $('funnel'); target.replaceChildren();
    const steps = [['registered', 'Cadastro'], ['verified', 'E-mail verificado'], ['activated', 'Primeira conclusão'], ['returning', 'Retorno em outro dia']];
    steps.forEach(([key, label]) => {
      const item = el('div', 'funnel-step'); const heading = el('div', 'funnel-step-label');
      heading.append(el('span', '', label), el('strong', '', count(data[key])), el('small', '', num(data.registered) > 0 ? `${fmt(num(data[key]) / num(data.registered) * 100)}%` : '—'));
      item.append(heading, bar(data[key], num(data.registered), 'funnel-bar')); target.append(item);
    });
  }

  function renderInsights(insights) {
    const target = $('insights'); target.replaceChildren();
    if (!insights.length) {
      const item = el('article', 'insight'); const symbol = el('span', 'insight-symbol', '↗');
      const text = el('div'); text.append(el('h3', '', 'Acompanhe os primeiros sinais'), el('p', '', 'As oportunidades aparecem à medida que os usuários começam a usar o Clarify.'));
      item.append(symbol, text); target.append(item); return;
    }
    insights.slice(0, 3).forEach((insight) => {
      const tone = ['warning', 'success'].includes(insight.tone) ? insight.tone : 'info';
      const item = el('article', `insight ${tone}`); const text = el('div');
      text.append(el('h3', '', insight.title), el('p', '', insight.body)); item.append(el('span', 'insight-symbol', tone === 'warning' ? '!' : tone === 'success' ? '↗' : '↗'), text); target.append(item);
    });
  }

  function status(user) {
    const key = Object.hasOwn(statusNames, user.status) ? user.status : 'inactive';
    return el('span', `status ${key}`, statusNames[key]);
  }

  function userIdentity(user) {
    const wrapper = el('div', 'user-cell'); const avatar = el('span', 'user-avatar', initials(user.email)); avatar.setAttribute('aria-hidden', 'true');
    const text = el('div'); const button = el('button', 'user-button', user.email || 'Conta removida'); button.type = 'button';
    button.addEventListener('click', () => openDetail(user.id, button));
    text.append(button, el('span', 'user-date', `Cadastro em ${when(user.date_joined)}`)); wrapper.append(avatar, text); return wrapper;
  }

  function renderUsersTable(target, users, compact = false) {
    target.replaceChildren();
    if (!users.length) { const empty = el('div', 'empty-state'); empty.append(el('strong', '', 'Nenhum usuário encontrado'), el('p', '', compact ? 'A atividade dos usuários aparecerá aqui após o primeiro uso no período.' : 'Ajuste a busca ou o filtro para ver outras contas.')); target.append(empty); return; }
    const table = el('table', 'data-table'); const caption = el('caption', 'sr-only', compact ? 'Usuários com atividade no período' : 'Usuários e consumo'); table.append(caption);
    const head = el('thead'); const heading = el('tr');
    ['Usuário', 'Status', 'Operações', 'Áudio', compact ? 'Custo (USD)' : 'Cota do mês', 'Última atividade'].forEach((label, index) => { const th = el('th', index > 1 && index < 5 ? 'num' : '', label); th.scope = 'col'; heading.append(th); }); head.append(heading); table.append(head);
    const body = el('tbody'); users.forEach((user) => {
      const row = el('tr'); const identity = el('td'); identity.append(userIdentity(user)); const badge = el('td'); badge.append(status(user));
      const quota = el('td', 'num');
      if (compact) quota.textContent = usd(user.cost_usd);
      else {
        const q = user.quota || {}; const used = num(q.used_ms) + num(q.reserved_ms); const limit = num(q.limit_ms); const value = limit > 0 ? Math.round(used / limit * 100) : 0;
        const inner = el('div', 'quota-cell'); inner.append(bar(used, limit, 'quota-track'), el('span', '', limit > 0 ? `${value}%` : 'Sem cota')); quota.append(inner);
      }
      row.append(identity, badge, el('td', 'num', count(user.operations)), el('td', 'num', `${fmt(user.audio_minutes)} min`), quota, el('td', '', when(user.last_active_at))); body.append(row);
    }); table.append(body); target.append(table);
  }

  async function loadUsers() {
    const version = ++state.userLoad;
    const params = new URLSearchParams({ days: state.days, search: $('user-search').value.trim(), segment: $('user-segment').value, page: state.userPage });
    const data = await api(`/admin/api/users?${params}`);
    if (version !== state.userLoad || !state.signedIn) return;
    state.users = data; renderUsersTable($('users-table'), data.results || []);
    $('users-count').textContent = `${count(data.count)} ${num(data.count) === 1 ? 'usuário' : 'usuários'}`;
    $('pagination-info').textContent = `Página ${count(data.page)} de ${count(Math.max(1, num(data.pages)))}`;
    $('previous-page').disabled = num(data.page) <= 1; $('next-page').disabled = num(data.page) >= num(data.pages);
    updateTimestamp(new Date().toISOString());
  }

  function renderUsage(data) {
    const m = data.metrics || {}; const p = m.previous || {}; const cards = $('usage-kpis'); cards.replaceChildren();
    metric(cards, { label: 'Operações', value: count(m.operations), kind: 'operations', comparison: delta(m.operations, p.operations) });
    metric(cards, { label: 'Áudio processado', value: fmt(m.audio_minutes), unit: 'min', kind: 'audio', comparison: delta(m.audio_minutes, p.audio_minutes) });
    metric(cards, { label: 'Conclusão confirmada', value: m.success_rate === null || m.success_rate === undefined ? '—' : `${fmt(m.success_rate)}%`, kind: 'active', note: 'Das operações finalizadas' });
    metric(cards, { label: 'Custo no período', value: usd(m.cost_usd), kind: 'cost', note: 'USD · custo contabilizado' });
    const b = data.budget || {};
    $('budget-spent').textContent = usd(b.spent_usd); $('budget-limit').textContent = `de ${usd(b.limit_usd)} de orçamento`;
    $('budget-accounted').textContent = usd(b.spent_usd); $('budget-reserved').textContent = usd(b.reserved_usd);
    $('budget-remaining').textContent = usd(b.remaining_usd); $('budget-projected').textContent = usd(b.projected_usd);
    const ratio = num(b.limit_usd) > 0 ? (num(b.spent_usd) + num(b.reserved_usd)) / num(b.limit_usd) * 100 : 0;
    $('budget-meter').value = Math.max(0, Math.min(100, ratio)); $('budget-meter').textContent = `${fmt(ratio)}%`;
    $('budget-meter').setAttribute('aria-valuetext', `${usd(num(b.spent_usd) + num(b.reserved_usd))} comprometidos de ${usd(b.limit_usd)}`);
    if (validDate(b.month)) $('budget-month').textContent = `${new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(b.month))} · independente do filtro de período`;
    renderQuality($('quality'), data.health || {});
    const target = $('daily-table'); target.replaceChildren(); const rows = data.trend || [];
    if (!rows.length) { target.append(el('div', 'empty-state', 'Nenhuma operação no período.')); return; }
    const table = el('table', 'data-table'); const caption = el('caption', 'sr-only', 'Uso diário'); table.append(caption); const head = el('thead'); const heading = el('tr');
    ['Data (UTC)', 'Usuários ativos', 'Operações', 'Áudio', 'Custo (USD)'].forEach((label, index) => { const th = el('th', index ? 'num' : '', label); th.scope = 'col'; heading.append(th); }); head.append(heading); table.append(head);
    const body = el('tbody'); [...rows].reverse().forEach((row) => { const tr = el('tr'); tr.append(el('td', '', when(row.date)), el('td', 'num', count(row.active_users)), el('td', 'num', count(row.operations)), el('td', 'num', `${fmt(row.audio_minutes)} min`), el('td', 'num', usd(row.cost_usd))); body.append(tr); }); table.append(body); target.append(table);
  }

  function renderQuality(target, health) {
    target.replaceChildren();
    [['complete', 'Concluídas'], ['uncertain', 'Sem confirmação'], ['running', 'Em andamento']].forEach(([key, label]) => {
      const row = el('div', `quality-row ${key}`); const name = el('span'); name.append(el('i', 'status-dot'), el('span', '', label)); row.append(name, el('strong', '', count(health[key]))); target.append(row);
    });
  }

  async function openDetail(id, trigger) {
    const version = ++state.detailLoad; const dialog = $('user-dialog'); detailTrigger = trigger;
    $('detail-content').replaceChildren(el('p', 'muted', 'Carregando usuário…'));
    if (!dialog.open) dialog.showModal();
    $('close-detail').focus();
    try {
      const data = await api(`/admin/api/users/${encodeURIComponent(id)}?days=${state.days}`);
      if (version !== state.detailLoad || !dialog.open || !state.signedIn) return;
      renderDetail(data);
    } catch (error) {
      if (version !== state.detailLoad || error.message === 'session') return;
      const content = $('detail-content'); content.replaceChildren(el('p', 'muted', 'Não foi possível carregar esta conta.'));
      const retry = el('button', 'button secondary', 'Tentar novamente'); retry.type = 'button'; retry.addEventListener('click', () => openDetail(id, trigger)); content.append(retry);
    }
  }

  function renderDetail(data) {
    const user = data.user || {}; const target = $('detail-content'); target.replaceChildren();
    const identity = el('div', 'detail-identity'); identity.append(el('span', 'user-avatar', initials(user.email))); const title = el('h2', '', user.email); title.id = 'detail-title'; identity.append(title, el('p', '', `Cadastro em ${when(user.date_joined)}`), status(user)); target.append(identity);
    const metrics = el('div', 'detail-metrics');
    [['Operações no período', count(user.operations)], ['Áudio no período', `${fmt(user.audio_minutes)} min`], ['Custo no período', usd(user.cost_usd)], ['Última atividade', when(user.last_active_at)]].forEach(([label, value]) => { const card = el('div', 'detail-metric'); card.append(el('span', '', label), el('strong', '', value)); metrics.append(card); }); target.append(metrics);
    const details = el('section', 'detail-section'); details.append(el('h3', '', 'Conta e cota do mês')); const facts = el('dl', 'detail-facts'); const quota = user.quota || {};
    [['E-mail', user.verified ? 'Verificado' : 'Não verificado'], ['Conta', user.is_active ? 'Habilitada' : 'Desabilitada'], ['Processamento', user.funded_access ? 'Permitido pela conta' : 'Não permitido pela conta'], ['Cota de áudio', `${fmt(num(quota.limit_ms) / 60000)} min`], ['Consumido no mês', `${fmt(num(quota.used_ms) / 60000)} min`], ['Reservado no mês', `${fmt(num(quota.reserved_ms) / 60000)} min`]].forEach(([label, value]) => { const row = el('div'); row.append(el('dt', '', label), el('dd', '', value)); facts.append(row); }); details.append(facts); target.append(details);
    const quality = el('section', 'detail-section'); quality.append(el('h3', '', `Conclusão nos últimos ${state.days} dias`)); const health = el('div'); renderQuality(health, data.health || {}); quality.append(health); target.append(quality);
    target.append(el('p', 'detail-note', 'Esta visão mostra metadados de uso. Textos, gravações e chaves do usuário não são exibidos. A atividade detalhada fica disponível por 31 dias.'));
  }

  function closeDetail() { state.detailLoad += 1; $('user-dialog').close(); if (detailTrigger?.isConnected) detailTrigger.focus(); }

  $('email-form').addEventListener('submit', async (event) => {
    event.preventDefault(); if (state.authBusy) return; const epoch = state.authEpoch; authBusy(true); $('auth-message').classList.remove('error');
    try {
      const { response } = await request('/_allauth/browser/v1/auth/code/request', { method: 'POST', body: JSON.stringify({ email: $('login-email').value.trim() }) });
      if (epoch !== state.authEpoch) return;
      if (response.status !== 401 && response.status !== 200) {
        authError(response.status === 429 ? 'Limite de tentativas atingido. Aguarde antes de pedir outro código.' : 'Não foi possível enviar o código. Verifique o e-mail e tente novamente.'); return;
      }
      $('email-form').hidden = true; $('code-form').hidden = false; $('auth-title').textContent = 'Confira seu e-mail';
      $('auth-message').textContent = 'Se esta conta tiver acesso, você receberá um código válido por 10 minutos.';
      $('login-code').value = ''; $('login-code').focus();
    } catch { if (epoch === state.authEpoch) authError('Não foi possível conectar. Verifique sua conexão e tente novamente.'); }
    finally { if (epoch === state.authEpoch) authBusy(false); }
  });

  $('code-form').addEventListener('submit', async (event) => {
    event.preventDefault(); if (state.authBusy) return; const epoch = state.authEpoch; authBusy(true);
    try {
      const { response } = await request('/_allauth/browser/v1/auth/code/confirm', { method: 'POST', body: JSON.stringify({ code: $('login-code').value.trim() }) });
      if (epoch !== state.authEpoch) return;
      if (response.status !== 200) { authError(response.status === 429 ? 'Limite de tentativas atingido. Aguarde antes de tentar novamente.' : 'Código inválido ou expirado. Confira o código ou peça outro.'); return; }
      $('login-code').value = ''; await boot();
    } catch { if (epoch === state.authEpoch) authError('Não foi possível confirmar o código. Tente novamente.'); }
    finally { if (epoch === state.authEpoch) authBusy(false); }
  });

  $('change-email').addEventListener('click', () => { $('code-form').hidden = true; $('email-form').hidden = false; $('auth-title').textContent = 'Acesse seu painel'; $('auth-message').textContent = ''; $('login-email').focus(); });
  $('logout').addEventListener('click', signOut); $('logout-mobile').addEventListener('click', signOut); $('auth-signout').addEventListener('click', signOut);
  $('refresh').addEventListener('click', load); $('retry').addEventListener('click', load);
  $('period').addEventListener('change', () => { state.days = Number($('period').value); state.userPage = 1; if ($('user-dialog').open) closeDetail(); load(); });
  $('user-search').addEventListener('input', () => { clearTimeout(userTimer); state.load += 1; state.userLoad += 1; clearUsers(); userTimer = setTimeout(() => { state.userPage = 1; load(); }, 300); });
  $('user-segment').addEventListener('change', () => { state.userPage = 1; load(); });
  $('previous-page').addEventListener('click', () => { if (state.userPage > 1) { state.userPage -= 1; load(); } });
  $('next-page').addEventListener('click', () => { if (state.users && state.userPage < num(state.users.pages)) { state.userPage += 1; load(); } });
  document.querySelectorAll('[data-chart]').forEach((button) => button.addEventListener('click', () => { state.chart = button.dataset.chart; renderChart(); }));
  $('definitions-toggle').addEventListener('click', () => { const expanded = $('definitions').hidden; $('definitions').hidden = !expanded; $('definitions-toggle').setAttribute('aria-expanded', String(expanded)); });
  $('close-detail').addEventListener('click', closeDetail);
  $('user-dialog').addEventListener('cancel', (event) => { event.preventDefault(); closeDetail(); });
  $('user-dialog').addEventListener('click', (event) => { if (event.target === $('user-dialog') && event.clientX < $('user-dialog').getBoundingClientRect().left) closeDetail(); });
  window.addEventListener('hashchange', navigate);
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderChart, 100); });
  boot();
})();
