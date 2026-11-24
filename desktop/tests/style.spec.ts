import { test, expect, settingsScenario } from "./settings-fixture";
import { navigate, openReviewSettings, openSettings, closeSettings } from "./settings-navigation";

settingsScenario({ initialPage: "style", personalCatalog: true }, () => {
test("styles: simplified choices persist, legacy tones remain readable, and forbidden routes hide tone", async ({ page }, testInfo) => {
  const rpc = (method: string, args: unknown[] = []) => page.evaluate(request =>
    (window as any).__testSettings(request), { method, args });
  await rpc("savePreference", ["setLanguage", ["en"]]);
  await rpc("savePreference", ["setDictationCleanupLevel", [""]]);
  await rpc("savePreference", ["setDictationWritingStyle", [""]]);
  await page.reload(); await navigate(page, "Estilo");
  await expect(page.getByRole("button", { name: "Adicionar aplicativo", exact: true })).toHaveCount(0);
  const editing = page.getByRole("combobox", { name: "Após o ditado", exact: true });
  const tone = page.getByRole("combobox", { name: "Tom", exact: true });
  await expect(editing).toContainText("Instruções atuais");
  expect((await rpc("snapshot")).dictationCleanupLevel).toBe("");
  for (const [value, label] of [["very_casual", "Muito casual"], ["informal", "Informal"], ["organized", "Organizado"]]) {
    await rpc("savePreference", ["setDictationWritingStyle", [value]]);
    await page.reload(); await navigate(page, "Estilo");
    await expect(tone).toContainText(label);
    await tone.click(); await expect(page.getByRole("option", { name: "Formal", exact: true })).toBeVisible(); await page.keyboard.press("Escape"); await expect(tone).toBeFocused();
  }
  await tone.click(); await page.getByRole("option", { name: "Manter meu tom", exact: true }).click();
  expect((await rpc("snapshot")).dictationWritingStyle).toBe("natural");
  await editing.click(); await page.getByRole("option", { name: "Manter minhas palavras", exact: true }).click();
  await expect(tone).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Idioma de saída", exact: true })).toBeVisible();
  const general = await openSettings(page, "Geral");
  await expect(general.getByRole("combobox", { name: /Idioma/ })).toHaveCount(0);
  await closeSettings(page);
  await expect(page.getByRole("status").filter({ hasText: "O idioma fica salvo. Sem revisão, o ditado não é traduzido." })).toBeVisible();
  expect((await rpc("snapshot")).language).toBe("en");
  await rpc("savePreference", ["setDictationCleanupLevel", ["light"]]);
  await page.reload(); await navigate(page, "Estilo");
  await expect(editing).toContainText("Ajustes mínimos"); await expect(tone).toHaveCount(0);
  await editing.click(); await page.getByRole("option", { name: "Melhorar a clareza", exact: true }).click();
  await expect(page.getByText("Conecte o serviço de revisão para melhorar a clareza.", { exact: true })).toBeVisible();
  await expect(tone).toHaveCount(0);
  await page.getByRole("button", { name: "Configurar revisão", exact: true }).click();
  const service = page.getByRole("combobox", { name: "Serviço", exact: true });
  await service.click();
  await page.getByRole("option", { name: "OpenAI", exact: true }).click();
  await expect(service).toContainText("OpenAI");
  await page.getByRole("button", { name: "Conectar serviço", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Serviço na nuvem", exact: true })).toContainText("OpenAI");
  await openReviewSettings(page);
  await service.click();
  await page.getByRole("option", { name: "OpenCode (free models)", exact: true }).click();
  await page.getByRole("combobox", { name: "Modelo", exact: true }).click();
  await page.getByRole("option", { name: "opencode/fixture-free-b", exact: true }).click();
  await closeSettings(page);
  await expect(tone).toContainText("Manter meu tom");
  await editing.click();
  await expect(page.getByPlaceholder("Buscar após o ditado…", { exact: true })).toBeFocused();
  await expect(page.getByRole("option", { name: "Ajustes mínimos", exact: true })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "Instruções atuais", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape"); await expect(editing).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath("clarity-natural.png"), fullPage: true });
  await openReviewSettings(page);
  await page.getByRole("switch", { name: "Ativar revisão por IA", exact: true }).click();
  await closeSettings(page);
  await expect(tone).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "A revisão do ditado está desativada" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("disabled-refinement.png"), fullPage: true });
});

test("styles: output preference saves and stays reachable by keyboard at compact widths", async ({ page }, testInfo) => {
  const output = page.getByRole("combobox", { name: "Idioma de saída", exact: true });
  await output.click(); await page.getByRole("option", { name: "Español", exact: true }).click();
  const state = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
  expect(state.language).toBe("es");
  await page.reload(); await navigate(page, "Estilo");
  await expect(output).toContainText("Español");
  for (const width of [640, 820, 1040]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await output.focus(); await page.keyboard.press("Enter"); await expect(page.getByRole("option", { name: "Español", exact: true })).toBeVisible(); await page.keyboard.press("Escape"); await expect(output).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath(`style-${width}.png`), fullPage: true });
  }
});



});
