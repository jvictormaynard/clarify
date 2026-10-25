export interface WeeklyUsage {
  schema_version: 2;
  period_start: string;
  reset_at: string;
  used_percent: number;
  remaining_percent: number;
  reserved_percent: number;
  allocation_status: 'available' | 'waiting' | 'unfunded' | 'inactive';
  hosted_available: boolean;
}

function utcTime(value: unknown): number {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(value)) return NaN;
  const timestamp = Date.parse(value);
  // Date.parse normalizes some invalid calendar dates, such as February 30.
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 19) === value.slice(0, 19)
    ? timestamp : NaN;
}

// The bridge can contain an empty, legacy or untrusted server snapshot. Never
// derive a weekly allowance from old durations or treat a missing limit as 100%.
export function usageProgress(snapshot: unknown = undefined, now = Date.now()): WeeklyUsage | null {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return null;
  const value = snapshot as Record<string, unknown>;
  const start = utcTime(value.period_start), reset = utcTime(value.reset_at);
  if (value.schema_version !== 2 || !Number.isFinite(start) || !Number.isFinite(reset)
    || start >= reset || reset <= now || typeof value.hosted_available !== 'boolean'
    || typeof value.allocation_status !== 'string'
    || !['available', 'waiting', 'unfunded', 'inactive'].includes(value.allocation_status)) return null;
  for (const field of ['used_percent', 'remaining_percent', 'reserved_percent']) {
    const percent = value[field];
    if (typeof percent !== 'number' || !Number.isFinite(percent) || percent < 0 || percent > 100) return null;
  }
  // Copy only the public percentage contract. Reservations remain separate.
  return {
    schema_version: 2, period_start: value.period_start as string, reset_at: value.reset_at as string,
    used_percent: value.used_percent as number, remaining_percent: value.remaining_percent as number,
    reserved_percent: value.reserved_percent as number, allocation_status: value.allocation_status as WeeklyUsage['allocation_status'],
    hosted_available: value.hosted_available,
  };
}

export function formatUsageReset(resetAt: string, locale: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
    ...(timeZone ? { timeZone } : {}),
  }).format(new Date(resetAt));
}
