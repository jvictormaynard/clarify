import { chromium, expect } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { performance } from "node:perf_hooks";

for (const key of ["CLARIFY_TEST_PYTHON", "CLARIFY_TEST_FIXTURE", "CLARIFY_SETTINGS_EXECUTABLE", "CLARIFY_TEST_OUTPUT"]) {
  if (!process.env[key]) throw new Error(`Missing ${key}`);
}
await mkdir(process.env.CLARIFY_TEST_OUTPUT, { recursive: true });
const started = performance.now();
const child = spawn(process.env.CLARIFY_TEST_PYTHON, ["-u", process.env.CLARIFY_TEST_FIXTURE, "--native"], {
  windowsHide: true,
  env: { ...process.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: "--remote-debugging-port=9223 --remote-debugging-address=127.0.0.1" },
});
child.stderr.on("data", data => process.stderr.write(data));
const exited = new Promise(resolve => child.once("exit", code => resolve(code)));
let browser;
try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch("http://127.0.0.1:9223/json/version")).ok) { ready = true; break; } } catch {}
    if (child.exitCode !== null) throw new Error(`Native host exited: ${child.exitCode}`);
    await delay(200);
  }
  if (!ready) throw new Error("Native webview did not start");
  browser = await chromium.connectOverCDP("http://127.0.0.1:9223");
  const page = browser.contexts()[0].pages()[0];
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeDisabled();
  console.log(`Native ready after ${Math.round(performance.now() - started)} ms (includes isolated Python fixture startup)`);
  await page.screenshot({ path: `${process.env.CLARIFY_TEST_OUTPUT}/native-dictation.png` });
  const measured = spawnSync("powershell.exe", ["-NoProfile", "-Command", `$taskProcesses=Get-CimInstance Win32_Process; $taskFamily=@(${child.pid}); do { $taskPrevious=$taskFamily.Count; $taskFamily+=@($taskProcesses | Where-Object { $_.ParentProcessId -in $taskFamily -and $_.ProcessId -notin $taskFamily } | Select-Object -ExpandProperty ProcessId) } while ($taskFamily.Count -gt $taskPrevious); $taskNative=@($taskFamily | Where-Object { $_ -ne ${child.pid} }); $taskMemory=($taskNative | ForEach-Object { (Get-Process -Id $_ -ErrorAction SilentlyContinue).WorkingSet64 } | Measure-Object -Sum).Sum; [pscustomobject]@{Processes=$taskNative.Count; SummedWorkingSetMB=[math]::Round($taskMemory/1MB,1)} | ConvertTo-Json -Compress`], { encoding: "utf8", windowsHide: true });
  console.log(`Native process memory (shared pages may be counted twice): ${measured.stdout.trim()}`);
  await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
  await page.getByRole("option", { name: "Local Whisper" }).click();
  await page.getByRole("combobox", { name: "Modelo", exact: true }).click();
  await page.getByRole("option", { name: /Whisper Medium/ }).click();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeDisabled();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções" }).fill("Unsaved native test draft");
  await page.evaluate(() => window.__TAURI_INTERNALS__.invoke("plugin:window|close", { label: "main" }));
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Continuar editando" }).click();
  await expect(page.getByRole("textbox", { name: "Instruções" })).toHaveValue("Unsaved native test draft");
  await page.evaluate(() => window.__TAURI_INTERNALS__.invoke("plugin:window|close", { label: "main" }));
  await page.getByRole("dialog").getByRole("button", { name: "Descartar", exact: true }).click();
  const code = await Promise.race([exited, delay(10000).then(() => "timeout")]);
  if (code !== 0) throw new Error(`Close did not release the child: ${code}`);
  if (errors.length) throw new Error(`Native frontend errors: ${errors.join("; ")}`);
  console.log("PASS: real Tauri IPC, model save, dirty close/cancel/discard, process exit");
} finally {
  await browser?.close().catch(() => {});
  if (child.exitCode === null) child.kill();
}
