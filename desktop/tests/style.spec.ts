import { test, expect, settingsScenario } from "./settings-fixture";
import { navigate, openStyleReview } from "./settings-navigation";

settingsScenario({ initialPage: "style" }, () => {
  test("styles: application rules persist and removal restores default", async ({ page }, testInfo) => {
    await expect(page.getByText("Todos os aplicativos usam o estilo geral.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Adicionar aplicativo", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Estilo do aplicativo", exact: true });
    await dialog.getByRole("textbox", { name: "Caminho do aplicativo", exact: true }).fill("C:\\Apps\\Editor.exe");
    await dialog.getByRole("combobox", { name: "Estilo de escrita", exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath("writing-tone-picker.png") });
    await page.getByRole("option", { name: "Formal", exact: true }).click();
    await dialog.getByRole("button", { name: "Salvar regra", exact: true }).click();
    await expect(dialog).toBeHidden();
    const saved = page.getByRole("button", { name: "Editar estilo de editor", exact: true });
    await expect(saved).toBeVisible();
    await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
    await page.reload(); await navigate(page, "Estilo");
    await saved.click();
    await expect(dialog.getByRole("combobox", { name: "Estilo de escrita", exact: true })).toContainText("Formal");
    await dialog.getByRole("button", { name: "Detalhes do aplicativo", exact: true }).click();
    await expect(dialog.getByRole("textbox", { name: "Caminho do aplicativo", exact: true })).toHaveValue("c:\\apps\\editor.exe");
    await page.screenshot({ path: testInfo.outputPath("application-writing-styles.png"), fullPage: true });
    await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
    await page.getByRole("button", { name: "Remover regra", exact: true }).click();
    await expect(saved).toBeHidden();
    await expect(page.getByText("Todos os aplicativos usam o estilo geral.", { exact: true })).toBeVisible();
  });
});

settingsScenario({ initialPage: "style" }, () => {
  test("styles: preserve explains that an app rule cannot enable cloud processing", async ({ page }) => {
    await page.getByRole("combobox", { name: "Após o ditado", exact: true }).click();
    await page.getByRole("option", { name: "Preservar palavras", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Estilo não aplicado nesta rota." })).toBeVisible();
  });
});

settingsScenario({ initialPage: "style" }, () => {
  test("cleanup: levels persist across pages and explain minimal changes", async ({ page }, testInfo) => {
    const level = page.getByRole("combobox", { name: "Após o ditado", exact: true });
    await expect(level).toContainText("Natural");
    await level.click();
    await page.getByRole("option", { name: "Ajustes mínimos", exact: true }).click();
    await expect(level).toContainText("Ajustes mínimos");
    await expect(page.getByText("Ajusta apenas espaços e tabulações. Mantém hesitações, repetições e autocorreções.")).toBeVisible();
    await navigate(page, "Ditado");
    await expect(level).toHaveCount(0);
    await navigate(page, "Estilo");
    await expect(level).toContainText("Ajustes mínimos");
    await level.click();
    await page.getByRole("option", { name: "Preservar palavras", exact: true }).click();
    await expect(level).toContainText("Preservar palavras");
    await navigate(page, "Estilo");
    await expect(level).toContainText("Preservar palavras");
    await level.click();
    await page.getByRole("option", { name: "Revisar clareza", exact: true }).click();
    await expect(level).toContainText("Revisar clareza");
    await page.screenshot({ path: testInfo.outputPath("dictation-cleanup.png"), fullPage: true });
    await level.click();
    await page.getByRole("option", { name: "Natural", exact: true }).click();
    await expect(level).toContainText("Natural");
    await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  });
});

for (const locale of ["en", "es"] as const) {
  settingsScenario({ locale: locale, initialPage: "style" }, () => {
    test(`cleanup: locale ${locale} shows honest minimal changes example`, async ({ page }) => {
      const level = page.getByRole("combobox", { name: locale === "en" ? "After dictation" : "Después del dictado", exact: true });
      await level.click();
      await page.getByRole("option", { name: locale === "en" ? "Minimal changes" : "Ajustes mínimos", exact: true }).click();
      await expect(page.getByText(locale === "en" ? "Adjusts spaces and tabs only. Keeps hesitations, repetitions and self-corrections." : "Ajusta solo espacios y tabulaciones. Conserva vacilaciones, repeticiones y autocorrecciones.")).toBeVisible();
    });
  });
}

settingsScenario({ initialPage: "style" }, () => {
  test("cleanup: clarity explains when the refinement route is disabled", async ({ page }) => {
    await openStyleReview(page);
    await page.getByRole("switch", { name: "Ativar revisão por IA", exact: true }).click();
    await navigate(page, "Estilo");
    const level = page.getByRole("combobox", { name: "Após o ditado", exact: true });
    await level.click();
    await page.getByRole("option", { name: "Revisar clareza", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Revisão indisponível nesta rota." })).toBeVisible();
    await expect(level).toContainText("Revisar clareza");
    await page.getByRole("button", { name: "Configurar revisão", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Estilo", exact: true })).toBeVisible();
  });
});
