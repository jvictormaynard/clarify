import type { Page } from "@playwright/test";
import { test, expect, settingsScenario } from "./settings-fixture";
import { navigate, openSettings, closeSettings, openStyleReview, settingsDialog, openDisclosure } from "./settings-navigation";


// The native runtime delivers these commands; OS hotkeys have contract coverage.
async function practiceCommand(page: Page, action: "start" | "stop" | "cancel") {
  await page.evaluate(async action => {
    await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "practiceCommand", args: [action] });
  }, action);
}

settingsScenario({ quota: true, initialPage: "style" }, () => {
  test("quota: cleanup choices remain available for managed accounts", async ({ page }) => {
    const level = page.getByRole("combobox", { name: "Edição do texto", exact: true });
    await level.click();
    await page.getByRole("option", { name: "Manter minhas palavras", exact: true }).click();
    await expect(level).toContainText("Manter minhas palavras");
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
      const snapshot = await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] });
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






settingsScenario({ quota: true }, () => {
  test("quota: computer access stays disabled for a signed-in account", async ({ page }) => {
    await openSettings(page, "Dispositivos");
    await expect(page.getByRole("button", { name: "Conectar celular", exact: true })).toBeDisabled();
    await expect(page.getByText("Saia da conta Clarify para conectar o celular aos seus modelos e serviços pessoais.", { exact: true })).toBeVisible();
  });
});

settingsScenario({ quota: true }, () => {
  test("quota: a signed-in startup shows no allowance until the quota arrives", async ({ page, releaseUsage }) => {
    await navigate(page, "Conta Clarify");
    await expect(page.getByRole("status").filter({ hasText: "A cota semanal não está disponível." })).toBeVisible();
    await expect(page.getByText("0 de 0 minutos neste mês", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await releaseUsage();
    await expect(page.getByRole("progressbar", { name: "Uso nesta semana" })).toHaveAttribute("aria-valuetext", "12,5% usados · 82,5% restantes");
    await expect(page.getByRole("status").filter({ hasText: "A cota semanal não está disponível." })).toHaveCount(0);
  });
});

settingsScenario({ quota: true, usage: "error" }, () => {
  test("quota: a failed quota request shows an error and allows a retry", async ({ page, releaseUsage }) => {
    await navigate(page, "Conta Clarify");
    await releaseUsage();
    await expect(page.getByRole("alert")).toContainText("Não foi possível conectar ao Clarify.");
    await expect(page.getByRole("status").filter({ hasText: "A cota semanal não está disponível." })).toBeVisible();
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    const retry = page.getByRole("button", { name: "Tentar novamente", exact: true });
    await expect(retry).toBeEnabled();
    await retry.click();
    await expect(page.getByRole("alert")).toContainText("Não foi possível conectar ao Clarify.");
    await expect(retry).toBeEnabled();
  });
});

for (const mode of ["legacy", "malformed"] as const) {
  settingsScenario({ quota: true, usage: mode }, () => {
    test(`quota: quota ${mode} stays unknown and allows a refresh`, async ({ page, releaseUsage }) => {
      await navigate(page, "Conta Clarify");
      await releaseUsage();
      const retry = page.getByRole("button", { name: "Tentar novamente", exact: true });
      await expect(retry).toBeEnabled();
      await retry.click();
      await expect(retry).toBeEnabled();
      await expect(page.getByRole("status").filter({ hasText: "A cota semanal não está disponível." })).toBeVisible();
      await expect(page.getByRole("progressbar")).toHaveCount(0);
      await expect(page.getByText(/minutos neste mês/)).toHaveCount(0);
    });
  });
}

for (const [mode, notice] of [
  ["waiting", "Sua conta aguarda a próxima distribuição de cotas."],
  ["unfunded", "Não há saldo de patrocínio para uma cota neste momento."],
  ["inactive", "O processamento da conta está inativo."],
] as const) {
  settingsScenario({ quota: true, usage: mode }, () => {
    test(`quota: quota ${mode} shows its status without usable credit`, async ({ page, releaseUsage }) => {
      await navigate(page, "Conta Clarify");
      await releaseUsage();
      await expect(page.getByRole("status").filter({ hasText: notice })).toBeVisible();
      await expect(page.getByRole("progressbar")).toHaveCount(0);
      await expect(page.getByText(/100%/)).toHaveCount(0);
      await expect(page.getByText(/Próxima renovação:/)).toBeVisible();
    });
  });
}

for (const mode of ["paused", "reserved"] as const) {
  settingsScenario({ quota: true, usage: mode }, () => {
    test(`quota: quota ${mode} keeps percentages and reports processing unavailable`, async ({ page, releaseUsage }) => {
      await navigate(page, "Conta Clarify");
      await releaseUsage();
      await expect(page.getByRole("status").filter({ hasText: "O processamento da conta está indisponível no momento." })).toBeVisible();
      await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuetext", mode === "reserved"
        ? "100% usados · 0% restantes" : "12,5% usados · 82,5% restantes");
      await expect(page.getByText("Você usou toda a sua cota semanal.", { exact: true })).toHaveCount(0);
    });
  });
}

test.describe("weekly reset timezone", () => {
  test.use({ timezoneId: "America/Los_Angeles" });
  for (const labels of [
    { locale: "pt", account: "Conta Clarify", exhausted: "Você usou toda a sua cota semanal.", reset: "Próxima renovação:", percent: "100% usados · 0% restantes" },
    { locale: "en", account: "Clarify account", exhausted: "You have used your weekly quota.", reset: "Next reset:", percent: "100% used · 0% remaining" },
    { locale: "es", account: "Cuenta Clarify", exhausted: "Has agotado tu cuota semanal.", reset: "Próxima renovación:", percent: "100 % usado · 0 % restante" },
] as const) {
    settingsScenario({ quota: true, locale: labels.locale, usage: "exhausted" }, () => {
      test(`quota: quota exhausted locale ${labels.locale} identifies exhaustion and shows the local reset`, async ({ page, releaseUsage }) => {
        await navigate(page, labels.account);
        await releaseUsage();
        await expect(page.getByRole("status").filter({ hasText: labels.exhausted })).toHaveText(labels.exhausted);
        await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
        const reset = page.getByText(new RegExp(labels.reset));
        await expect(reset).toContainText(labels.locale === "pt" ? /, (16|17):00 GMT-(7|8)\./ : /(PDT|PST|GMT-[78])/);
        await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuetext", labels.locale === "es" ? /100\s*% usado · 0\s*% restante/ : labels.percent);
      });
    });
  }
  settingsScenario({ quota: true }, () => {
    test("quota: reset uses local device time", async ({ page, releaseUsage }) => {
      await navigate(page, "Conta Clarify");
      await releaseUsage();
      await expect(page.getByText(/Próxima renovação:/)).toContainText(/, (16|17):00 GMT-(7|8)\./);
    });
  });
});

settingsScenario({ onboarding: true }, () => {
  test("onboarding: first run offers login methods and a visible guest action before Settings", async ({ page }) => {
    await expect(page.getByRole("navigation", { name: "Configurações" })).toBeHidden();
    await expect(page.getByText(/300 minutos/)).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "E-mail", exact: true })).toBeHidden();
    for (const provider of ["Google", "Microsoft", "GitHub", "e-mail"])
      await expect(page.getByRole("button", { name: `Continuar com ${provider}`, exact: true })).toBeVisible();
    const guest = page.getByRole("button", { name: "Continuar sem conta", exact: true });
    await expect(guest).toBeVisible();
    expect((await guest.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    for (const name of ["Entrar", "Criar conta", "Usar minha chave de API"])
      await expect(page.getByRole("button", { name, exact: true })).toBeHidden();
    await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
    await page.getByRole("button", { name: "Usar minha chave de API", exact: true }).click();
    await page.getByRole("textbox", { name: "Chave de API do Groq" }).fill("invalid");
    await page.getByRole("button", { name: "Salvar chave e continuar" }).click();
    await expect(page.getByRole("alert")).toContainText("chave válida");
    await page.getByRole("textbox", { name: "Chave de API do Groq" }).fill("gsk_test_only");
    await page.getByRole("button", { name: "Salvar chave e continuar" }).click();
    await expect(page.getByRole("heading", { name: "Vamos preparar seu ditado" })).toBeVisible();
    await page.getByRole("button", { name: "Pular prática", exact: true }).click();
    await expect(page.getByRole("navigation", { name: "Configurações" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole("heading", { name: "Boas-vindas ao Clarify" })).toBeHidden();
  });
});

test("login methods: Settings keeps the email draft and guest preferences", async ({ page }) => {
  const before = await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
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
  const afterEdit = await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
  expect(afterEdit.accountState.pending).toBeFalsy();
  await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Geral", exact: true })).toBeVisible();
  const after = await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
  expect(after.accountState.signedIn).toBe(false);
  expect(after.selectedMicrophoneId).toBe(before.selectedMicrophoneId);
  expect(after.historyEnabled).toBe(before.historyEnabled);
});

settingsScenario({ onboarding: true }, () => {
  test("onboarding: practice is explicit, keeps its result here and can be repeated", async ({ page }, testInfo) => {
    await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
    await page.getByRole("button", { name: "Usar minha chave de API", exact: true }).click();
    await page.getByRole("textbox", { name: "Chave de API do Groq" }).fill("gsk_test_only");
    await page.getByRole("button", { name: "Salvar chave e continuar" }).click();
    await expect(page.getByRole("heading", { name: "Vamos preparar seu ditado" })).toBeVisible();
    await expect(page.locator(".onboarding-keys")).toContainText("Alt");
    await expect(page.getByRole("textbox", { name: "Texto do seu ditado" })).toHaveCount(0);
    await page.getByRole("button", { name: "Testar microfone", exact: true }).click();
    await expect(page.getByRole("meter", { name: "Nível do microfone" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Conferir configuração", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Começar ditado", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Parar teste", exact: true }).click();
    await expect.poll(() => page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })).microphoneTestBusy)).toBe(false);
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

settingsScenario({ quota: true, usage: "exhausted" }, () => {
  test("quota: quota exhausted practice shows the next account action before capture", async ({ page, releaseUsage }) => {
    await releaseUsage();
    await navigate(page, "Geral");
    await page.getByRole("button", { name: "Praticar ditado", exact: true }).click();
    await expect(page.getByText("Não há cota disponível. Confira o saldo e a próxima renovação na sua conta.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Começar ditado", exact: true })).toHaveCount(0);
    await page.getByRole("link", { name: "Conferir configuração", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Conta", exact: true })).toBeVisible();
  });
});

settingsScenario({ onboarding: true, practice: "auth-error" }, () => {
  test("onboarding: practice BYOK auth error links to personal configuration", async ({ page }) => {
    await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
    await page.getByRole("button", { name: "Usar minha chave de API", exact: true }).click();
    await page.getByRole("textbox", { name: "Chave de API do Groq" }).fill("gsk_test_only");
    await page.getByRole("button", { name: "Salvar chave e continuar" }).click();
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
    await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
    await page.getByRole("button", { name: "Usar minha chave de API", exact: true }).click();
    await page.getByRole("textbox", { name: "Chave de API do Groq" }).fill("gsk_test_only");
    await page.getByRole("button", { name: "Salvar chave e continuar" }).click();
    await page.getByRole("button", { name: "Continuar", exact: true }).click();
    await practiceCommand(page, "start");
    await practiceCommand(page, "stop");
    await expect(page.getByText("Limite do provedor atingido. Verifique seu saldo ou plano.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
    await page.getByRole("link", { name: "Conferir configuração", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Modelos e serviços", exact: true })).toBeVisible();
  });
});

settingsScenario({ quota: true, practice: "account-error" }, () => {
  test("quota: practice account error shows the quota action after processing", async ({ page, releaseUsage }) => {
    await releaseUsage();
    await navigate(page, "Geral");
    await page.getByRole("button", { name: "Praticar ditado", exact: true }).click();
    await page.getByRole("button", { name: "Continuar", exact: true }).click();
    await practiceCommand(page, "start");
    await practiceCommand(page, "stop");
    await expect(page.getByText("Não há cota disponível. Confira o saldo e a próxima renovação na sua conta.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeDisabled();
    await page.getByRole("link", { name: "Conferir configuração", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Conta", exact: true })).toBeVisible();
  });
});

settingsScenario({ onboarding: true }, () => {
  test("onboarding: email confirmation activates account processing immediately", async ({ page }) => {
    await page.getByRole("button", { name: "Continuar com e-mail", exact: true }).click();
    await page.getByRole("textbox", { name: "E-mail", exact: true }).fill("test@example.test");
    await page.getByRole("textbox", { name: "E-mail", exact: true }).press("Enter");
    await expect(page.getByText("Digite o código enviado para test@example.test.", { exact: false })).toBeVisible();
    await page.getByRole("textbox", { name: "Código recebido por e-mail" }).fill("000000");
    await page.getByRole("button", { name: "Confirmar código" }).click();
    await expect(page.getByRole("alert")).toContainText("Código inválido");
    await page.getByRole("textbox", { name: "Código recebido por e-mail" }).fill("123456");
    await page.getByRole("button", { name: "Confirmar código" }).click();
    await expect(page.getByRole("heading", { name: "Sua conta está pronta" })).toBeVisible();
    await expect(page.getByText(/Patrocínios financiam uma cota semanal individual/)).toBeVisible();
    await expect(page.getByText(/300 minutos/)).toHaveCount(0);
    await expect(page.getByRole("navigation")).toBeHidden();
    await expect(page.getByRole("button", { name: "Ativar processamento do Clarify" })).toHaveCount(0);
    await page.getByRole("button", { name: "Começar", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Vamos preparar seu ditado" })).toBeVisible();
    await page.getByRole("button", { name: "Pular prática", exact: true }).click();
    await expect(page.getByRole("navigation")).toBeVisible();
    await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeHidden();
    await navigate(page, "Estilo");
    await expect(page.getByRole("heading", { level: 1, name: "Estilo", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Serviço", exact: true })).toBeHidden();
    await navigate(page, "Conta Clarify");
    const usage = page.getByRole("progressbar", { name: "Uso nesta semana" });
    await expect(usage).toHaveAttribute("aria-valuenow", "12.5");
    await expect(usage).toHaveAttribute("aria-valuetext", "12,5% usados · 82,5% restantes");
    await expect(page.getByText("Atualizada após cada processamento.", { exact: false })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Ativar processamento do Clarify" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Sair da conta", exact: true })).toBeHidden();
    await expect(page.getByRole("button", { name: "Excluir conta", exact: true })).toBeHidden();
    await openDisclosure(page, "Zona de perigo");
    for (const label of ["Sair da conta", "Excluir conta"]) {
      const button = page.getByRole("button", { name: label, exact: true });
      await expect(button).toBeVisible();
      expect(await button.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
    }
    await page.getByRole("button", { name: "Excluir conta", exact: true }).click();
    await expect(page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ })).toBeVisible();
    await expect(page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ }).getByRole("button", { name: "Cancelar", exact: true })).toBeFocused();
    await page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ }).getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ })).toHaveCount(0);
    await expect(usage).toBeVisible();
    await page.getByRole("button", { name: "Sair da conta", exact: true }).click();
    await expect(page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ })).toBeVisible();
    await page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ }).getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ })).toHaveCount(0);
    await expect(usage).toBeVisible();
    await page.getByRole("button", { name: "Sair da conta", exact: true }).click();
    await page.getByRole("dialog", { name: /^(Excluir conta|Sair da conta)$/ }).getByRole("button", { name: "Sair da conta", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Sair da conta", exact: true })).toBeHidden();
    await closeSettings(page);
    await navigate(page, "Estilo");
    await expect(page.getByRole("heading", { level: 1, name: "Estilo", exact: true })).toBeVisible();
    await openSettings(page, "Geral");
    await expect(settingsDialog(page).getByRole("button", { name: "Modelos e serviços", exact: true })).toBeVisible();
    await closeSettings(page);
    await openStyleReview(page);
    await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toBeVisible();
  });
});

for (const provider of ["Google", "Microsoft", "GitHub"]) {
  settingsScenario({ onboarding: true }, () => {
    test(`onboarding: social ${provider} signs in without requiring the email form`, async ({ page }) => {
      await expect(page.getByRole("textbox", { name: "E-mail", exact: true })).toBeHidden();
      await page.getByRole("button", { name: `Continuar com ${provider}`, exact: true }).click();
      await expect(page.getByRole("heading", { name: "Sua conta está pronta" })).toBeVisible();
      await expect(page.getByText(`${provider.toLowerCase()}@example.test`, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Começar", exact: true }).click();
      await page.getByRole("button", { name: "Pular prática", exact: true }).click();
      await expect(page.getByRole("navigation")).toBeVisible();
    });
  });
}

settingsScenario({ onboarding: true, socialWait: true }, () => {
  test("onboarding: social cancellation stays enabled while the browser login is pending", async ({ page }) => {
    await page.getByRole("button", { name: "Continuar com Google", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Conclua o login no navegador");
    const cancel = page.getByRole("button", { name: "Cancelar login", exact: true });
    await expect(cancel).toBeEnabled();
    await cancel.click();
    await expect(page.getByRole("alert")).toContainText("O login foi cancelado.");
    await expect(page.getByRole("button", { name: "Continuar com Google", exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Continuar com e-mail", exact: true })).toBeVisible();
  });
});

settingsScenario({ onboarding: true, socialWait: true }, () => {
  test("onboarding: account social cancellation restores provider actions after local setup", async ({ page }) => {
    await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
    await page.getByRole("button", { name: "Continuar com modelo local" }).click();
    await page.getByRole("button", { name: "Pular prática", exact: true }).click();
    await navigate(page, "Conta Clarify");
    await page.getByText("Servidor próprio", { exact: true }).click();
    const server = page.getByRole("textbox", { name: "Endereço do servidor", exact: true });
    const saveServer = page.getByRole("button", { name: "Salvar servidor", exact: true });
    const navigation = settingsDialog(page).getByRole("navigation");
    const cancel = page.getByRole("button", { name: "Cancelar login", exact: true });
    await expect(server).toBeEnabled();

    let releaseCancel!: () => void;
    const cancelGate = new Promise<void>(resolve => { releaseCancel = resolve; });
    let cancelRequested!: () => void;
    const cancelRequest = new Promise<void>(resolve => { cancelRequested = resolve; });
    await page.route("**/__test_rpc", async route => {
      const request = route.request().postDataJSON();
      if (request.method === "accountCommand" && request.args[0] === "cancel-social") {
        cancelRequested();
        await cancelGate;
      }
      await route.fallback();
    });
    try {
      await page.getByRole("button", { name: "Continuar com Google", exact: true }).click();
      await expect(page.getByRole("status").filter({ hasText: "Conclua o login no navegador" })).toBeVisible();
      for (const button of await navigation.getByRole("button").all()) await expect(button).toBeEnabled();
      await expect(server).toBeDisabled();
      await expect(saveServer).toBeDisabled();
      await expect(cancel).toBeEnabled();
      await cancel.click();
      await cancelRequest;
      await expect(cancel).toBeDisabled();
      await expect(server).toBeDisabled();
      await expect(saveServer).toBeDisabled();
      for (const button of await navigation.getByRole("button").all()) await expect(button).toBeEnabled();
    } finally {
      releaseCancel();
    }

    await expect(page.getByRole("alert")).toContainText("O login foi cancelado.");
    await expect(cancel).toHaveCount(0);
    for (const provider of ["Google", "Microsoft", "GitHub"]) {
      await expect(page.getByRole("button", { name: `Continuar com ${provider}`, exact: true })).toBeEnabled();
    }
    await expect(page.getByRole("button", { name: "Continuar com e-mail", exact: true })).toBeEnabled();
    await expect(server).toBeEnabled();
    await expect(saveServer).toBeEnabled();
    for (const button of await navigation.getByRole("button").all()) await expect(button).toBeEnabled();
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

settingsScenario({ onboarding: true, practice: "missing-model" }, () => {
  test("onboarding: local choice leads to model setup without a login", async ({ page }) => {
    await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
    await page.getByRole("button", { name: "Continuar com modelo local" }).click();
    await expect(page.getByRole("heading", { name: "Vamos preparar seu ditado" })).toBeVisible();
    await page.getByRole("link", { name: "Configurar modelo", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Modelos e serviços", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Modelo local", exact: true })).toBeVisible();
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
  settingsScenario({ onboarding: true, locale: labels.locale }, () => {
    test(`onboarding: locale ${labels.locale} keeps auth geometry and restores the skip action on Back`, async ({ page }) => {
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
  test("snippets account: sidebar excludes personal processing controls", async ({ page }) => {
    await closeSettings(page);
    await expect(page.locator("aside nav").getByRole("button")).toHaveCount(6);
    await navigate(page, "Estilo");
    const settings = await openSettings(page, "Geral");
    await expect(settings.getByRole("button", { name: "Modelos e serviços", exact: true })).toHaveCount(0);
    await closeSettings(page);
    await navigate(page, "Histórico");
    await expect(page.getByRole("heading", { name: "Bem-vindo de volta", exact: true })).toBeVisible();
  });
});
