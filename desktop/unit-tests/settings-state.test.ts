import { test, expect, vi } from "vitest";
import { invoke } from "./support/transport";
import { call, settingsTransaction } from "../src/settings/bridge";
import { mergeSettings } from "../src/settings/state";
import type { Settings } from "../src/settings/bridge";

test("a complete settings transaction excludes snapshot reads and other mutations", async () => {
  const methods: string[] = [];
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  vi.mocked(invoke).mockImplementation(async (request) => {
    const { method } = request as { method: string };
    methods.push(method);
    if (method === "setRoutePrompt") await gate;
    return {} as never;
  });
  const transaction = settingsTransaction(async perform => {
    await perform("setRoutePrompt", "draft");
    return perform("save");
  });
  const read = call("snapshot");
  const preference = call("savePreference", "setAutostart", [true]);
  await Promise.resolve();
  expect(methods).toEqual(["setRoutePrompt"]);
  release();
  await Promise.all([transaction, read, preference]);
  expect(methods).toEqual(["setRoutePrompt", "save", "snapshot", "savePreference"]);
});

test("a failed transaction releases the settings connection for later requests", async () => {
  const methods: string[] = [];
  vi.mocked(invoke).mockImplementation(async (request) => {
    const { method } = request as { method: string };
    methods.push(method);
    if (method === "save") throw new Error("Isolated storage failure");
    return { autostart: true } as never;
  });
  const failure = await settingsTransaction(perform => perform("save"))
    .then(() => "unexpected success", error => String(error));
  expect(failure).toContain("Isolated storage failure");
  expect(await call("snapshot")).toEqual({ autostart: true });
  expect(methods).toEqual(["save", "snapshot"]);
});

test("telemetry deltas preserve unrelated settings and unchanged library references", () => {
  const dictionaryEntries = [{ term: "Kept", pronunciation: "", aliases: [], enabled: true }];
  const initial = { dictionaryEntries, microphoneTestLevel: 0, autostart: true } as unknown as Settings;
  const update = mergeSettings(initial, { microphoneTestLevel: 0.75 });
  const unchanged = mergeSettings(update, { dictionaryEntries: [{ term: "Kept", pronunciation: "", aliases: [], enabled: true }] });
  expect({ sameLibrary: update.dictionaryEntries === dictionaryEntries, unchanged: unchanged === update,
    level: update.microphoneTestLevel, autostart: update.autostart })
    .toEqual({ sameLibrary: true, unchanged: true, level: 0.75, autostart: true });
});
