import { afterEach, vi } from "vitest";

// Transport is the substitution boundary. Production bridge queues, controllers,
// hooks, and React effects remain real modules.
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => true,
  invoke: vi.fn(() => { throw new Error("No Settings transport fixture installed"); }),
}));
vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: vi.fn() }));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
