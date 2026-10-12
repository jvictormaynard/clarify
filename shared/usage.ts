// Reservations are pending operations, not minutes already consumed.
export function usageProgress(usedMs = 0, limitMs = 0) {
  const used = Number.isFinite(usedMs) ? Math.max(0, usedMs) : 0;
  const limit = Number.isFinite(limitMs) ? Math.max(0, limitMs) : 0;
  return {
    usedMinutes: used / 60000,
    limitMinutes: limit / 60000,
    percent: limit > 0 ? Math.min(100, used / limit * 100) : 0,
  };
}
