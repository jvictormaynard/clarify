import { expect, type Page } from "@playwright/test";

export const settingsDialog = (page: Page) => page.getByRole("dialog", { name: /^(Configurações|Settings|Ajustes)$/ });

export async function openDisclosure(page: Page, name: string) {
  const trigger = page.getByRole("button", { name, exact: true });
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  const panel = page.locator(`[id="${await trigger.getAttribute("aria-controls")}"]`);
  await expect(panel).not.toHaveAttribute("data-starting-style");
  await expect.poll(() => panel.evaluate(element => element.getAnimations().filter(animation => animation.playState === "running").length)).toBe(0);
}

export function settingsSectionLabel(section: string) {
  const aliases: Record<string, string> = { Ditado: "Geral", Atalhos: "Geral", Privacidade: "Dados e privacidade", "Conta Clarify": "Conta", Dictation: "General", Shortcuts: "General", Privacy: "Data & Privacy", "Clarify account": "Account", Dictado: "General", Atajos: "General", Privacidad: "Datos y privacidad", "Cuenta Clarify": "Cuenta" };
  return aliases[section] ?? section;
}

export async function openSettings(page: Page, section: string) {
  await expect(page.locator("main .page-content")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".settings-dialog[data-ending-style]")).toHaveCount(0);
  const dialog = settingsDialog(page);
  if (!await dialog.isVisible()) {
    await page.getByRole("button", { name: /^(Configurações|Settings|Ajustes)$/ }).click();
  }

  await dialog.getByRole("button", { name: settingsSectionLabel(section), exact: true }).click();
  return dialog;
}

export async function closeSettings(page: Page) {
  const dialog = settingsDialog(page);
  if (await dialog.isVisible()) {
    await dialog.getByRole("button", { name: /^(Fechar|Close|Cerrar)$/ }).click();
    await expect(dialog).toBeHidden();
  }
}

export async function navigate(page: Page, destination: string) {
  await expect(page.locator("main .page-content")).toBeVisible({ timeout: 30000 });
  if (["Ditado", "Dictation", "Dictado", "Geral", "Sistema", "Dispositivos", "Modelos e serviços", "Atalhos", "Privacidade", "Conta Clarify",
    "General", "System", "Devices", "Dispositivos", "Models and services", "Shortcuts", "Privacy", "Clarify account", "Cuenta Clarify"].includes(destination)) {
    await openSettings(page, destination);
  } else {
    await closeSettings(page);
    await page.locator("aside nav").getByRole("button", { name: destination === "Histórico" ? "Início" : destination === "History" ? "Home" : destination, exact: true }).click();
  }
}

export async function openStyleReview(page: Page, language = "pt") {
  const name = language === "en" ? "Style" : "Estilo";
  if (await settingsDialog(page).isVisible() ||
    !await page.getByRole("heading", { level: 1, name, exact: true }).isVisible()) {
    await navigate(page, name);
  }
  const more = page.getByRole("button", { name: /^(More options|Mais opções|Más opciones)$/ });
  if (await more.getAttribute("aria-expanded") !== "true") await openDisclosure(page, (await more.innerText()).trim());
  const disclosure = page.getByRole("button", { name: language === "en" ? "Review model and instructions" : "Modelo e instruções da revisão", exact: true });
  if (await disclosure.getAttribute("aria-expanded") !== "true") await openDisclosure(page, (await disclosure.innerText()).trim());
  await expect(page.getByRole("textbox", { name: language === "en" ? "Instructions" : "Instruções", exact: true })).toBeVisible();
}
