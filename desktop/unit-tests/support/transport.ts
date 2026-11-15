import { vi } from 'vitest';

export const invoke = vi.fn<(request: { method: string; args: unknown[] }) => Promise<unknown>>(
  () => { throw new Error('No Settings transport fixture installed'); },
);
export const windowCall = vi.fn<(...args: unknown[]) => Promise<void>>(async () => {});
export const onWindow = vi.fn<(listener: (event: string) => void) => () => void>(() => () => {});
