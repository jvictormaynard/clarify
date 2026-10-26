import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { resolve } from "node:path";
import { createContext, runInContext } from "node:vm";

function loadSource(path: string, context: ReturnType<typeof createContext>) {
  const source = readFileSync(resolve("src/settings", path), "utf8")
    .replace(/^import\b[\s\S]*?;\s*/gm, "").replace(/^export /gm, "");
  runInContext(stripTypeScriptTypes(source), context);
}

test("a complete settings transaction excludes polls and other mutations", async () => {
  const methods: string[] = [];
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const context = createContext({
    invoke: async (_command: string, request: { method: string }) => {
      methods.push(request.method);
      if (request.method === "setRoutePrompt") await gate;
      return {};
    },
  });
  loadSource("bridge.ts", context);
  const transaction = runInContext("settingsTransaction(async perform => { await perform('setRoutePrompt', 'draft'); return perform('save'); })", context);
  const poll = runInContext("pollSettings()", context);
  const preference = runInContext("call('savePreference', 'setAutostart', [true])", context);
  await Promise.resolve();
  expect(methods).toEqual(["setRoutePrompt"]);
  release();
  await Promise.all([transaction, poll, preference]);
  expect(methods).toEqual(["setRoutePrompt", "save", "poll", "savePreference"]);
});

test("a failed transaction releases the settings connection for later requests", async () => {
  const methods: string[] = [];
  const context = createContext({
    invoke: async (_command: string, request: { method: string }) => {
      methods.push(request.method);
      if (request.method === "save") throw new Error("Isolated storage failure");
      return { autostart: true };
    },
  });
  loadSource("bridge.ts", context);
  const failure = await Promise.resolve(runInContext("settingsTransaction(perform => perform('save'))", context))
    .then(() => "unexpected success", error => String(error));
  expect(failure).toContain("Isolated storage failure");
  expect(await runInContext("pollSettings()", context)).toEqual({ autostart: true });
  expect(methods).toEqual(["save", "poll"]);
});

test("telemetry deltas preserve unrelated settings and unchanged library references", () => {
  const context = createContext({});
  loadSource("state.ts", context);
  const result = runInContext(`(() => {
    const dictionaryEntries = [{ term: 'Kept', enabled: true }];
    const initial = { dictionaryEntries, microphoneTestLevel: 0, autostart: true };
    const update = mergeSettings(initial, { microphoneTestLevel: 0.75 });
    const unchanged = mergeSettings(update, { dictionaryEntries: [{ term: 'Kept', enabled: true }] });
    return { sameLibrary: update.dictionaryEntries === dictionaryEntries, unchanged: unchanged === update, level: update.microphoneTestLevel, autostart: update.autostart };
  })()`, context);
  expect(result).toEqual({ sameLibrary: true, unchanged: true, level: 0.75, autostart: true });
});
