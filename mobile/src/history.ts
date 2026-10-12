// Group by the device's calendar day, not by a UTC date or a 24-hour interval.
export function calendarDay(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}
export function groupHistory<T extends { createdAt: number }>(entries: readonly T[]) {
  const groups = new Map<string, { key: string; date: Date; data: T[] }>();
  for (const entry of [...entries].sort((a, b) => b.createdAt - a.createdAt)) {
    const date = new Date(entry.createdAt * 1000), key = calendarDay(date);
    let group = groups.get(key);
    if (!group) { group = { key, date, data: [] }; groups.set(key, group); }
    group.data.push(entry);
  }
  return [...groups.values()];
}
export function historyDayTitle(date: Date, today: Date, locale: string, todayLabel: string): string {
  if (calendarDay(date) === calendarDay(today)) return todayLabel;
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric',
    ...(date.getFullYear() === today.getFullYear() ? {} : { year: 'numeric' }) }).format(date);
}
export function historyTime(createdAt: number, locale: string): string {
  return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(new Date(createdAt * 1000));
}
