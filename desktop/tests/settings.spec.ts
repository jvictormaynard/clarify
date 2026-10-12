import { test, expect } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

let child: ChildProcessWithoutNullStreams;
let id = 0;
const pending = new Map<number, (value: unknown) => void>();
let releaseUsage: () => void;
test.beforeEach(async ({ page }, testInfo) => {
  if (!process.env.CLARIFY_TEST_PYTHON || !process.env.CLARIFY_TEST_FIXTURE) throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE");
  const onboarding = testInfo.title.startsWith("onboarding:");
  const quota = testInfo.title.startsWith("quota:");
  const usageReady = new Promise<void>(resolve => { releaseUsage = resolve; });
  const locale = /locale (en|es)/.exec(testInfo.title)?.[1] || "pt";
  child = spawn(process.env.CLARIFY_TEST_PYTHON, ["-u", process.env.CLARIFY_TEST_FIXTURE, ...(onboarding ? ["--onboarding"] : []), ...(quota ? ["--signed-in"] : []), ...(testInfo.title.includes("failed quota") ? ["--usage-error"] : [])], { windowsHide: true, env: { ...process.env, CLARIFY_TEST_UI_LANGUAGE: locale } });
  child.stderr.on("data", data => process.stderr.write(data));
  createInterface({ input: child.stdout }).on("line", line => {
    const reply = JSON.parse(line); pending.get(reply.id)?.(reply); pending.delete(reply.id);
  });
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    if (quota && request.method === "accountCommand") await usageReady;
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
  await expect(onboarding ? page.getByRole("heading", { name: locale === "en" ? "Welcome to Clarify" : locale === "es" ? "Te damos la bienvenida a Clarify" : "Boas-vindas ao Clarify" }) : page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
});
test.afterEach(async () => { releaseUsage?.(); child?.stdin.end(JSON.stringify({ method: "quit" }) + "\n"); pending.clear(); });

test("quota: a signed-in startup shows loading until the quota arrives", async ({ page }) => {
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Carregando…" })).toBeVisible();
  await expect(page.getByText("0 de 0 minutos neste mês", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  releaseUsage();
  await expect(page.getByRole("progressbar", { name: "Uso neste mês" })).toHaveAttribute("aria-valuetext", "7,5 de 300 minutos neste mês");
  await expect(page.getByRole("status").filter({ hasText: "Carregando…" })).toHaveCount(0);
});

test("quota: a failed quota request shows an error and allows a retry", async ({ page }) => {
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  releaseUsage();
  await expect(page.getByRole("alert")).toContainText("Não foi possível conectar ao Clarify.");
  await expect(page.getByRole("status").filter({ hasText: "Carregando…" })).toHaveCount(0);
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  const retry = page.getByRole("button", { name: "Tentar novamente", exact: true });
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect(page.getByRole("alert")).toContainText("Não foi possível conectar ao Clarify.");
  await expect(retry).toBeEnabled();
});

test("onboarding: first run shows email and a local link before Settings", async ({ page }) => {
  await expect(page.getByRole("navigation", { name: "Configurações" })).toBeHidden();
  await expect(page.getByRole("textbox", { name: "E-mail", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
  for (const name of ["Entrar", "Criar conta", "Usar minha chave de API"])
    await expect(page.getByRole("button", { name, exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
  await page.getByRole("button", { name: "Usar minha chave de API", exact: true }).click();
  await page.getByRole("textbox", { name: "Chave de API do Groq" }).fill("invalid");
  await page.getByRole("button", { name: "Salvar chave e continuar" }).click();
  await expect(page.getByRole("alert")).toContainText("chave válida");
  await page.getByRole("textbox", { name: "Chave de API do Groq" }).fill("gsk_test_only");
  await page.getByRole("button", { name: "Salvar chave e continuar" }).click();
  await expect(page.getByRole("navigation", { name: "Configurações" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Boas-vindas ao Clarify" })).toBeHidden();
});

test("onboarding: email confirmation activates account processing immediately", async ({ page }) => {
  await page.getByRole("textbox", { name: "E-mail", exact: true }).fill("test@example.test");
  await page.getByRole("textbox", { name: "E-mail", exact: true }).press("Enter");
  await expect(page.getByText("Digite o código enviado para test@example.test.", { exact: false })).toBeVisible();
  await page.getByRole("textbox", { name: "Código recebido por e-mail" }).fill("000000");
  await page.getByRole("button", { name: "Confirmar código" }).click();
  await expect(page.getByRole("alert")).toContainText("Código inválido");
  await page.getByRole("textbox", { name: "Código recebido por e-mail" }).fill("123456");
  await page.getByRole("button", { name: "Confirmar código" }).click();
  await expect(page.getByRole("heading", { name: "Sua conta está pronta" })).toBeVisible();
  await expect(page.getByRole("navigation")).toBeHidden();
  await expect(page.getByRole("button", { name: "Ativar processamento do Clarify" })).toHaveCount(0);
  await page.getByRole("button", { name: "Começar", exact: true }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
  await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeHidden();
  await expect(page.getByRole("button", { name: "Texto", exact: true })).toBeHidden();
  await expect(page.getByRole("combobox", { name: "Serviço", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  const usage = page.getByRole("progressbar", { name: "Uso neste mês" });
  await expect(usage).toHaveAttribute("aria-valuenow", "2.5");
  await expect(usage).toHaveAttribute("aria-valuetext", "7,5 de 300 minutos neste mês");
  await expect(page.getByText("Atualizada após cada processamento.", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ativar processamento do Clarify" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sair da conta", exact: true })).toBeHidden();
  await expect(page.getByRole("button", { name: "Excluir conta", exact: true })).toBeHidden();
  await page.getByText("Zona de perigo", { exact: true }).click();
  for (const label of ["Sair da conta", "Excluir conta"]) {
    const button = page.getByRole("button", { name: label, exact: true });
    await expect(button).toBeVisible();
    expect(await button.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
  }
  await page.getByRole("button", { name: "Excluir conta", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Cancelar", exact: true })).toBeFocused();
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(usage).toBeVisible();
  await page.getByRole("button", { name: "Sair da conta", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(usage).toBeVisible();
  await page.getByRole("button", { name: "Sair da conta", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Sair da conta", exact: true }).click();
  await expect(page.getByRole("button", { name: "Texto", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toBeVisible();
});

test("modifier and side mouse shortcuts can be captured and saved", async ({ page }) => {
  await page.getByRole("button", { name: "Atalhos", exact: true }).click();
  const recording = page.locator(".shortcut").first();
  await recording.click();
  const captureAction = () => page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })).hotkeyCaptureAction);
  await expect.poll(captureAction).toBe("recording_hotkey");
  await page.getByRole("textbox", { name: "Novo atalho" }).press("Control");
  await expect(recording).toHaveText("Ctrl");
  await expect.poll(captureAction).toBe("");
  await recording.click();
  await page.getByRole("textbox", { name: "Novo atalho" }).press("Meta");
  await expect(recording).toHaveText("Win");
  await recording.click();
  const field = page.getByRole("textbox", { name: "Novo atalho" });
  await field.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await field.dispatchEvent("mousedown", { button: 3, buttons: 8 });
  await expect(page.getByRole("dialog")).toBeVisible();
  await field.dispatchEvent("mouseup", { button: 3 });
  await expect(recording).toHaveText("Mouse 4");
  await recording.click();
  await page.getByRole("textbox", { name: "Novo atalho" }).press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect.poll(captureAction).toBe("");
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Atalhos", exact: true }).click();
  await expect(page.locator(".shortcut").first()).toHaveText("Mouse 4");
});

test("onboarding: local choice leads to model setup without a login", async ({ page }) => {
  await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
  await page.getByRole("button", { name: "Continuar e configurar modelo" }).click();
  await expect(page.getByRole("heading", { name: "Modelos e serviços", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Modelo local", exact: true })).toBeVisible();
});

test("account remains optional and self-hosting configuration does not change dictation routes", async ({ page }) => {
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  await expect(page.getByText("A conta é opcional.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
  await page.getByRole("textbox", { name: "E-mail", exact: true }).fill("test@example.test");
  await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
  await page.getByText("Servidor próprio", { exact: true }).click();
  await page.getByRole("textbox", { name: "Endereço do servidor", exact: true }).fill("https://clarify.example");
  await page.getByRole("button", { name: "Salvar servidor", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
});

test("editable fields expose their guidance to assistive technology", async ({ page }) => {
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  const history = page.getByRole("switch", { name: "Salvar histórico", exact: true });
  await expect(history).toHaveAccessibleDescription("Mantenha suas transcrições neste computador.");
  if (!(await history.isChecked())) await history.click();
  await expect(history).toBeChecked();
  const retention = page.getByRole("spinbutton", { name: "Retenção do histórico", exact: true });
  await expect(retention).toHaveAccessibleDescription("Em dias. Deixe vazio para não definir um prazo.");
  await page.getByText("Retenção do histórico", { exact: true }).click();
  await expect(retention).toBeFocused();
});

test("instruction placeholders meet normal-text contrast", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  const contrast = await page.getByRole("textbox", { name: "Instruções", exact: true }).evaluate(element => {
    const luminance = (color: string) => {
      const values = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      });
      return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
    };
    const foreground = luminance(getComputedStyle(element, "::placeholder").color);
    const background = luminance(getComputedStyle(element).backgroundColor);
    return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
  });
  expect(contrast).toBeGreaterThanOrEqual(4.5);
});

test("automatic updates are optional and follow save and discard", async ({ page }) => {
  const version = await page.evaluate(async () => {
    const state = await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] });
    return state.applicationVersion;
  });
  expect(version).toMatch(/^\d+\.\d+\.\d+$/);
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  const toggle = page.getByRole("switch", { name: "Atualização automática", exact: true });
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await page.getByRole("button", { name: "Descartar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await expect(toggle).toBeChecked();
  await expect(page.getByText(`Versão ${version}`, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verificar atualizações" })).toBeDisabled();
  await page.setViewportSize({ width: 640, height: 520 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
  await page.screenshot({ path: "test-results/settings-updates.png", animations: "disabled" });
});

test("dictionary supports custom phrases, search, save and discard", async ({ page }) => {
  await page.getByRole("button", { name: "Dicionário", exact: true }).click();
  await page.getByRole("textbox", { name: "Novo termo", exact: true }).fill("Railway");
  await page.getByRole("textbox", { name: "Novo termo", exact: true }).press("Enter");
  await page.getByRole("textbox", { name: "Novo termo", exact: true }).fill("Eva Desktop");
  await page.getByRole("button", { name: "Adicionar termo" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeVisible();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.getByRole("textbox", { name: "Buscar termos" }).fill("eva");
  await expect(page.getByRole("textbox", { name: "Termo 1", exact: true })).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Termo 2", exact: true })).toHaveValue("Eva Desktop");
  await page.getByRole("textbox", { name: "Termo 2", exact: true }).focus();
  await page.getByRole("textbox", { name: "Termo 2", exact: true }).press("ControlOrMeta+A");
  await page.getByRole("textbox", { name: "Termo 2", exact: true }).pressSequentially("Lana Desktop");
  await expect(page.getByRole("textbox", { name: "Termo 2", exact: true })).toBeFocused();
  await expect(page.getByRole("textbox", { name: "Termo 2", exact: true })).toHaveValue("Lana Desktop");
  await page.getByRole("textbox", { name: "Buscar termos" }).clear();
  await page.getByRole("textbox", { name: "Termo 1", exact: true }).fill("Lana");
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await page.getByRole("button", { name: "Dicionário", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Termo 1", exact: true })).toHaveValue("Lana");
  await page.getByRole("button", { name: "Descartar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Termo 1", exact: true })).toHaveValue("Railway");
  await page.getByRole("switch", { name: "Usar termo 1", exact: true }).click();
  await page.getByRole("button", { name: "Remover termo 2", exact: true }).click();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("switch", { name: "Usar termo 1", exact: true })).not.toBeChecked();
  await expect(page.getByRole("textbox", { name: "Termo 2", exact: true })).toBeHidden();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.screenshot({ path: "test-results/settings-dictionary.png", animations: "disabled" });
  await page.setViewportSize({ width: 640, height: 520 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
  await page.screenshot({ path: "test-results/settings-dictionary-compact.png", animations: "disabled" });
});

test("integrated titlebar stays compact and close preserves unsaved changes", async ({ page }) => {
  await expect(page.getByRole("img", { name: "Clarify", exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Minimizar", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Maximizar", exact: true })).toBeVisible();
  expect(await page.locator(".titlebar").evaluate(el => getComputedStyle(el).backgroundColor)).toBe(await page.locator(".settings-window").evaluate(el => getComputedStyle(el).backgroundColor));
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await page.getByRole("switch").first().click();
  await page.getByRole("button", { name: "Fechar configurações", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Alterações não salvas" })).toBeVisible();
  await page.getByRole("button", { name: "Continuar editando" }).click();
  await page.screenshot({ path: "test-results/settings-titlebar.png" });
  await page.setViewportSize({ width: 640, height: 520 });
  await expect(page.getByRole("button", { name: "Fechar configurações", exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
  await page.screenshot({ path: "test-results/settings-titlebar-compact.png" });
});

test("page headings scroll with content on every settings tab", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.setViewportSize({ width: 640, height: 520 });
  for (const name of ["Ditado", "Texto", "Atalhos", "Modelos e serviços", "Geral"]) {
    await page.getByRole("button", { name, exact: true }).click();
    const heading = page.getByRole("heading", { name, exact: true });
    const scroll = page.locator(".scroll-area");
    await scroll.evaluate(el => { el.scrollTop = 0; });
    await expect(heading).toBeVisible();
    expect(await heading.evaluate(el => !!el.closest(".scroll-area"))).toBe(true);
    const top = (await heading.boundingBox())!.y;
    const delta = await scroll.evaluate(el => { el.scrollTop = 100; return el.scrollTop; });
    if (delta > 0) {
      await expect.poll(async () => (await heading.boundingBox())!.y).toBeCloseTo(top - delta, 0);
    }
    await expect(page.getByRole("button", { name: "Fechar configurações", exact: true })).toBeInViewport();
  }
  expect(consoleErrors).toEqual([]);
});

test("scroll boundaries cannot move the window chrome or sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 520 });
  await page.getByRole("button", { name: "Modelos e serviços", exact: true }).click();
  const area = page.locator(".scroll-area");
  const titlebar = page.locator(".titlebar");
  const nav = page.locator("aside");
  const before = { titlebar: await titlebar.boundingBox(), nav: await nav.boundingBox() };
  await expect.poll(() => area.evaluate(el => getComputedStyle(el).overscrollBehaviorY)).toBe("none");
  for (const edge of [0, 100000]) {
    await area.evaluate((el, top) => { el.scrollTop = top; }, edge);
    await area.hover();
    await page.mouse.wheel(0, edge ? 1500 : -1500);
    await page.waitForTimeout(300);
    expect(await titlebar.boundingBox()).toEqual(before.titlebar);
    expect(await nav.boundingBox()).toEqual(before.nav);
    expect(await page.evaluate(() => ({ x: scrollX, y: scrollY, root: document.querySelector(".settings-window")!.scrollTop }))).toEqual({ x: 0, y: 0, root: 0 });
    await expect(page.getByRole("button", { name: "Fechar configurações", exact: true })).toBeInViewport();
  }
  await titlebar.hover();
  await page.mouse.wheel(0, -1500);
  expect(await titlebar.boundingBox()).toEqual(before.titlebar);
});

test("save bar appears only for changes without resizing the scroll viewport", async ({ page }) => {
  const bar = page.getByRole("group", { name: "Alterações pendentes" });
  await expect(bar).toBeHidden();
  await expect(page.locator("footer")).toHaveCount(0);
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  const before = await page.locator(".scroll-area").boundingBox();
  await page.getByRole("switch").first().click();
  await expect(bar).toBeVisible();
  await expect.poll(() => page.locator(".floating-save").evaluate(el => getComputedStyle(el).opacity)).toBe("1");
  expect(await page.locator(".scroll-area").boundingBox()).toEqual(before);
  await page.screenshot({ path: "test-results/settings-floating-save.png" });
  await bar.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(bar).toBeHidden();
  await expect.poll(() => page.locator(".floating-save").evaluate(el => getComputedStyle(el).visibility)).toBe("hidden");
  expect(await page.locator(".scroll-area").boundingBox()).toEqual(before);
});

test("installed models: search inside popup, keyboard selection, save and discard", async ({ page }) => {
  await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
  await page.getByRole("option", { name: "Local Whisper" }).click();
  await page.getByRole("combobox", { name: "Modelo", exact: true }).click();
  await page.getByPlaceholder("Buscar modelo…").fill("Medium");
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.getByPlaceholder("Buscar modelo…").press("Enter");
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("Medium");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Alterações salvas" })).toHaveText("Alterações salvas");
  await page.getByRole("combobox", { name: "Modelo", exact: true }).click();
  await page.getByRole("option", { name: /Whisper Base/ }).click();
  await page.getByRole("button", { name: "Descartar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("Medium");
});

test("picker resets search when reopened before its closing animation ends", async ({ page }) => {
  await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
  await page.getByRole("option", { name: "Local Whisper" }).click();
  await expect(page.locator(".popover")).toHaveCount(0);
  // Keep the exiting popup mounted to reproduce rapid reopening deterministically.
  await page.addStyleTag({ content: '.popover[data-state="closed"] { animation-duration: 30s; }' });
  const model = page.getByRole("combobox", { name: "Modelo", exact: true });
  const search = page.getByPlaceholder("Buscar modelo…");
  await model.click();
  await search.fill("Medium");
  await expect(page.getByRole("option")).toHaveCount(1);
  await search.press("Enter");
  await expect(page.locator('.popover[data-state="closed"]')).toHaveCount(1);
  await model.click();
  await expect(search).toHaveValue("");
  await expect(page.getByRole("option", { name: /Whisper Base/ })).toBeVisible();
  await search.fill("Medium");
  await search.press("Escape");
  await expect(page.locator('.popover[data-state="closed"]')).toHaveCount(1);
  await model.click();
  await expect(search).toHaveValue("");
  await page.getByRole("option", { name: /Whisper Base/ }).click();
  await expect(model).toContainText("Base");
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
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
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
  expect(frames.filter(f => !f.same || f.opacity !== "1" || f.animation !== "none")).toEqual([]);
  expect(new Set(frames.map(f => f.width)).size).toBe(1);
});

test("recording options stay in the new window and preserve drafts until save", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Opções avançadas" })).toHaveCount(0);
  await page.getByText("Limites e parada automática", { exact: true }).click();
  await page.getByRole("spinbutton", { name: "Duração máxima", exact: true }).fill("5");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("alert")).toContainText("aviso");
  await page.getByRole("spinbutton", { name: "Duração máxima", exact: true }).fill("120");
  await page.getByRole("switch", { name: "Parar após fala e silêncio" }).click();
  await page.getByRole("spinbutton", { name: "Tempo de silêncio", exact: true }).fill("1.5");
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  await page.getByText("Limites e parada automática", { exact: true }).click();
  await expect(page.getByRole("spinbutton", { name: "Duração máxima", exact: true })).toHaveValue("120");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.getByRole("spinbutton", { name: "Duração máxima", exact: true }).fill("180");
  await page.getByRole("button", { name: "Descartar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(page.getByRole("spinbutton", { name: "Duração máxima", exact: true })).toHaveValue("120");
});

test("local cleanup and custom route settings are editable without legacy navigation", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("combobox", { name: "Contexto da revisão", exact: true }).click();
  await page.getByRole("option", { name: "Transcrição local", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Contexto da revisão", exact: true })).toContainText("Transcrição local");
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Revisão local independente.");
  await page.getByText("Modelo e endereço personalizados", { exact: true }).click();
  await page.getByRole("textbox", { name: "ID do modelo", exact: true }).fill("custom-local-cleanup");
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Revisão local independente.");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Revisão local independente.");
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("combobox", { name: "Contexto da revisão", exact: true }).click();
  await page.getByRole("option", { name: "Transcrição local", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Revisão local independente.");
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("custom-local-cleanup");
});

test("local model removal requires confirmation and cancel keeps the model", async ({ page }) => {
  await page.getByRole("button", { name: "Modelos e serviços", exact: true }).click();
  await page.getByText("Opções do modelo local", { exact: true }).click();
  await page.getByRole("button", { name: "Remover modelo", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("reinstalá-lo");
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(page.getByText("Pronto para usar", { exact: true })).toBeVisible();
});

for (const labels of [
  { locale: "pt", email: "E-mail", skip: "Continuar sem conta", next: "Continuar", code: "Código recebido por e-mail", confirm: "Confirmar código", back: "Voltar" },
  { locale: "en", email: "Email", skip: "Continue without an account", next: "Continue", code: "Code received by email", confirm: "Confirm code", back: "Back" },
  { locale: "es", email: "Correo electrónico", skip: "Continuar sin cuenta", next: "Continuar", code: "Código recibido por correo", confirm: "Confirmar código", back: "Volver" },
]) {
  test(`onboarding: locale ${labels.locale} keeps auth geometry and restores the skip action on Back`, async ({ page }) => {
    const email = page.getByRole("textbox", { name: labels.email, exact: true });
    const next = page.getByRole("button", { name: labels.next, exact: true });
    await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeVisible();
    const first = await email.boundingBox(), submit = await next.boundingBox();
    expect(first).not.toBeNull(); expect(submit).not.toBeNull();
    expect(Math.abs(first!.x - submit!.x)).toBeLessThan(1);
    expect(Math.abs(first!.width - submit!.width)).toBeLessThan(1);
    await email.fill("test@example.test"); await next.click();
    const code = page.getByRole("textbox", { name: labels.code, exact: true });
    await expect(code).toBeVisible();
    await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeHidden();
    const verify = await code.boundingBox();
    const confirm = await page.getByRole("button", { name: labels.confirm, exact: true }).boundingBox();
    expect(Math.abs(verify!.x - confirm!.x)).toBeLessThan(1);
    expect(Math.abs(verify!.width - confirm!.width)).toBeLessThan(1);
    await page.getByRole("button", { name: labels.back, exact: true }).click();
    await expect(email).toBeVisible();
    await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeVisible();
  });
}
