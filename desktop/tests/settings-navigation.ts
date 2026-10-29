import { expect, type Page } from "@playwright/test";

export const settingsDialog = (page: Page) => page.getByRole("dialog", { name: /^(Configurações|Settings|Ajustes)$/ });

export async function openSettings(page: Page, section: string) {
  await expect(page.locator(".settings-dialog[data-ending-style]")).toHaveCount(0);
  const dialog = settingsDialog(page);
  if (!await dialog.isVisible()) {
    await page.getByRole("button", { name: /^(Configurações|Settings|Ajustes)$/ }).click();
  }
  await dialog.getByRole("button", { name: section, exact: true }).click();
  return dialog;
}

export async function closeSettings(page: Page) {
  const dialog = settingsDialog(page);
  if (await dialog.isVisible()) {
    await dialog.getByRole("button", { name: /^(Concluído|Done|Listo)$/ }).click();
    await expect(dialog).toBeHidden();
  }
}

export async function navigate(page: Page, destination: string) {
  if (["Geral", "Modelos e serviços", "Atalhos", "Privacidade", "Conta Clarify",
    "General", "Models and services", "Shortcuts", "Privacy", "Clarify account", "Cuenta Clarify"].includes(destination)) {
    await openSettings(page, destination);
  } else {
    await closeSettings(page);
    await page.getByRole("navigation").getByRole("button", { name: destination, exact: true }).click();
  }
}

export async function openStyleReview(page: Page, language = "pt") {
  const name = language === "en" ? "Style" : "Estilo";
  if (await settingsDialog(page).isVisible() ||
    await page.getByRole("button", { name, exact: true }).getAttribute("aria-current") !== "page") {
    await navigate(page, name);
  }
  const disclosure = page.getByRole("button", { name: language === "en" ? "Review model and instructions" : "Modelo e instruções da revisão", exact: true });
  if (await disclosure.getAttribute("aria-expanded") !== "true") await disclosure.click();
  await expect(page.getByRole("textbox", { name: language === "en" ? "Instructions" : "Instruções", exact: true })).toBeVisible();
}
