import type { Page } from "@playwright/test";
import { test, expect, settingsScenario } from "./settings-fixture";
import { navigate, openSettings, closeSettings, openStyleReview, settingsDialog, openDisclosure } from "./settings-navigation";


async function finishPersonalSetup(page: Page) {
  await page.getByRole("button", { name: "Vamos começar", exact: true }).click();
  for (const step of ["language", "speech", "text"]) {
    await expect(page.locator(".personal-setup")).toHaveAttribute("data-step", step);
    await page.getByRole("button", { name: "Continuar", exact: true }).click();
  }
  await expect(page.locator(".personal-setup")).toHaveAttribute("data-step", "install");
  await page.getByRole("button", { name: "Verificar e experimentar", exact: true }).click();
}

// The native runtime delivers these commands; OS hotkeys have contract coverage.
async function practiceCommand(page: Page, action: "start" | "stop" | "cancel") {
  await page.evaluate(async action => {
    await (window as any).__testSettings({ method: "practiceCommand", args: [action] });
  }, action);
}

settingsScenario({ signedIn: true, initialPage: "style" }, () => {
  test("account: cleanup choices remain available with personal processing", async ({ page }) => {
    const level = page.getByRole("combobox", { name: "Edição do texto", exact: true });
    await level.click();
    await page.getByRole("option", { name: "Manter minhas palavras", exact: true }).click();
    await expect(level).toContainText("Manter minhas palavras");
    await expect(page.getByRole("combobox", { name: "Tom", exact: true })).toHaveCount(0);
    await page.reload(); await navigate(page, "Estilo");
    await expect(level).toContainText("Manter minhas palavras");
  });
});

