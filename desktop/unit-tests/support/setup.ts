import { afterEach, vi } from "vitest";

// Transport is the substitution boundary. Production bridge queues, controllers,
// hooks, and React effects remain real modules.
vi.mock("../../src/platform", async () => {
  const { invoke, windowCall, onWindow, subscribe } = await import("./transport");
  return {
    electron: () => ({
      call: (_channel: string, method: string, args: unknown[]) => invoke({ method, args }),
      window: windowCall, onWindow, subscribe, ready: async () => {},
    }),
    nativeWindow: () => true,
    windowAction: windowCall,
  };
});

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
