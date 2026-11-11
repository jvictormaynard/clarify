import { test, expect, settingsScenario } from "./settings-fixture";
import { navigate, openStyleReview, openDisclosure } from "./settings-navigation";

settingsScenario({ initialPage: "style" }, () => {
test("styles: simplified choices persist, legacy tones remain readable, and forbidden routes hide tone", async ({ page }, testInfo) => {
  const rpc = (method: string, args: unknown[] = []) => page.evaluate(request =>
    (window as any).__TAURI_INTERNALS__.invoke("settings_call", request), { method, args });
  await rpc("savePreference", ["setLanguage", ["en"]]);
  await rpc("savePreference", ["setDictationCleanupLevel", [""]]);
  await rpc("savePreference", ["setDictationWritingStyle", [""]]);
  await page.reload(); await navigate(page, "Estilo");
  await expect(page.getByRole("button", { name: "Adicionar aplicativo", exact: true })).toHaveCount(0);
  const editing = page.getByRole("combobox", { name: "Edição do texto", exact: true });
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
  await openDisclosure(page, "Mais opções");
  await expect(page.getByRole("status").filter({ hasText: "O idioma fica salvo. Sem revisão, o ditado não é traduzido." })).toBeVisible();
  expect((await rpc("snapshot")).language).toBe("en");
  await rpc("savePreference", ["setDictationCleanupLevel", ["light"]]);
  await page.reload(); await navigate(page, "Estilo");
  await expect(editing).toContainText("Ajustes mínimos"); await expect(tone).toHaveCount(0);
  await editing.click(); await page.getByRole("option", { name: "Melhorar a clareza", exact: true }).click();
  await expect(tone).toContainText("Manter meu tom");
  await editing.click();
  await expect(page.getByPlaceholder("Buscar edição do texto…", { exact: true })).toBeFocused();
  await expect(page.getByRole("option", { name: "Ajustes mínimos", exact: true })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "Instruções atuais", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape"); await expect(editing).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath("clarity-natural.png"), fullPage: true });
  await openStyleReview(page);
  await page.getByRole("switch", { name: "Ativar revisão por IA", exact: true }).click();
  await expect(tone).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("disabled-refinement.png"), fullPage: true });
});

test("styles: output preference saves through the toolbar owner without saving provider drafts", async ({ page }, testInfo) => {
  await openStyleReview(page);
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep this unsaved provider draft.");
  const output = page.getByRole("combobox", { name: "Idioma de saída", exact: true });
  await output.click(); await page.getByRole("option", { name: "Español", exact: true }).click();
  const state = await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
  expect(state.language).toBe("es"); expect(state.routePrompt).not.toBe("Keep this unsaved provider draft.");
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this unsaved provider draft.");
  await page.reload(); await navigate(page, "Estilo"); await openDisclosure(page, "Mais opções");
  await expect(output).toContainText("Español");
  for (const width of [640, 820, 1040]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await output.focus(); await page.keyboard.press("Enter"); await expect(page.getByRole("option", { name: "Español", exact: true })).toBeVisible(); await page.keyboard.press("Escape"); await expect(output).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath(`style-${width}.png`), fullPage: true });
  }
});



});

settingsScenario({ initialPage: "style", quota: true }, () => {
test("quota: styles hide tone for preserve without exposing personal provider routes", async ({ page }) => {
  await expect(page.getByRole("combobox", { name: "Tom", exact: true })).toBeVisible();
  const editing = page.getByRole("combobox", { name: "Edição do texto", exact: true });
  await editing.click(); await page.getByRole("option", { name: "Manter minhas palavras", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Tom", exact: true })).toHaveCount(0);
  await page.reload(); await navigate(page, "Estilo"); await expect(editing).toContainText("Manter minhas palavras");
  await openDisclosure(page, "Mais opções");
  await expect(page.getByRole("button", { name: "Modelo e instruções da revisão", exact: true })).toHaveCount(0);
});

});
