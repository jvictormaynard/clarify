import { test as base, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import type { Settings } from "../src/settings/bridge";

type FixtureSession = { rpc: (method: string, ...args: unknown[]) => Promise<Settings> };

async function startFixture(page: Page, language: string, signedIn: boolean) {
  if (!process.env.CLARIFY_TEST_PYTHON || !process.env.CLARIFY_TEST_FIXTURE) throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE");
  const child: ChildProcessWithoutNullStreams = spawn(process.env.CLARIFY_TEST_PYTHON,
    ["-u", process.env.CLARIFY_TEST_FIXTURE, "--text-actions", ...(signedIn ? ["--signed-in"] : [])],
    { windowsHide: true, env: { ...process.env, CLARIFY_TEST_UI_LANGUAGE: language } });
  let id = 0, closed = false;
  const pending = new Map<number, { resolve: (value: Settings) => void; reject: (error: unknown) => void }>();
  child.stderr.on("data", value => process.stderr.write(value));
  const replies = createInterface({ input: child.stdout });
  replies.on("line", line => {
    const reply = JSON.parse(line), waiting = pending.get(reply.id);
    pending.delete(reply.id);
    if (reply.error) waiting?.reject(reply.error); else waiting?.resolve(reply.result);
  });
  child.once("exit", code => {
    for (const waiting of pending.values()) waiting.reject(new Error(`Settings fixture exited: ${code}`));
    pending.clear();
  });
  const rpc = (method: string, ...args: unknown[]) => new Promise<Settings>((resolve, reject) => {
    const key = ++id;
    if (closed) { reject(new Error("Settings fixture closed")); return; }
    pending.set(key, { resolve, reject });
    child.stdin.write(JSON.stringify({ id: key, method, args }) + "\n");
  });
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    try { await route.fulfill({ json: { result: await rpc(request.method, ...(request.args ?? [])) } }); }
    catch (error) { if (!closed) await route.fulfill({ json: { error: String(error) } }); else await route.abort().catch(() => {}); }
  });
  await page.addInitScript(() => {
    (window as any).__TAURI_INTERNALS__ = { invoke: async (_command: string, request: unknown) => {
      const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
      const reply = await response.json(); if (reply.error) throw reply.error; return reply.result;
    } };
  });
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: language === "en" ? "Microphone" : language === "es" ? "Micrófono" : "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
  return {
    rpc,
    close: async () => {
      closed = true;
      await page.unroute("**/__test_rpc");
      const exited = new Promise<void>(resolve => { if (child.exitCode !== null) resolve(); else child.once("exit", () => resolve()); });
      child.stdin.end(JSON.stringify({ method: "quit" }) + "\n");
      const timer = setTimeout(() => child.kill(), 3000);
      try { await exited; } finally { clearTimeout(timer); replies.close(); }
    },
  };
}

export const test = base.extend<{ uiLanguage: string; signedIn: boolean; settingsFixture: FixtureSession }>({
  uiLanguage: ["pt", { option: true }], signedIn: [false, { option: true }],
  settingsFixture: [async ({ page, uiLanguage, signedIn }, use) => {
    const fixture = await startFixture(page, uiLanguage, signedIn);
    try { await use(fixture); } finally { await fixture.close(); }
  }, { auto: true, timeout: 45_000 }],
});
export { expect };

export { openSettings } from "./settings-navigation";
