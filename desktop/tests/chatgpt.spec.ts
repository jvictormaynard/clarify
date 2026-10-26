import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

let child: ChildProcessWithoutNullStreams;
let id = 0;
const pending = new Map<number, (value: unknown) => void>();

test.beforeEach(async ({ page }, info) => {
  if (!process.env.CLARIFY_TEST_PYTHON || !process.env.CLARIFY_TEST_FIXTURE)
    throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE");
  child = spawn(process.env.CLARIFY_TEST_PYTHON, ["-u", process.env.CLARIFY_TEST_FIXTURE,
    "--chatgpt", ...(info.title.includes("permission") ? ["--chatgpt-no-plan"] : []),
    ...(info.title.includes("cancellation") ? ["--chatgpt-wait"] : []),
    ...(info.title.includes("Clarify account") ? ["--signed-in"] : []),
  ], { windowsHide: true, env: { ...process.env, CLARIFY_TEST_UI_LANGUAGE: "en" } });
  child.stderr.on("data", data => process.stderr.write(data));
  createInterface({ input: child.stdout }).on("line", line => {
    const reply = JSON.parse(line);
    pending.get(reply.id)?.(reply); pending.delete(reply.id);
  });
  await page.route("**/__test_rpc", async route => {
    const key = ++id;
    const result = new Promise(resolve => pending.set(key, resolve));
    child.stdin.write(JSON.stringify({ id: key, ...route.request().postDataJSON() }) + "\n");
    await route.fulfill({ json: await result });
  });
  await page.addInitScript(() => {
    (window as any).__TAURI_INTERNALS__ = { invoke: async (_: string, request: unknown) => {
      const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
      const reply = await response.json(); if (reply.error) throw reply.error; return reply.result;
    } };
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dictation", exact: true })).toBeVisible({ timeout: 30000 });
});

test.afterEach(async () => {
  child?.stdin.end(JSON.stringify({ method: "quit" }) + "\n");
  pending.clear();
});

async function snapshot(page: Page) {
  return page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
}

async function selectChatGPT(page: Page) {
  await page.getByRole("button", { name: "Models and services", exact: true }).click();
  await page.getByRole("combobox", { name: "Cloud service", exact: true }).click();
  await page.getByRole("option", { name: "ChatGPT (subscription)", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "API key", exact: true })).toHaveCount(0);
  await expect(page.getByText("Custom endpoint", { exact: true })).toHaveCount(0);
}

test("ChatGPT connects without API keys, refreshes account catalogs and persists notice acknowledgement", async ({ page }, info) => {
  await selectChatGPT(page);
  await expect(page.getByText(/Audio transcription is excluded/)).toBeVisible();
  await page.getByRole("button", { name: "Continue with ChatGPT", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("You're using your ChatGPT plan");
  await page.getByRole("dialog").getByRole("button", { name: "Got it", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toContainText("Personal");
  expect((await snapshot(page)).dirty).toBe(false);
  await page.getByRole("button", { name: "Manage usage in ChatGPT", exact: true }).click();
  await expect(page.getByRole("button", { name: "Add ChatGPT account", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Text", exact: true }).click();
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await page.getByRole("option", { name: "ChatGPT (subscription)", exact: true }).click();
  await page.getByRole("combobox", { name: "Model", exact: true }).click();
  await expect(page.getByRole("option")).toHaveText(["First account model", "Second account model"]);
  await page.getByRole("option", { name: "Second account model", exact: true }).click();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCount(0);
  expect((await snapshot(page)).routeModelId).toBe("personal-a");
  await expect(page.getByText("Custom model and endpoint", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("chatgpt-text-synthetic.png"), fullPage: true });
  await page.getByRole("button", { name: "Models and services", exact: true }).click();
  await page.getByRole("button", { name: "Add ChatGPT account", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toContainText("Second");
  await page.getByRole("combobox", { name: "ChatGPT account", exact: true }).click();
  await page.getByRole("option", { name: "demo@example.test · Personal", exact: true }).click();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toContainText("Personal");
  expect((await snapshot(page)).chatgptState.planNoticeSeen).toBe(true);
  await page.getByRole("button", { name: "Manage usage in ChatGPT", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("chatgpt-models-synthetic.png"), fullPage: true });
  await page.getByRole("button", { name: "Text", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Model", exact: true })).toContainText("Select");
  await page.getByRole("combobox", { name: "Model", exact: true }).click();
  await page.getByRole("option", { name: "First account model", exact: true }).click();
  expect((await snapshot(page)).routeModelId).toBe("personal-z");
  await page.getByRole("button", { name: "Models and services", exact: true }).click();
  await page.getByRole("button", { name: "Sign out of ChatGPT", exact: true }).click();
  await expect(page.getByText("ChatGPT not connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Text", exact: true }).click();
  expect((await snapshot(page)).routeModelOptions).toEqual([]);
  expect((await snapshot(page)).routeModelId).toBe("");
  await page.getByRole("button", { name: "Dictation", exact: true }).click();
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await expect(page.getByRole("option", { name: "ChatGPT (subscription)", exact: true })).toHaveCount(0);
});

test("ChatGPT identity without plan permission does not enable text models", async ({ page }) => {
  await selectChatGPT(page);
  await expect(page.getByText("Account connected. ChatGPT plan use is not allowed.", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Refresh ChatGPT models", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Text", exact: true }).click();
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await page.getByRole("option", { name: "ChatGPT (subscription)", exact: true }).click();
  expect((await snapshot(page)).routeModelStatus).toBe("not_configured");
});

test("ChatGPT sign-in cancellation leaves the account disconnected", async ({ page }) => {
  await selectChatGPT(page);
  await page.getByRole("button", { name: "Continue with ChatGPT", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue with ChatGPT", exact: true })).toBeVisible();
  expect((await snapshot(page)).chatgptState.connected).toBe(false);
});

test("Clarify account keeps personal provider controls hidden", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Models and services", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Text", exact: true })).toHaveCount(0);
});
