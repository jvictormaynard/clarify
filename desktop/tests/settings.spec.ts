import { test, expect } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

let child: ChildProcessWithoutNullStreams;
let id = 0;
const pending = new Map<number, (value: unknown) => void>();
test.beforeEach(async ({ page }) => {
  if (!process.env.CLARIFY_TEST_PYTHON || !process.env.CLARIFY_TEST_FIXTURE) throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE");
  child = spawn(process.env.CLARIFY_TEST_PYTHON, ["-u", process.env.CLARIFY_TEST_FIXTURE], { windowsHide: true });
  child.stderr.on("data", data => process.stderr.write(data));
  createInterface({ input: child.stdout }).on("line", line => {
    const reply = JSON.parse(line); pending.get(reply.id)?.(reply); pending.delete(reply.id);
  });
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    const key = ++id;
    const result = new Promise(resolve => pending.set(key, resolve));
    child.stdin.write(JSON.stringify({ id: key, ...request }) + "\n");
    await route.fulfill({ json: await result });
  });
  await page.addInitScript(() => {
    (window as any).__TAURI_INTERNALS__ = { invoke: async (_command: string, request: unknown) => {
      const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
      const result = await response.json(); if (result.error) throw result.error; return result.result;
    } };
  });
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeDisabled();
});
test.afterEach(async () => { child?.stdin.end(JSON.stringify({ method: "quit" }) + "\n"); pending.clear(); });

test("installed models: search inside popup, keyboard selection, save and discard", async ({ page }) => {
  await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
  await page.getByRole("option", { name: "Local Whisper" }).click();
  await page.getByRole("combobox", { name: "Modelo", exact: true }).click();
  await page.getByPlaceholder("Buscar modelo…").fill("Medium");
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.getByPlaceholder("Buscar modelo…").press("Enter");
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("Medium");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Alterações salvas" })).toBeVisible();
  await page.getByRole("combobox", { name: "Modelo", exact: true }).click();
  await page.getByRole("option", { name: /Whisper Base/ }).click();
  await page.getByRole("button", { name: "Descartar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("Medium");
});

test("draft prompt survives navigation; invalid retention cannot save", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções" }).fill("Preserve every detail.");
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await page.getByRole("switch", { name: "Salvar histórico" }).click();
  await page.getByRole("spinbutton", { name: "Retenção do histórico" }).fill("-1");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("alert")).toContainText("3650");
  await page.getByRole("spinbutton", { name: "Retenção do histórico" }).fill("30");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeDisabled();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções" })).toHaveValue("Preserve every detail.");
});

test("microphone preview stops on navigation and all pages fit", async ({ page }, testInfo) => {
  await page.getByRole("button", { name: "Testar microfone" }).click();
  await expect(page.getByRole("button", { name: "Parar teste" })).toBeVisible();
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  await expect(page.getByRole("button", { name: "Testar microfone" })).toBeVisible();
  for (const width of [640, 820, 1040]) {
    await page.setViewportSize({ width, height: 760 });
    for (const name of ["Ditado", "Geral", "Texto", "Atalhos", "Modelos e serviços"]) {
      await page.getByRole("button", { name, exact: true }).click();
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await expect(page.locator("fieldset")).toBeEnabled();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`${width}-${name}.png`), animations: "disabled" });
    }
  }
});

test("navigation preserves the page container, brightness and horizontal geometry", async ({ page }) => {
  await expect(page.locator("fieldset")).toBeEnabled();
  await page.evaluate(() => {
    (window as any).__originalPage = document.querySelector(".page");
    (window as any).__navFrames = [];
    (window as any).__sampling = true;
    const sample = () => {
      if (!(window as any).__sampling) return;
      const button = document.querySelector("nav button")!;
      const area = document.querySelector(".page")!;
      (window as any).__navFrames.push({
        opacity: getComputedStyle(button).opacity,
        same: area === (window as any).__originalPage,
        width: area.getBoundingClientRect().width,
        animation: getComputedStyle(area).animationName,
      });
      requestAnimationFrame(sample);
    };
    sample();
  });
  for (const name of ["Texto", "Geral", "Modelos e serviços", "Ditado", "Texto"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expect(page.locator("fieldset")).toBeEnabled();
  }
  for (const name of ["Reescrita", "Tradução", "Revisão"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("fieldset")).toBeEnabled();
  }
  const frames = await page.evaluate(() => {
    (window as any).__sampling = false;
    return (window as any).__navFrames as { opacity: string; same: boolean; width: number; animation: string }[];
  });
  expect(frames.length).toBeGreaterThan(5);
  expect(frames.every(f => f.same && f.opacity === "1" && f.animation === "none")).toBe(true);
  expect(new Set(frames.map(f => f.width)).size).toBe(1);
});
