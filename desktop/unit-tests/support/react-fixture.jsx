import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { afterEach, test as unitTest } from "vitest";

const roots = new Set();

// Keep each concurrent-operation scenario inside React's async act scope.
// Explicit render() calls flush the selected intermediate state while a bridge
// request remains held. React owns all hook slots, memoization, and effects.
export function test(name, body) {
  unitTest(name, () => act(body));
}

export async function mountHook(useHook) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.add({ root, container });
  let value;
  function Probe() { value = useHook(); return null; }
  const render = () => {
    flushSync(() => root.render(createElement(Probe)));
    return value;
  };
  await act(async () => { render(); });
  return { render };
}

export function mountPage(Component, controller) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.add({ root, container });
  const render = () => flushSync(() => root.render(createElement(Component, { controller })));
  render();
  return { container, render };
}

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of roots) { root.unmount(); container.remove(); }
    roots.clear();
  });
});
