import { useCallback, useRef, useState, type SetStateAction } from "react";

// Update the ref at the input event, before React renders. An async completion
// can then clear its own revision without clearing a newer edit.
export function useDraft<T>(initial: T) {
  const [value, update] = useState(initial);
  const ref = useRef(value);
  const set = useCallback((next: SetStateAction<T>) => {
    ref.current = typeof next === "function" ? (next as (previous: T) => T)(ref.current) : next;
    update(ref.current);
  }, []);
  return [value, set, ref] as const;
}