settingsScenario({ signedIn: true }, () => {
  test("snippets account: background refresh keeps confirmation Cancel focused and dismissible", async ({ page }) => {
    await navigate(page, "Conta Clarify");
    await openDisclosure(page, "Zona de perigo");
    await page.getByRole("button", { name: "Excluir conta", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Excluir conta", exact: true });
    const cancel = dialog.getByRole("button", { name: "Cancelar", exact: true });
    await expect(cancel).toBeFocused();
    const account = await page.evaluate(async () => {
      const snapshot = await (window as any).__testSettings({ method: "snapshot", args: [] });
      return snapshot.accountState;
    });
    await page.route("**/__test_rpc", async route => {
      if (route.request().postDataJSON().method === "poll") {
        await route.fulfill({ json: { result: { accountState: { ...account, busy: true } } } });
      } else await route.fallback();
    });
    await expect(dialog.getByRole("button", { name: "Confirmar exclusão da conta", exact: true })).toBeDisabled();
    await expect(cancel).toBeEnabled();
    await expect(cancel).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });
});






test("login methods: Settings keeps the email draft and guest preferences", async ({ page }) => {
  const before = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
  await navigate(page, "Conta Clarify");
  const email = page.getByRole("textbox", { name: "E-mail", exact: true });
  const chooseEmail = page.getByRole("button", { name: "Continuar com e-mail", exact: true });
  await expect(email).toBeHidden();
  await chooseEmail.click();
  await expect(email).toBeFocused();
  await email.fill("unsent@example.test");
  await page.getByRole("button", { name: "Voltar", exact: true }).click();
  await expect(chooseEmail).toBeFocused();
  await chooseEmail.click();
  await expect(email).toHaveValue("unsent@example.test");
  const afterEdit = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
  expect(afterEdit.accountState.pending).toBeFalsy();
  await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Geral", exact: true })).toBeVisible();
  const after = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
  expect(after.accountState.signedIn).toBe(false);
  expect(after.selectedMicrophoneId).toBe(before.selectedMicrophoneId);
  expect(after.historyEnabled).toBe(before.historyEnabled);
});

settingsScenario({ onboarding: true }, () => {
  test("onboarding: practice is explicit, keeps its result here and can be repeated", async ({ page }, testInfo) => {
    await finishPersonalSetup(page);
    await expect(page.getByRole("heading", { name: "Vamos preparar seu ditado" })).toBeVisible();
    await expect(page.locator(".onboarding-keys")).toContainText("Alt");
    await expect(page.getByRole("textbox", { name: "Texto do seu ditado" })).toHaveCount(0);
    await page.getByRole("button", { name: "Testar microfone", exact: true }).click();
    await expect(page.getByRole("meter", { name: "Nível do microfone" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Conferir configuração", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Começar ditado", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Parar teste", exact: true }).click();
    await expect.poll(() => page.evaluate(async () => (await (window as any).__testSettings({ method: "snapshot", args: [] })).microphoneTestBusy)).toBe(false);
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
    for (const width of [640, 820, 1040]) {
      await page.setViewportSize({ width, height: 760 });
      await page.screenshot({ path: testInfo.outputPath(`onboarding-setup-${width}.png`) });
    }
    await page.getByRole("button", { name: "Testar microfone", exact: true }).click();
    await page.getByRole("button", { name: "Continuar", exact: true }).click();
    await expect(page.getByRole("meter", { name: "Nível do microfone" })).toHaveCount(0);
    const composer = page.getByRole("group", { name: "E-mail de prática", exact: true });
    await composer.focus();
    await expect(composer).toBeFocused();
    await expect(composer.locator(".onboarding-keys")).toBeVisible();
    await expect(page.locator(".onboarding-flow-actions").getByRole("button")).toHaveText(["Pular prática", "Continuar"]);
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
    await expect(composer.getByRole("textbox", { name: "Assunto", exact: true })).toHaveValue("Uma conversa rápida");
    await expect(composer.getByText("Diga, por exemplo: Hoje vou escrever uma mensagem com o Clarify.", { exact: true })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("onboarding-practice.png") });
    await practiceCommand(page, "start");
    await expect(composer.locator(".onboarding-keys")).toHaveCount(0);
    await expect(composer.getByRole("textbox", { name: "Assunto", exact: true })).toHaveValue("Uma conversa rápida");
    await expect(composer.getByText("Hoje vou escrever uma mensagem com o Clarify.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
    await expect(composer.getByRole("textbox", { name: "Texto do seu ditado" })).toHaveCount(0);
    await practiceCommand(page, "cancel");
    await expect(composer.locator(".onboarding-keys")).toBeVisible();
    await expect(composer.getByText("Hoje vou escrever uma mensagem com o Clarify.", { exact: true })).toHaveCount(0);
    await practiceCommand(page, "start");
    await practiceCommand(page, "stop");
    await expect(page.getByRole("textbox", { name: "Texto do seu ditado" })).toHaveValue("Hoje vou escrever com o Clarify.");
    await expect(composer.getByRole("textbox", { name: "Assunto", exact: true })).toHaveValue("Uma conversa rápida");
    await expect(page.getByRole("heading", { name: "Seu ditado está pronto", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
    await page.screenshot({ path: testInfo.outputPath("onboarding-success.png") });
    await practiceCommand(page, "start");
    await expect(composer.getByRole("textbox", { name: "Texto do seu ditado" })).toHaveCount(0);
    await expect(composer.locator(".onboarding-keys")).toHaveCount(0);
    await expect(composer.getByText("Hoje vou escrever uma mensagem com o Clarify.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
    await practiceCommand(page, "stop");
    await expect(page.getByRole("heading", { name: "Seu ditado está pronto", exact: true })).toBeVisible();
    await page.setViewportSize({ width: 640, height: 520 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
    await page.getByRole("button", { name: "Continuar", exact: true }).click();
    await page.getByRole("button", { name: "Pular prática", exact: true }).click();
    await navigate(page, "Geral");
    await page.getByRole("button", { name: "Praticar ditado", exact: true }).click();
    await expect(settingsDialog(page)).toBeHidden();
    await expect(page.getByRole("textbox", { name: "Texto do seu ditado" })).toHaveCount(0);
    await page.getByRole("button", { name: "Pular prática", exact: true }).click();
    await expect(settingsDialog(page)).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Boas-vindas ao Clarify" })).toBeHidden();
    await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible({ timeout: 30000 });
  });
});

settingsScenario({ onboarding: true, practice: "auth-error" }, () => {
  test("onboarding: practice BYOK auth error links to personal configuration", async ({ page }) => {
    await finishPersonalSetup(page);
    await page.getByRole("button", { name: "Continuar", exact: true }).click();
    await practiceCommand(page, "start");
    await practiceCommand(page, "stop");
    await expect(page.getByText("Conclua e salve a configuração de transcrição antes de ditar.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
    await page.getByRole("link", { name: "Conferir configuração", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Modelos e serviços", exact: true })).toBeVisible();
  });
});

settingsScenario({ onboarding: true, practice: "provider-quota" }, () => {
  test("onboarding: practice BYOK quota points to the provider balance or plan", async ({ page }) => {
    await finishPersonalSetup(page);
    await page.getByRole("button", { name: "Continuar", exact: true }).click();
    await practiceCommand(page, "start");
    await practiceCommand(page, "stop");
    await expect(page.getByText("Limite do provedor atingido. Verifique seu saldo ou plano.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
    await page.getByRole("link", { name: "Conferir configuração", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Modelos e serviços", exact: true })).toBeVisible();
  });
});

for (const provider of ["Google", "Microsoft", "GitHub"]) {
  settingsScenario({ account: true }, () => {
    test(`account: social ${provider} signs in without requiring the email form`, async ({ page }) => {
      await navigate(page, "Conta Clarify");
      await expect(page.getByRole("textbox", { name: "E-mail", exact: true })).toBeHidden();
      await page.getByRole("button", { name: `Continuar com ${provider}`, exact: true }).click();
      await expect(page.getByText(`${provider.toLowerCase()}@example.test`, { exact: true })).toBeVisible();
      await expect(settingsDialog(page)).toBeVisible();
    });
  });
}

settingsScenario({ socialWait: true }, () => {
  test("onboarding: social cancellation stays enabled while the browser login is pending", async ({ page }) => {
    await navigate(page, "Conta Clarify");
    await page.getByRole("button", { name: "Continuar com Google", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Conclua o login no navegador" })).toBeVisible();
    const cancel = page.getByRole("button", { name: "Cancelar login", exact: true });
    await expect(cancel).toBeEnabled();
    await cancel.click();
    await expect(page.getByRole("alert")).toContainText("O login foi cancelado.");
    await expect(page.getByRole("button", { name: "Continuar com Google", exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Continuar com e-mail", exact: true })).toBeVisible();
  });
});

settingsScenario({ socialWait: true }, () => {
  test("account social cancellation remains available while navigating with local drafts", async ({ page }) => {
    await navigate(page, "Conta Clarify");
    await page.getByRole("button", { name: "Continuar com Google", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Conclua o login no navegador" })).toBeVisible();
    await openStyleReview(page);
    await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep my local draft");
    await navigate(page, "Conta Clarify");
    const cancel = page.getByRole("button", { name: "Cancelar login", exact: true });
    await expect(cancel).toBeEnabled();
    await cancel.click();
    await expect(page.getByRole("alert")).toContainText("O login foi cancelado.");
    await openStyleReview(page);
    await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep my local draft");
  });
});

test("account remains optional and self-hosting configuration does not change dictation routes", async ({ page }) => {
  await navigate(page, "Conta Clarify");
  await expect(page.getByText("A conta é opcional.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Continuar com e-mail", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
  await page.getByRole("textbox", { name: "E-mail", exact: true }).fill("test@example.test");
  await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
  await page.getByText("Servidor próprio", { exact: true }).click();
  await page.getByRole("textbox", { name: "Endereço do servidor", exact: true }).fill("https://clarify.example");
  await page.getByRole("button", { name: "Salvar servidor", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
  await navigate(page, "Ditado");
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
});

for (const labels of [
  { locale: "pt", choice: "Continuar com e-mail", email: "E-mail", skip: "Continuar sem conta", next: "Continuar", code: "Código recebido por e-mail", confirm: "Confirmar código", back: "Voltar" },
  { locale: "en", choice: "Continue with email", email: "Email", skip: "Continue without an account", next: "Continue", code: "Code received by email", confirm: "Confirm code", back: "Back" },
  { locale: "es", choice: "Continuar con correo electrónico", email: "Correo electrónico", skip: "Continuar sin cuenta", next: "Continuar", code: "Código recibido por correo", confirm: "Confirmar código", back: "Volver" },
] as const) {
  settingsScenario({ account: true, locale: labels.locale }, () => {
    test(`onboarding: locale ${labels.locale} keeps auth geometry and restores the skip action on Back`, async ({ page }) => {
      await openSettings(page, labels.locale === "en" ? "Account" : labels.locale === "es" ? "Cuenta" : "Conta");
      const email = page.getByRole("textbox", { name: labels.email, exact: true });
      const next = page.getByRole("button", { name: labels.next, exact: true });
      await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeVisible();
      await expect(email).toBeHidden();
      await page.getByRole("button", { name: labels.choice, exact: true }).click();
      await expect(email).toBeEnabled();
      const first = await email.locator("xpath=..").boundingBox(), submit = await next.boundingBox();
      expect(first).not.toBeNull(); expect(submit).not.toBeNull();
      expect(Math.abs(first!.x + first!.width - submit!.x - submit!.width)).toBeLessThan(1);
      const back = await page.getByRole("button", { name: labels.back, exact: true }).boundingBox();
      expect(back!.x + back!.width).toBeLessThan(submit!.x);
      await email.locator("xpath=..").click({ position: { x: first!.width / 2, y: first!.height - 3 } });
      await expect(email).toBeFocused();
      await email.fill("test@example.test"); await next.click();
      const code = page.getByRole("textbox", { name: labels.code, exact: true });
      await expect(code).toBeVisible();
      await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeHidden();
      await expect(code).toBeEnabled();
      const verify = await code.locator("xpath=..").boundingBox();
      const confirm = await page.getByRole("button", { name: labels.confirm, exact: true }).boundingBox();
      expect(Math.abs(verify!.x + verify!.width - confirm!.x - confirm!.width)).toBeLessThan(1);
      const codeBack = await page.getByRole("button", { name: labels.back, exact: true }).boundingBox();
      expect(codeBack!.x + codeBack!.width).toBeLessThan(confirm!.x);
      await code.locator("xpath=..").click({ position: { x: verify!.width / 2, y: verify!.height - 3 } });
      await expect(code).toBeFocused();
      await page.getByRole("button", { name: labels.back, exact: true }).click();
      await expect(email).toBeVisible();
      await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeVisible();
    });
  });
}

settingsScenario({ signedIn: true }, () => {
  test("snippets account: sidebar retains personal processing controls", async ({ page }) => {
    await closeSettings(page);
    await expect(page.locator("aside nav").getByRole("button")).toHaveCount(6);
    await navigate(page, "Estilo");
    const settings = await openSettings(page, "Geral");
    await settings.getByRole("button", { name: "Modelos e serviços", exact: true }).click();
    await expect(settings.getByRole("combobox", { name: "Serviço na nuvem", exact: true })).toBeVisible();
    await openStyleReview(page);
    await navigate(page, "Conta Clarify");
    await expect(page.getByText("Dicionário e snippets", { exact: true })).toBeVisible();
    await expect(page.getByRole("progressbar", { name: "Uso nesta semana" })).toHaveCount(0);
    await expect(page.getByText(/cota semanal|saldo de patrocínio/)).toHaveCount(0);
    await closeSettings(page);
    await navigate(page, "Histórico");
    await expect(page.getByRole("heading", { name: "Bem-vindo de volta", exact: true })).toBeVisible();
  });
});
