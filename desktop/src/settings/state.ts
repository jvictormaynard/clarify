import type { Settings } from "./bridge";

// Settings values are JSON values. Compare without serializing large libraries.
export function settingsValuesEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length &&
      left.every((value, index) => settingsValuesEqual(value, right[index]));
  }
  const before = left as Record<string, unknown>;
  const after = right as Record<string, unknown>;
  const keys = Object.keys(before);
  return keys.length === Object.keys(after).length && keys.every(key =>
    Object.hasOwn(after, key) && settingsValuesEqual(before[key], after[key]),
  );
}

// Copy only changed top-level properties. Full replies use the same comparison,
// so a command cannot replace an unchanged library with freshly decoded arrays.
export function mergeSettings(previous: Settings, patch: Partial<Settings>): Settings {
  let next = previous;
  for (const key of Object.keys(patch) as (keyof Settings)[]) {
    if (settingsValuesEqual(previous[key], patch[key])) continue;
    if (next === previous) next = { ...previous };
    Object.assign(next, { [key]: patch[key] });
  }
  return next;
}
