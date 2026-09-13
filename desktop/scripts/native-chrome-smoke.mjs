// Isolated real-WebView test. Uses temporary settings, never the user's config.
import { chromium, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import net from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

for (const key of ["CLARIFY_TEST_PYTHON", "CLARIFY_TEST_FIXTURE", "CLARIFY_SETTINGS_EXECUTABLE"])
  if (!process.env[key]) throw new Error(`Set ${key}`);
const server = net.createServer();
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
await new Promise(resolve => server.close(resolve));
const profile = await mkdtemp(join(tmpdir(), "clarify-native-webview-"));
const fixture = spawn(process.env.CLARIFY_TEST_PYTHON, [process.env.CLARIFY_TEST_FIXTURE, "--native", "--check-chrome"], {
  windowsHide: true, env: { ...process.env, WEBVIEW2_USER_DATA_FOLDER: profile, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port} --remote-debugging-address=127.0.0.1` },
});
fixture.stderr.on("data", data => process.stderr.write(data));
let chromeVerified = false;
fixture.stdout.on("data", data => {
  if (data.toString().includes("PASS: native rounded corners")) chromeVerified = true;
  process.stdout.write(data);
});
let browser;
try {
  for (let attempt = 0; attempt < 60; attempt++) {
    try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`); break; }
    catch { if (fixture.exitCode !== null) throw new Error(`Fixture exited: ${fixture.exitCode}`); await delay(500); }
  }
  if (!browser) throw new Error("Native WebView did not start");
  const page = browser.contexts()[0].pages()[0];
  await expect.poll(() => chromeVerified, { timeout: 10000 }).toBe(true);
  await expect(page.getByRole("heading", { name: "Ditado", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dicionário", exact: true }).click();
  await page.getByRole("textbox", { name: "Novo termo", exact: true }).fill("Eva Desktop");
  await page.getByRole("button", { name: "Adicionar termo" }).click();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await page.getByRole("button", { name: "Dicionário", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Termo 1", exact: true })).toHaveValue("Eva Desktop");
  console.log("PASS: native dictionary add, save and navigation");
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  const chromeBounds = await page.locator(".titlebar").boundingBox();
  const scrollArea = page.locator(".scroll-area");
  for (const edge of [0, 100000]) {
    await scrollArea.evaluate((el, top) => { el.scrollTop = top; }, edge);
    await scrollArea.hover();
    await page.mouse.wheel(0, edge ? 1500 : -1500);
    await delay(300);
    expect(await page.locator(".titlebar").boundingBox()).toEqual(chromeBounds);
    expect(await page.evaluate(() => scrollY)).toBe(0);
  }
  await page.getByRole("button", { name: "Maximizar", exact: true }).click();
  await expect(page.getByRole("button", { name: "Restaurar janela", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Restaurar janela", exact: true }).click();
  await expect(page.getByRole("button", { name: "Maximizar", exact: true })).toBeVisible();
  // Tauri's drag-region handler also owns double-click maximize.
  await page.locator(".titlebar").dblclick({ position: { x: 180, y: 20 } });
  await expect(page.getByRole("button", { name: "Restaurar janela", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Restaurar janela", exact: true }).click();
  await page.getByRole("button", { name: "Minimizar", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__TAURI_INTERNALS__.invoke("plugin:window|is_minimized", { label: "main" }))).toBe(true);
  // A close request must traverse the existing unsaved-change guard.
  await page.evaluate(() => window.__TAURI_INTERNALS__.invoke("plugin:window|close", { label: "main" }));
  await Promise.race([new Promise(resolve => fixture.once("exit", resolve)), delay(5000)]);
  if (fixture.exitCode !== 0) throw new Error(`Native close did not finish cleanly: ${fixture.exitCode}`);
  console.log("PASS: native maximize, restore, titlebar double-click, minimize and clean close");
} finally {
  await browser?.close().catch(() => {});
  if (fixture.exitCode === null) fixture.kill();
  if (profile.startsWith(join(tmpdir(), "clarify-native-webview-")))
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }).catch(() => {});
}
