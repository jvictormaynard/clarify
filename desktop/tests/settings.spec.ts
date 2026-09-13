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
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
});
test.afterEach(async () => { child?.stdin.end(JSON.stringify({ method: "quit" }) + "\n"); pending.clear(); });

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
