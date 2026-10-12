import assert from 'node:assert/strict';
import test from 'node:test';
import { groupHistory, historyDayTitle, historyTime } from '../src/history.ts';

test('history groups local calendar days, sorts entries, and joins a paginated day without mutating input', () => {
  const prior = process.env.TZ; process.env.TZ = 'America/Sao_Paulo';
  try {
    const entry = (id: string, iso: string) => ({ id, createdAt: Date.parse(iso) / 1000 });
    const entries = [entry('old', '2026-10-11T02:59:00Z'), entry('first', '2026-10-11T03:00:00Z'), entry('latest', '2026-10-12T02:59:00Z')];
    const sections = groupHistory(entries);
    assert.deepEqual(sections.map(s => s.data.map(e => e.id)), [['latest', 'first'], ['old']]);
    assert.deepEqual(entries.map(e => e.id), ['old', 'first', 'latest']);
    assert.deepEqual(groupHistory([]), []);
  } finally { process.env.TZ = prior; }
});

test('a daylight saving day uses its calendar boundary and not a 24 hour window', () => {
  const prior = process.env.TZ; process.env.TZ = 'Europe/Berlin';
  try {
    const entries = ['2026-03-28T23:00:00Z', '2026-03-29T21:59:00Z', '2026-03-29T22:00:00Z'].map(iso => ({ createdAt: Date.parse(iso) / 1000 }));
    assert.deepEqual(groupHistory(entries).map(s => s.data.length), [1, 2]);
  } finally { process.env.TZ = prior; }
});

test('day titles and row times use Portuguese, English and Spanish', () => {
  const today = new Date(2026, 9, 12, 12), yesterday = new Date(2026, 9, 11, 12), lastYear = new Date(2025, 9, 11, 12);
  for (const [locale, label] of [['pt', 'Hoje'], ['en', 'Today'], ['es', 'Hoy']]) {
    assert.equal(historyDayTitle(today, today, locale, label), label);
    assert.equal(historyDayTitle(yesterday, today, locale, label), new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(yesterday));
    assert.match(historyDayTitle(lastYear, today, locale, label), /2025/);
    assert.equal(historyTime(today.getTime() / 1000, locale), new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(today));
  }
});
