import { test } from "@playwright/test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { createContext, runInContext } from "node:vm";

function jobs(method = "saveTextAction", key = "textActionMutation") {
  let next = { generation: 7, busy: true, status: "pending", error: "" };
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let entered!: () => void;
  const polled = new Promise<void>(resolve => { entered = resolve; });
  const calls: string[] = [];
  const context = createContext({ t: (value: string) => value,
    setTimeout: (callback: () => void) => { queueMicrotask(callback); return 0; },
    invoke: async (_command: string, request: { method: string }) => {
      calls.push(request.method);
      if (request.method === method) return { [key]: { ...next }, textActions: [] };
      if (request.method === "poll") { entered(); await held; return { [key]: { ...next }, textActions: [{ id: "saved" }] }; }
      return { selectedScope: "transcription" };
    },
  });
  const source = readFileSync("src/settings/bridge.ts", "utf8").replace(/^import\b[\s\S]*?;\s*/gm, "").replace(/^export /gm, "");
  runInContext(stripTypeScriptTypes(source), context);
  return { calls, release, polled,
    finish: (patch: Partial<typeof next> = {}) => { next = { ...next, busy: false, status: "succeeded", ...patch }; release(); },
    execute: (transaction: boolean) => runInContext(transaction
      ? `settingsTransaction(call => call(${JSON.stringify(method)}, {}, "context", "revision"))`
      : `call(${JSON.stringify(method)}, {}, "context", "revision")`, context) as Promise<any>,
    queued: () => runInContext('call("snapshot")', context) as Promise<any>,
  };
}

for (const transaction of [false, true]) test(`action jobs: ${transaction ? "transaction" : "call"} keeps the pipe until its own job finishes`, async () => {
  const h = jobs(); const saving = h.execute(transaction);
  assert.equal(await Promise.race([h.polled.then(() => "polled"), saving.then(() => "returned")]), "polled");
  const queued = h.queued();
  assert.equal(h.calls.includes("snapshot"), false);
  h.finish();
  const result = await saving;
  assert.equal(result.textActions[0].id, "saved");
  await queued; assert.equal(h.calls.at(-1), "snapshot");
});

test("action jobs: final failure rejects with the latest snapshot for draft recovery", async () => {
  const h = jobs(); const saving = h.execute(true);
  assert.equal(await Promise.race([h.polled.then(() => "polled"), saving.then(() => "returned")]), "polled");
  h.finish({ status: "failed", error: "Account changed" });
  await assert.rejects(saving, error => {
    assert.equal((error as any).message, "Account changed");
    assert.equal((error as any).snapshot.textActions[0].id, "saved");
    return true;
  });
});

test("action jobs: another generation cannot confirm the pending save", async () => {
  const h = jobs(); const saving = h.execute(false);
  assert.equal(await Promise.race([h.polled.then(() => "polled"), saving.then(() => "returned")]), "polled");
  h.finish({ generation: 8 });
  await assert.rejects(saving, /operação de ações mudou/);
});

test("action jobs: refresh waits for its catalog generation before returning recovered state", async () => {
  const h = jobs("refreshTextActions", "textActionRefresh"); const refreshing = h.execute(false);
  assert.equal(await Promise.race([h.polled.then(() => "polled"), refreshing.then(() => "returned")]), "polled");
  h.finish();
  const result = await refreshing;
  assert.equal(result.textActionRefresh.status, "succeeded");
  assert.equal(result.textActions[0].id, "saved");
});
