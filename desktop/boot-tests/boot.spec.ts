import { test, expect } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import { observeBuiltBoot } from "../scripts/built-boot.mjs";
import { openSettings, closeSettings } from "../tests/settings-navigation";

let child: ChildProcessWithoutNullStreams;
let closed: Promise<void>;
let pending: Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>;
let calls: string[];
let fixtureError: Error | undefined;

test.beforeEach(async ({ page, baseURL }) => {
  const python = process.env.CLARIFY_TEST_PYTHON;
  const fixture = process.env.CLARIFY_TEST_FIXTURE;
  if (!python || !fixture) throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE.");
  pending = new Map();
  calls = [];
  fixtureError = undefined;
  child = spawn(python, ["-u", fixture], { windowsHide: true, env: { ...process.env, CLARIFY_TEST_UI_LANGUAGE: "en" } });
  const fail = (error: Error) => {
    fixtureError = error;
    for (const item of pending.values()) item.reject(error);
    pending.clear();
  };
  child.on("error", fail);
  child.stdin.on("error", fail);
  child.stderr.on("data", data => process.stderr.write(data));
  closed = new Promise(resolve => child.once("close", () => { fail(new Error("Settings fixture closed.")); resolve(); }));
  createInterface({ input: child.stdout }).on("line", line => {
    try {
      const reply = JSON.parse(line);
      const item = pending.get(reply.id);
      pending.delete(reply.id);
      if (reply.error) item?.reject(new Error(JSON.stringify(reply.error)));
      else item?.resolve(reply.result);
    } catch (error) { fail(error as Error); }
  });
  let id = 0;
  await page.exposeFunction("__bootSettingsCall", (request: { method: string }) => {
    if (fixtureError) throw fixtureError;
    calls.push(request.method);
    const key = ++id;
    return new Promise((resolve, reject) => {
      pending.set(key, { resolve, reject });
      child.stdin.write(JSON.stringify({ ...request, id: key }) + "\n");
    });
  });
  await page.addInitScript(() => {
    (window as any).__TAURI_INTERNALS__ = { invoke: (_command: string, request: unknown) => (window as any).__bootSettingsCall(request) };
  });
  await page.route("**/*", route => new URL(route.request().url()).origin === baseURL ? route.continue() : route.abort("blockedbyclient"));
});

test.afterEach(async () => {
  if (!child) return;
  if (!child.stdin.destroyed) child.stdin.end(JSON.stringify({ method: "quit" }) + "\n");
  const timeout = setTimeout(() => child.kill(), 5000);
  try { await closed; } finally { clearTimeout(timeout); }
});

test("production Settings boots, reads the controller and reloads without browser errors", async ({ page }, info) => {
  const boot = observeBuiltBoot(page);
  try {
    const response = await page.goto("/");
    expect(response?.status()).toBe(200);
    const scripts = await page.locator("script[src]").evaluateAll(nodes => nodes.map(node => node.getAttribute("src")));
    expect(scripts.length).toBeGreaterThan(0);
    expect(scripts.every(source => source?.startsWith("/assets/") && source.endsWith(".js"))).toBe(true);
    await expect(page.getByRole("combobox", { name: "Microphone", exact: true })).toBeVisible({ timeout: 30000 });
    expect(calls).toContain("snapshot");
    await openSettings(page, "Privacy");
    await expect(page.getByText("Save history", { exact: true })).toBeVisible();
    await closeSettings(page);
    await page.reload();
    await expect(page.getByRole("combobox", { name: "Microphone", exact: true })).toBeVisible({ timeout: 30000 });
    await page.waitForLoadState("networkidle");
    boot.assertHealthy();
  } finally {
    await info.attach("built-boot-errors", { body: JSON.stringify(boot.errors, null, 2), contentType: "application/json" });
  }
});

test("boot validator rejects a missing production entry script", async ({ page }) => {
  const boot = observeBuiltBoot(page);
  await page.route("**/assets/*.js", route => route.fulfill({ status: 404, body: "Missing script" }));
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  expect(() => boot.assertHealthy()).toThrow(/HTTP 404:.*\/assets\//);
});

test("boot validator rejects a missing dynamically imported chunk", async ({ page }) => {
  const boot = observeBuiltBoot(page);
  await page.goto("/");
  await page.evaluate(async () => { await import("/assets/missing-boot-chunk.js").catch(() => {}); });
  expect(() => boot.assertHealthy()).toThrow(/HTTP 404:.*missing-boot-chunk/);
});

test("boot validator rejects initialization exceptions", async ({ page }) => {
  const boot = observeBuiltBoot(page);
  await page.addInitScript(() => { throw new Error("boot initialization regression"); });
  await page.goto("/");
  expect(() => boot.assertHealthy()).toThrow(/pageerror: boot initialization regression/);
});

test("boot validator rejects console errors even when the application mounts", async ({ page }) => {
  const boot = observeBuiltBoot(page);
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Microphone", exact: true })).toBeVisible({ timeout: 30000 });
  await page.evaluate(() => console.error("boot console regression"));
  expect(() => boot.assertHealthy()).toThrow(/console: boot console regression/);
});
