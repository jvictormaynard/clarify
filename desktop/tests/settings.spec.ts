import { test, expect } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";

let child: ChildProcessWithoutNullStreams;
let id = 0;
const pending = new Map<number, (value: unknown) => void>();
let releaseUsage: () => Promise<void>;

test("styles: application rules persist and removal restores default", async ({ page }, testInfo) => {
  await expect(page.getByText("Padrão para todos os aplicativos.", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Caminho do aplicativo", exact: true }).fill("C:\\Apps\\Editor.exe");
  await page.getByRole("combobox", { name: "Estilo de escrita", exact: true }).click();
  await page.getByRole("option", { name: "Informal", exact: true }).click();
  await page.getByRole("button", { name: "Salvar regra", exact: true }).click();
  const saved = page.getByRole("combobox", { name: "Estilo para c:\\apps\\editor.exe", exact: true });
  await expect(saved).toContainText("Informal");
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await page.reload();
  await expect(saved).toContainText("Informal");
  await page.screenshot({ path: testInfo.outputPath("application-writing-styles.png"), fullPage: true });
  await page.getByRole("button", { name: "Remover regra", exact: true }).click();
  await expect(saved).toBeHidden();
  await expect(page.getByText("Padrão para todos os aplicativos.", { exact: true })).toBeVisible();
});

test("styles: preserve explains that an app rule cannot enable cloud processing", async ({ page }) => {
  await page.getByRole("combobox", { name: "Nível de revisão", exact: true }).click();
  await page.getByRole("option", { name: "Preservar palavras", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Estilo não aplicado nesta rota." })).toBeVisible();
});

test("quota: styles remain configurable for managed accounts", async ({ page }) => {
  await page.getByRole("textbox", { name: "Caminho do aplicativo", exact: true }).fill("C:\\Apps\\Chat.exe");
  await page.getByRole("button", { name: "Salvar regra", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Estilo para c:\\apps\\chat.exe", exact: true })).toContainText("Natural");
});

test("cleanup: levels persist across pages and explain minimal changes", async ({ page }, testInfo) => {
  const level = page.getByRole("combobox", { name: "Nível de revisão", exact: true });
  await expect(level).toContainText("Padrão atual");
  await level.click();
  await page.getByRole("option", { name: "Ajustes mínimos", exact: true }).click();
  await expect(level).toContainText("Ajustes mínimos");
  await expect(page.getByText("Ajusta apenas espaços e tabulações. Mantém hesitações, repetições e autocorreções.")).toBeVisible();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(level).toContainText("Ajustes mínimos");
  await level.click();
  await page.getByRole("option", { name: "Preservar palavras", exact: true }).click();
  await expect(level).toContainText("Preservar palavras");
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  await expect(level).toContainText("Preservar palavras");
  await level.click();
  await page.getByRole("option", { name: "Revisar clareza", exact: true }).click();
  await expect(level).toContainText("Revisar clareza");
  await page.screenshot({ path: testInfo.outputPath("dictation-cleanup.png"), fullPage: true });
  await level.click();
  await page.getByRole("option", { name: "Padrão atual", exact: true }).click();
  await expect(level).toContainText("Padrão atual");
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
});

for (const locale of ["en", "es"] as const) {
  test(`cleanup: locale ${locale} shows honest minimal changes example`, async ({ page }) => {
    const level = page.getByRole("combobox", { name: locale === "en" ? "Cleanup level" : "Nivel de revisión", exact: true });
    await level.click();
    await page.getByRole("option", { name: locale === "en" ? "Minimal changes" : "Ajustes mínimos", exact: true }).click();
    await expect(page.getByText(locale === "en" ? "Adjusts spaces and tabs only. Keeps hesitations, repetitions and self-corrections." : "Ajusta solo espacios y tabulaciones. Conserva vacilaciones, repeticiones y autocorrecciones.")).toBeVisible();
  });
}

test("quota: cleanup choices remain available for managed accounts", async ({ page }) => {
  const level = page.getByRole("combobox", { name: "Nível de revisão", exact: true });
  await level.click();
  await page.getByRole("option", { name: "Preservar palavras", exact: true }).click();
  await expect(level).toContainText("Preservar palavras");
  await page.reload();
  await expect(level).toContainText("Preservar palavras");
});

test("cleanup: clarity explains when the refinement route is disabled", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  const level = page.getByRole("combobox", { name: "Nível de revisão", exact: true });
  await level.click();
  await page.getByRole("option", { name: "Revisar clareza", exact: true }).click();
  await page.getByRole("switch", { name: "Ativar este fluxo", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Revisão indisponível nesta rota." })).toBeVisible();
  await expect(level).toContainText("Revisar clareza");
});

for (const method of ["testMicrophone", "stopMicrophoneTest", "refreshMicrophones"] as const) {
  test(`responsive operations: ${method} keeps navigation and unrelated controls stable`, async ({ page }) => {
    if (method === "stopMicrophoneTest") {
      await page.getByRole("button", { name: "Testar microfone", exact: true }).click();
      await expect(page.getByRole("button", { name: "Parar teste", exact: true })).toBeVisible();
    }
    let release!: () => void;
    let started!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const entered = new Promise<void>(resolve => { started = resolve; });
    await page.route("**/__test_rpc", async route => {
      if (route.request().postDataJSON().method === method) { started(); await held; }
      await route.fallback();
    });
    const navigation = page.getByRole("button", { name: "Dicionário", exact: true });
    const before = await navigation.evaluate(element => getComputedStyle(element).opacity);
    try {
      if (method === "refreshMicrophones") {
        await page.getByRole("combobox", { name: "Microfone", exact: true }).click();
        await page.getByRole("button", { name: "Atualizar microfone", exact: true }).click();
      } else {
        await page.getByRole("button", { name: method === "testMicrophone" ? "Testar microfone" : "Parar teste", exact: true }).click();
      }
      await entered;
      if (method === "refreshMicrophones") await page.keyboard.press("Escape");
      await expect(navigation).toBeEnabled();
      await expect(navigation).toHaveCSS("opacity", before);
      await expect(page.getByRole("combobox", { name: "Serviço", exact: true })).toBeEnabled();
      await navigation.click();
      await expect(page.getByRole("heading", { name: "Dicionário", exact: true })).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Novo termo", exact: true })).toBeEnabled();
    } finally { release(); }
  });
}

test("responsive operations: saving text allows navigation and preserves edits typed during the save", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
  await prompt.fill("First text revision.");
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "save") { started(); await held; }
    await route.fallback();
  });
  try {
    await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
    await entered;
    await expect(prompt).toBeEnabled();
    await prompt.fill("Newer unsaved revision.");
    await page.getByRole("button", { name: "Dicionário", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Novo termo", exact: true })).toBeVisible();
  } finally { release(); }
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(prompt).toHaveValue("Newer unsaved revision.");
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeVisible();
});

test("contextual actions wait for the requested workflow before saving", async ({ page }) => {
  await page.getByText("Instruções da transcrição", { exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções da transcrição", exact: true }).fill("Dictation draft");
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Text draft");
  let release!: () => void, started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    if (request.method === "selectWorkflow" && request.args[0] === "transcription") { started(); await held; }
    await route.fallback();
  });
  try {
    await page.getByRole("button", { name: "Ditado", exact: true }).click();
    await entered;
    await expect(page.getByRole("heading", { name: "Ditado", exact: true })).toBeVisible();
    await expect(page.getByRole("group", { name: "Alterações pendentes", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Dicionário", exact: true })).toBeEnabled();
  } finally { release(); }
  await page.getByText("Instruções da transcrição", { exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções da transcrição", exact: true })).toHaveValue("Dictation draft");
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Text draft");
  const snapshot = await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
  expect(snapshot.routePrompt).not.toBe("Text draft");
});

for (const library of ["dictionary", "snippets"] as const) {
  test(`${library}: Save preserves a text reversion made after the click`, async ({ page }) => {
    const dictionary = library === "dictionary";
    await page.getByRole("button", { name: dictionary ? "Dicionário" : "Snippets", exact: true }).click();
    if (dictionary) {
      await page.getByRole("textbox", { name: "Novo termo", exact: true }).fill("Original term");
      await page.getByRole("button", { name: "Adicionar termo", exact: true }).click();
    } else {
      await page.getByRole("textbox", { name: "Nova frase de ativação", exact: true }).fill("original");
      await page.getByRole("textbox", { name: "Novo texto do snippet", exact: true }).fill("Original text");
      await page.getByRole("button", { name: "Adicionar snippet", exact: true }).click();
    }
    const save = page.getByRole("button", { name: "Salvar alterações", exact: true });
    await save.click();await expect(save).toBeHidden();
    const editor = page.getByRole("textbox", { name: dictionary ? "Termo 1" : "Texto do snippet 1", exact: true });
    await editor.fill("Submitted revision");
    let release!: () => void, started!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const entered = new Promise<void>(resolve => { started = resolve; });
    await page.route("**/__test_rpc", async route => {
      if (route.request().postDataJSON().method === "save") { started(); await held; }
      await route.fallback();
    });
    try {
      await save.click();await entered;
      await editor.fill(dictionary ? "Original term" : "Original text");
    } finally { release(); }
    await expect(save).toBeEnabled();
    await expect(editor).toHaveValue(dictionary ? "Original term" : "Original text");
    const read = () => page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
    let snapshot = await read();
    expect(dictionary ? snapshot.dictionaryEntries[0].term : snapshot.snippets[0].replacement).toBe("Submitted revision");
    await save.click();await expect(save).toBeHidden();snapshot = await read();
    expect(dictionary ? snapshot.dictionaryEntries[0].term : snapshot.snippets[0].replacement).toBe(dictionary ? "Original term" : "Original text");
  });
}

test("automatic preferences: switches persist without committing a pending prompt", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
  const original = await prompt.inputValue();
  await prompt.fill("Text draft must stay private until Save.");
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  const setting = page.getByRole("switch", { name: "Iniciar com o Windows", exact: true });
  const checked = await setting.isChecked();
  const response = page.waitForResponse(response => response.url().endsWith("/__test_rpc") && response.request().postDataJSON().method === "savePreference");
  await setting.click();
  await response;
  const persisted = await page.evaluate(async () => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "load", args: [] }));
  expect(persisted.autostart).toBe(!checked);
  expect(persisted.routePrompt).toBe(original);
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(prompt).toHaveValue("Text draft must stay private until Save.");
});

test("desktop navigation: Settings has no global search or floating save island", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Buscar configurações…", exact: true })).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".floating-save")).toHaveCount(0);
});

test("contextual confirmation: Save keeps drafts from other pages unsaved", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
  const original = await prompt.inputValue();
  await prompt.fill("Keep this text draft unsaved.");
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  const history = page.getByRole("switch", { name: "Salvar histórico", exact: true });
  if (!await history.isChecked()) await history.click();
  await expect(history).toBeChecked();
  await page.getByRole("spinbutton", { name: "Retenção do histórico", exact: true }).fill("31");
  await page.getByRole("group", { name: "Alterações pendentes" }).getByRole("button", { name: "Descartar", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Alterações não salvas" });
  await confirmation.getByRole("button", { name: "Salvar", exact: true }).click();
  await expect(confirmation).toHaveCount(0);
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(prompt).toHaveValue("Keep this text draft unsaved.");
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(prompt).toHaveValue(original);
});

test("responsive account: pending microphone work does not disable sign-in", async ({ page }) => {
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "testMicrophone") { started(); await held; }
    await route.fallback();
  });
  try {
    await page.getByRole("button", { name: "Testar microfone", exact: true }).click();
    await entered;
    await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
    await page.getByRole("textbox", { name: "E-mail", exact: true }).fill("test@example.test");
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
  } finally { release(); }
});

test("snippets account: background refresh keeps confirmation Cancel focused and dismissible", async ({ page }) => {
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  await page.getByText("Zona de perigo", { exact: true }).click();
  await page.getByRole("button", { name: "Excluir conta", exact: true }).click();
  const dialog = page.getByRole("dialog");
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

test("provider selection: pending selection cannot transfer a key typed for the visible provider", async ({ page }) => {
  await page.getByRole("button", { name: "Modelos e serviços", exact: true }).click();
  const provider = page.getByRole("combobox", { name: "Serviço na nuvem", exact: true });
  const key = page.getByLabel("Chave de API", { exact: true });
  await expect(key).toBeEnabled();
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "selectProvider") { started(); await held; }
    await route.fallback();
  });
  try {
    await provider.click();
    await page.getByRole("option", { name: "OpenAI", exact: true }).click();
    await entered;
    await expect(page.getByRole("button", { name: "Dicionário", exact: true })).toBeEnabled();
    // Either bind edits to the displayed provider or guard these inputs during selection.
    if (await key.isEnabled()) await key.fill("sk_test_only_visible_provider");
  } finally { release(); }
  await expect(provider).toContainText("OpenAI");
  await expect(key).toBeEnabled();
  await expect(key).toHaveValue("");
});
test("snippets: add edit disable discard and remove a multiline snippet", async ({ page }) => {
  await page.getByRole("button", { name: "Snippets", exact: true }).click();
  await page.getByRole("textbox", { name: "Nova frase de ativação" }).fill("minha assinatura");
  await page.getByRole("textbox", { name: "Novo texto do snippet" }).fill("Nome\n  Equipe\n");
  await page.getByRole("button", { name: "Adicionar snippet", exact: true }).click();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("textbox", { name: "Texto do snippet 1", exact: true })).toHaveValue("Nome\n  Equipe\n");
  await page.getByRole("textbox", { name: "Texto do snippet 1", exact: true }).fill("Editado");
  await page.getByRole("switch", { name: "Usar snippet 1", exact: true }).click();
  await page.getByRole("button", { name: "Descartar", exact: true }).click();
  await page.getByRole("dialog", { name: "Alterações não salvas" }).getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Texto do snippet 1", exact: true })).toHaveValue("Nome\n  Equipe\n");
  await expect(page.getByRole("switch", { name: "Usar snippet 1", exact: true })).not.toBeChecked();
  await page.getByRole("textbox", { name: "Buscar snippets" }).fill("ausente");
  await expect(page.getByText("Nenhum snippet encontrado.")).toBeVisible();
  await page.getByRole("textbox", { name: "Buscar snippets" }).clear();
  await page.getByRole("button", { name: "Remover snippet 1", exact: true }).click();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByText("Adicione seu primeiro snippet acima.")).toBeVisible();
});
test("snippets: composer preserves both fields typed while an earlier row Save waits", async ({ page }) => {
  await page.getByRole("button", { name: "Snippets", exact: true }).click();
  const trigger = page.getByRole("textbox", { name: "Nova frase de ativação", exact: true });
  const replacement = page.getByRole("textbox", { name: "Novo texto do snippet", exact: true });
  await trigger.fill("saved phrase");
  await replacement.fill("Saved replacement");
  await page.getByRole("button", { name: "Adicionar snippet", exact: true }).click();
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await page.getByRole("textbox", { name: "Texto do snippet 1", exact: true }).fill("Earlier row revision");
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "save") { started(); await held; }
    await route.fallback();
  });
  try {
    await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
    await entered;
    await trigger.fill("new unsaved phrase");
    await replacement.fill("New text typed during Save");
  } finally { release(); }
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await expect(trigger).toHaveValue("new unsaved phrase");
  await expect(replacement).toHaveValue("New text typed during Save");
  const saved = await page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })).snippets);
  expect(saved).toHaveLength(1);
  expect(saved[0].replacement).toBe("Earlier row revision");
});

test("snippets account: account draft cannot be saved after the session changes", async ({ page }) => {
  await page.getByRole("button", { name: "Snippets", exact: true }).click();
  await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toHaveCount(0);
  await page.getByRole("textbox", { name: "Nova frase de ativação" }).fill("minha assinatura");
  await page.getByRole("textbox", { name: "Novo texto do snippet" }).fill("Account draft");
  await page.getByRole("button", { name: "Adicionar snippet", exact: true }).click();
  await page.evaluate(async () => {
    await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["logout", ""] });
  });
  await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("alert")).toContainText("A conta mudou.");
  await expect(page.getByRole("textbox", { name: "Texto do snippet 1", exact: true })).toHaveValue("Account draft");
});

test("snippets account: composer clears when the session changes before Add", async ({ page }) => {
  await page.getByRole("button", { name: "Snippets", exact: true }).click();
  await page.getByRole("textbox", { name: "Nova frase de ativação" }).fill("private phrase");
  await page.getByRole("textbox", { name: "Novo texto do snippet" }).fill("Private account text");
  await page.evaluate(async () => {
    await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["logout", ""] });
  });
  await expect(page.getByRole("textbox", { name: "Nova frase de ativação" })).toHaveValue("");
  await expect(page.getByRole("textbox", { name: "Novo texto do snippet" })).toHaveValue("");
  await expect(page.getByRole("button", { name: "Adicionar snippet", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.getByRole("textbox", { name: "Nova frase de ativação" }).fill("guest phrase");
  await page.getByRole("textbox", { name: "Novo texto do snippet" }).fill("Guest text");
  await page.getByRole("button", { name: "Adicionar snippet", exact: true }).click();
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("textbox", { name: "Texto do snippet 1", exact: true })).toHaveValue("Guest text");
});

for (const direction of ["sign-in", "sign-out"] as const) {
  test(`snippets account: dictionary composer resets during ${direction}`, async ({ page }) => {
    const account = () => page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })).accountState);
    await expect.poll(async () => (await account()).busy).toBe(false);
    if (direction === "sign-in") {
      await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["logout", ""] }));
      await expect.poll(async () => (await account()).signedIn).toBe(false);
      await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeVisible();
      await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["login", "test@example.test"] }));
      await expect.poll(async () => (await account()).pending).toBe("login");
      await expect.poll(async () => (await account()).busy).toBe(false);
    }
    const action = direction === "sign-in" ? "confirm" : "logout";
    let release!: () => void;
    let started!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const entered = new Promise<void>(resolve => { started = resolve; });
    await page.route("**/__test_rpc", async route => {
      const request = route.request().postDataJSON();
      if (request.method === "accountCommand" && request.args[0] === action) { started(); await held; }
      await route.fallback();
    });
    const term = page.getByRole("textbox", { name: "Novo termo", exact: true });
    try {
      await page.evaluate((nextAction) => {
        (window as any).__accountTransition = (window as any).__TAURI_INTERNALS__.invoke("settings_call", {
          method: "accountCommand", args: [nextAction, nextAction === "confirm" ? "123456" : ""],
        });
      }, action);
      await entered;
      await page.getByRole("button", { name: "Dicionário", exact: true }).click();
      await term.fill("Private previous-owner term");
    } finally { release(); }
    await page.evaluate(() => (window as any).__accountTransition);
    await expect.poll(async () => (await account()).signedIn).toBe(direction === "sign-in");
    await expect(term).toHaveValue("");
    await term.press("Enter");
    await expect(page.getByRole("button", { name: "Adicionar termo", exact: true })).toBeDisabled();
    await expect(page.getByRole("textbox", { name: "Termo 1", exact: true })).toHaveCount(0);
  });
}

for (const library of ["dictionary", "snippets"] as const) {
  test(`snippets account: sync-import keeps local ${library} text and remote additions`, async ({ page }) => {
    const dictionary = library === "dictionary";
    await page.getByRole("button", { name: dictionary ? "Dicionário" : "Snippets", exact: true }).click();
    if (dictionary) {
      await page.getByRole("textbox", { name: "Novo termo", exact: true }).fill("Base term");
      await page.getByRole("button", { name: "Adicionar termo", exact: true }).click();
    } else {
      await page.getByRole("textbox", { name: "Nova frase de ativação", exact: true }).fill("base phrase");
      await page.getByRole("textbox", { name: "Novo texto do snippet", exact: true }).fill("Base replacement");
      await page.getByRole("button", { name: "Adicionar snippet", exact: true }).click();
    }
    await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
    await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
    const edited = page.getByRole("textbox", { name: dictionary ? "Termo 1" : "Texto do snippet 1", exact: true });
    await edited.fill("Local unsaved revision");
    await page.evaluate(() => fetch("/__test_rpc", { method: "POST", body: JSON.stringify({ method: "testArmLibrarySync", args: [] }) }));
    await page.getByRole("switch", { name: dictionary ? "Usar termo 1" : "Usar snippet 1", exact: true }).click();
    const remote = () => page.evaluate(async (key) => {
      const snapshot = await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] });
      return snapshot[key].length;
    }, dictionary ? "dictionaryEntries" : "snippets");
    await expect.poll(remote).toBe(2);
    await expect(edited).toHaveValue("Local unsaved revision");
    await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
    await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
    await page.reload();
    await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
    await page.getByRole("button", { name: dictionary ? "Dicionário" : "Snippets", exact: true }).click();
    await expect(edited).toHaveValue("Local unsaved revision");
    await expect(page.getByRole("textbox", { name: dictionary ? "Termo 2" : "Texto do snippet 2", exact: true })).toHaveValue(dictionary ? "Remote term" : "Remote replacement");
    await expect(page.getByRole("switch", { name: dictionary ? "Usar termo 1" : "Usar snippet 1", exact: true })).not.toBeChecked();
  });
}

test.beforeEach(async ({ page }, testInfo) => {
  if (!process.env.CLARIFY_TEST_PYTHON || !process.env.CLARIFY_TEST_FIXTURE) throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE");
  const onboarding = testInfo.title.startsWith("onboarding:");
  const quota = testInfo.title.startsWith("quota:");
  const signedIn = quota || testInfo.title.startsWith("snippets account:");
  releaseUsage = async () => {
    await page.evaluate(async () => {
      await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["refresh", ""] });
    });
  };
  const locale = /locale (en|es)/.exec(testInfo.title)?.[1] || "pt";
  child = spawn(process.env.CLARIFY_TEST_PYTHON, ["-u", process.env.CLARIFY_TEST_FIXTURE, ...(onboarding ? ["--onboarding"] : []), ...(signedIn ? ["--signed-in"] : []), ...(testInfo.title.includes("social cancellation") ? ["--social-wait"] : []), ...(testInfo.title.includes("sync-import") ? ["--library-sync"] : []), ...(testInfo.title.startsWith("history:") ? ["--history"] : []), ...(testInfo.title.includes("review tools") ? ["--history-review"] : []), ...(testInfo.title.includes("large history") ? ["--history-large"] : []), ...(testInfo.title.includes("failed quota") ? ["--usage-error"] : []), ...["legacy", "malformed", "waiting", "unfunded", "inactive", "paused", "exhausted"].filter(mode => testInfo.title.includes(`quota ${mode}`)).map(mode => `--usage-${mode}`)], { windowsHide: true, env: { ...process.env, CLARIFY_TEST_UI_LANGUAGE: locale } });
  child.stderr.on("data", data => process.stderr.write(data));
  createInterface({ input: child.stdout }).on("line", line => {
    const reply = JSON.parse(line); pending.get(reply.id)?.(reply); pending.delete(reply.id);
  });
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    // Quota tests control refresh explicitly. Automatic refreshes must not
    // race the request that releases the initial empty usage snapshot.
    if (quota && request.method === "accountCommand" && request.args[0] === "auto") {
      request.method = "snapshot"; request.args = [];
    }
    const key = ++id;
    const result = new Promise(resolve => pending.set(key, resolve));
    child.stdin.write(JSON.stringify({ id: key, ...request }) + "\n");
    const reply = await result as { result?: { accountState?: { usage?: Record<string, unknown> } } };
    const usage = reply.result?.accountState?.usage;
    if (usage && testInfo.title.includes("quota reserved")) {
      Object.assign(usage, { used_percent: 100, remaining_percent: 0, reserved_percent: 1, hosted_available: false });
    }
    await route.fulfill({ json: reply });
  });
  await page.addInitScript(() => {
    (window as any).__TAURI_INTERNALS__ = { invoke: async (_command: string, request: unknown) => {
      const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
      const result = await response.json(); if (result.error) throw result.error; return result.result;
    } };
  });
  await page.goto("/");
  // A cold Windows real-controller fixture took 20.28 s. Keep action deadlines unchanged.
  await expect(onboarding ? page.getByRole("heading", { name: locale === "en" ? "Welcome to Clarify" : locale === "es" ? "Te damos la bienvenida a Clarify" : "Boas-vindas ao Clarify" }) : page.getByRole("combobox", { name: locale === "en" ? "Microphone" : locale === "es" ? "Micrófono" : "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
});
test.afterEach(async () => { child?.stdin.end(JSON.stringify({ method: "quit" }) + "\n"); pending.clear(); });

test("history: existing records stay visible and local delete and clear update the list", async ({ page }) => {
  await page.getByRole("button", { name: "Histórico", exact: true }).click();
  await expect(page.getByText("Isolated mobile history.", { exact: true })).toBeVisible();
  await expect(page.getByText("Isolated revised desktop history.", { exact: true })).toBeVisible();
  const items = page.getByRole("listitem");
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText("Mobile");
  await expect(items.last()).toContainText("Desktop");
  await items.first().getByRole("button", { name: "Excluir transcrição", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Excluir", exact: true }).click();
  await expect(items).toHaveCount(1);
  await page.getByRole("button", { name: "Limpar histórico", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Excluir", exact: true }).click();
  await expect(page.getByText("Nenhuma transcrição ainda.", { exact: true })).toBeVisible();
});

test("history: large history loads bounded pages and full legacy text without blocking Settings", async ({ page }) => {
  test.setTimeout(60000);
  await page.getByRole("button", { name: "Histórico", exact: true }).click();
  await expect(page.getByRole("listitem")).toHaveCount(20);
  await page.getByRole("listitem").first().getByRole("button", { name: "Abrir textos", exact: true }).click();
  const reader = page.getByRole("region", { name: "Resultado", exact: true });
  await expect(reader.locator(".history-text")).toHaveText(("Giant legacy " + "x".repeat(1100000)).slice(0, 4000));
  await reader.getByRole("button", { name: "Próximo trecho", exact: true }).click();
  await expect(reader.locator(".history-text")).toHaveText("x".repeat(4000));
  await page.getByRole("button", { name: "Carregar mais", exact: true }).click();
  await expect(page.getByRole("listitem")).toHaveCount(40);
  await page.getByRole("button", { name: "Carregar mais", exact: true }).click();
  await expect(page.getByRole("listitem")).toHaveCount(48);
  await expect(page.getByRole("button", { name: "Carregar mais", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await expect(page.getByText("Salvar histórico", { exact: true })).toBeVisible();
});

test("history: session context changes close a stale delete dialog", async ({ page }) => {
  await page.getByRole("button", { name: "Histórico", exact: true }).click();
  await expect(page.getByRole("listitem")).toHaveCount(2);
  await page.getByRole("button", { name: "Limpar histórico", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.evaluate(() => fetch("/__test_rpc", { method: "POST", body: JSON.stringify({ method: "testHistoryContextChange", args: [] }) }));
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("listitem")).toHaveCount(2);
});

test("history: review tools compare preserved texts and recover from clipboard failure", async ({ page }, testInfo) => {
  await page.getByRole("button", { name: "Histórico", exact: true }).click();
  const revised = page.getByRole("listitem").filter({ hasText: "Isolated revised desktop history." });
  await revised.getByRole("button", { name: "Abrir textos", exact: true }).click();
  await expect(revised.getByRole("region", { name: "Original", exact: true })).toContainText("Isolated desktop history.");
  await expect(revised.getByRole("region", { name: "Resultado", exact: true })).toContainText("Isolated revised desktop history.");
  await page.screenshot({ path: testInfo.outputPath("history-comparison.png"), fullPage: true });
  let fail = true;
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "copyHistoryText" && fail) {
      fail = false; await route.fulfill({ json: { error: "Não foi possível copiar. Tente novamente." } }); return;
    }
    await route.fallback();
  });
  await revised.getByRole("button", { name: "Copiar resultado", exact: true }).click();
  await expect(revised.getByRole("alert")).toContainText("Não foi possível copiar.");
  await revised.getByRole("button", { name: "Copiar resultado", exact: true }).click();
  await expect(revised.getByRole("status")).toHaveText("Copiado.");
  await revised.getByRole("button", { name: "Copiar original", exact: true }).click();
  await expect.poll(() => page.evaluate(async () => (await (await fetch("/__test_rpc", { method: "POST", body: JSON.stringify({ method: "testHistoryClipboard", args: [] }) })).json()).result)).toEqual(["Isolated revised desktop history.", "Isolated desktop history."]);
  const same = page.getByRole("listitem").filter({ hasText: "Isolated mobile history." });
  await same.getByRole("button", { name: "Abrir textos", exact: true }).click();
  await expect(same).toContainText("O original e o resultado são iguais.");
  const absent = page.getByRole("listitem").filter({ hasText: "Result without original." });
  await absent.getByRole("button", { name: "Abrir textos", exact: true }).click();
  await expect(absent).toContainText("O original não está disponível para este registro.");
  await expect(absent.getByRole("button", { name: "Copiar original", exact: true })).toHaveCount(0);
});

test("history: large history search reaches older originals and never reports partial scan as empty", async ({ page }) => {
  await page.getByRole("button", { name: "Histórico", exact: true }).click();
  const queries = ["ISOLATED DESKTOP HISTORY.", "no such text"];
  // Hold each completed RPC before React receives it. This forces the pending
  // continuation state, including the final reply that removes the button.
  await page.evaluate(queries => {
    const runtime = (window as any).__TAURI_INTERNALS__;
    const invoke = runtime.invoke;
    runtime.invoke = async (command: string, request: any) => {
      const result = await invoke(command, request);
      if (request.method === "getHistoryPage" && queries.includes(request.args[2])) {
        await new Promise<void>(resolve => {
          (window as any).__historyScan = { query: request.args[2], cursor: request.args[1], release: resolve };
        });
      }
      return result;
    };
  }, queries);
  const more = page.getByRole("button", { name: "Continuar busca", exact: true });
  const empty = page.getByText("Nenhum resultado encontrado.", { exact: true });
  const scan = async (action: () => Promise<unknown>, query: string, cursor = "") => {
    const response = page.waitForResponse(response => {
      if (!response.url().endsWith("/__test_rpc")) return false;
      const request = response.request().postDataJSON();
      return request.method === "getHistoryPage" && request.args[1] === cursor && request.args[2] === query;
    });
    await action();
    const reply = await (await response).json();
    expect(reply.error).toBeUndefined();
    await page.waitForFunction(({ query, cursor }) => {
      const held = (window as any).__historyScan;
      return held?.query === query && held?.cursor === cursor;
    }, { query, cursor });
    if (cursor) await expect(more).toBeDisabled();
    await expect(empty).toHaveCount(0);
    await page.evaluate(() => {
      const held = (window as any).__historyScan;
      delete (window as any).__historyScan;
      held.release();
    });
    // Decide the next action only after this exact cursor's reply has rendered.
    if (reply.result.hasMore) await expect(more).toBeEnabled();
    else await expect(more).toHaveCount(0);
    await expect(page.getByRole("status", { name: "Carregando…", exact: true })).toHaveCount(0);
    return reply.result as { entries: unknown[]; cursor: string; hasMore: boolean };
  };
  const search = page.getByRole("searchbox", { name: "Buscar no histórico", exact: true });
  await search.fill(queries[0]);
  let result = await scan(() => page.getByRole("button", { name: "Buscar", exact: true }).click(), queries[0]);
  for (let i = 0; i < 20 && result.hasMore && !result.entries.length; i++) {
    result = await scan(() => more.click(), queries[0], result.cursor);
  }
  await expect(page.getByText("Isolated revised desktop history.", { exact: true })).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveCount(1);
  await search.fill(queries[1]);
  result = await scan(() => page.getByRole("button", { name: "Buscar", exact: true }).click(), queries[1]);
  for (let i = 0; i < 20 && result.hasMore; i++) {
    result = await scan(() => more.click(), queries[1], result.cursor);
  }
  await expect(empty).toBeVisible();
});

test("history: cancelled expansion ignores late text and context change closes comparison", async ({ page }) => {
  await page.getByRole("button", { name: "Histórico", exact: true }).click();
  let release!: () => void, started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "getHistoryTextPart") { started(); await held; }
    await route.fallback();
  });
  const row = page.getByRole("listitem").filter({ hasText: "Isolated revised desktop history." });
  await row.getByRole("button", { name: "Abrir textos", exact: true }).click();
  await entered;
  await row.getByRole("button", { name: "Fechar textos", exact: true }).click();
  release();
  await expect(page.locator(".history-comparison")).toHaveCount(0);
  await row.getByRole("button", { name: "Abrir textos", exact: true }).click();
  await expect(row.getByRole("region", { name: "Original", exact: true })).toContainText("Isolated desktop history.");
  await page.evaluate(() => fetch("/__test_rpc", { method: "POST", body: JSON.stringify({ method: "testHistoryContextChange", args: [] }) }));
  await expect(page.locator(".history-comparison")).toHaveCount(0);
});

test("quota: a signed-in startup shows no allowance until the quota arrives", async ({ page }) => {
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "A cota semanal não está disponível." })).toBeVisible();
  await expect(page.getByText("0 de 0 minutos neste mês", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await releaseUsage();
  await expect(page.getByRole("progressbar", { name: "Uso nesta semana" })).toHaveAttribute("aria-valuetext", "12,5% usados · 82,5% restantes");
  await expect(page.getByRole("status").filter({ hasText: "A cota semanal não está disponível." })).toHaveCount(0);
});

test("quota: a failed quota request shows an error and allows a retry", async ({ page }) => {
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
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

for (const mode of ["legacy", "malformed"]) {
  test(`quota: quota ${mode} stays unknown and allows a refresh`, async ({ page }) => {
    await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
    await releaseUsage();
    const retry = page.getByRole("button", { name: "Tentar novamente", exact: true });
    await expect(retry).toBeEnabled();
    await retry.click();
    await expect(retry).toBeEnabled();
    await expect(page.getByRole("status").filter({ hasText: "A cota semanal não está disponível." })).toBeVisible();
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(page.getByText(/minutos neste mês/)).toHaveCount(0);
  });
}
for (const [mode, notice] of [
  ["waiting", "Sua conta aguarda a próxima distribuição de cotas."],
  ["unfunded", "Não há saldo de patrocínio para uma cota neste momento."],
  ["inactive", "O processamento da conta está inativo."],
]) {
  test(`quota: quota ${mode} shows its status without usable credit`, async ({ page }) => {
    await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
    await releaseUsage();
    await expect(page.getByRole("status").filter({ hasText: notice })).toBeVisible();
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(page.getByText(/100%/)).toHaveCount(0);
    await expect(page.getByText(/Próxima renovação:/)).toBeVisible();
  });
}
for (const mode of ["paused", "reserved"]) {
  test(`quota: quota ${mode} keeps percentages and reports processing unavailable`, async ({ page }) => {
    await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
    await releaseUsage();
    await expect(page.getByRole("status").filter({ hasText: "O processamento da conta está indisponível no momento." })).toBeVisible();
    await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuetext", mode === "reserved"
      ? "100% usados · 0% restantes" : "12,5% usados · 82,5% restantes");
    await expect(page.getByText("Você usou toda a sua cota semanal.", { exact: true })).toHaveCount(0);
  });
}

test.describe("weekly reset timezone", () => {
  test.use({ timezoneId: "America/Los_Angeles" });
  for (const labels of [
    { locale: "pt", account: "Conta Clarify", exhausted: "Você usou toda a sua cota semanal.", reset: "Próxima renovação:", percent: "100% usados · 0% restantes" },
    { locale: "en", account: "Clarify account", exhausted: "You have used your weekly quota.", reset: "Next reset:", percent: "100% used · 0% remaining" },
    { locale: "es", account: "Cuenta Clarify", exhausted: "Has agotado tu cuota semanal.", reset: "Próxima renovación:", percent: "100 % usado · 0 % restante" },
  ]) {
    test(`quota: quota exhausted locale ${labels.locale} identifies exhaustion and shows the local reset`, async ({ page }) => {
      await page.getByRole("button", { name: labels.account, exact: true }).click();
      await releaseUsage();
      await expect(page.getByRole("status").filter({ hasText: labels.exhausted })).toHaveText(labels.exhausted);
      await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
      const reset = page.getByText(new RegExp(labels.reset));
      await expect(reset).toContainText(labels.locale === "pt" ? /, (16|17):00 GMT-(7|8)\./ : /(PDT|PST|GMT-[78])/);
      await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuetext", labels.locale === "es" ? /100\s*% usado · 0\s*% restante/ : labels.percent);
    });
  }
  test("quota: reset uses local device time", async ({ page }) => {
    await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
    await releaseUsage();
    await expect(page.getByText(/Próxima renovação:/)).toContainText(/, (16|17):00 GMT-(7|8)\./);
  });
});

test("onboarding: first run shows email and a local link before Settings", async ({ page }) => {
  await expect(page.getByRole("navigation", { name: "Configurações" })).toBeHidden();
  await expect(page.getByText(/300 minutos/)).toHaveCount(0);
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
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
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
  await expect(page.getByText(/Patrocínios financiam uma cota semanal individual/)).toBeVisible();
  await expect(page.getByText(/300 minutos/)).toHaveCount(0);
  await expect(page.getByRole("navigation")).toBeHidden();
  await expect(page.getByRole("button", { name: "Ativar processamento do Clarify" })).toHaveCount(0);
  await page.getByRole("button", { name: "Começar", exact: true }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
  await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeHidden();
  await expect(page.getByRole("button", { name: "Texto", exact: true })).toBeHidden();
  await expect(page.getByRole("combobox", { name: "Serviço", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  const usage = page.getByRole("progressbar", { name: "Uso nesta semana" });
  await expect(usage).toHaveAttribute("aria-valuenow", "12.5");
  await expect(usage).toHaveAttribute("aria-valuetext", "12,5% usados · 82,5% restantes");
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
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(usage).toBeVisible();
  await page.getByRole("button", { name: "Sair da conta", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(usage).toBeVisible();
  await page.getByRole("button", { name: "Sair da conta", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Sair da conta", exact: true }).click();
  await expect(page.getByRole("button", { name: "Texto", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toBeVisible();
});

for (const provider of ["Google", "Microsoft", "GitHub"]) {
  test(`onboarding: social ${provider} signs in without requiring the email form`, async ({ page }) => {
    await expect(page.getByRole("textbox", { name: "E-mail", exact: true })).toHaveValue("");
    await page.getByRole("button", { name: `Continuar com ${provider}`, exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sua conta está pronta" })).toBeVisible();
    await expect(page.getByText(`${provider.toLowerCase()}@example.test`, { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Começar", exact: true }).click();
    await expect(page.getByRole("navigation")).toBeVisible();
  });
}

test("onboarding: social cancellation stays enabled while the browser login is pending", async ({ page }) => {
  await page.getByRole("button", { name: "Continuar com Google", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Conclua o login no navegador");
  const cancel = page.getByRole("button", { name: "Cancelar login", exact: true });
  await expect(cancel).toBeEnabled();
  await cancel.click();
  await expect(page.getByRole("alert")).toContainText("O login foi cancelado.");
  await expect(page.getByRole("button", { name: "Continuar com Google", exact: true })).toBeEnabled();
  await expect(page.getByRole("textbox", { name: "E-mail", exact: true })).toBeVisible();
});

test("onboarding: account social cancellation restores provider actions after local setup", async ({ page }) => {
  await page.getByRole("button", { name: "Continuar sem conta", exact: true }).click();
  await page.getByRole("button", { name: "Continuar e configurar modelo" }).click();
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  await page.getByText("Servidor próprio", { exact: true }).click();
  const server = page.getByRole("textbox", { name: "Endereço do servidor", exact: true });
  const saveServer = page.getByRole("button", { name: "Salvar servidor", exact: true });
  const navigation = page.getByRole("navigation", { name: "Configurações", exact: true });
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
  await expect(page.getByRole("textbox", { name: "E-mail", exact: true })).toBeEnabled();
  await expect(server).toBeEnabled();
  await expect(saveServer).toBeEnabled();
  for (const button of await navigation.getByRole("button").all()) await expect(button).toBeEnabled();
});

test("account social cancellation remains available while navigating with local drafts", async ({ page }) => {
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  await page.getByRole("button", { name: "Continuar com Google", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Conclua o login no navegador" })).toBeVisible();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep my local draft");
  await page.getByRole("button", { name: "Conta Clarify", exact: true }).click();
  const cancel = page.getByRole("button", { name: "Cancelar login", exact: true });
  await expect(cancel).toBeEnabled();
  await cancel.click();
  await expect(page.getByRole("alert")).toContainText("O login foi cancelado.");
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep my local draft");
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
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Atalhos", exact: true }).click();
  await expect(page.locator(".shortcut").first()).toHaveText("Mouse 4");
});

test("cancelled shortcut capture rejects retained keyboard and mouse events", async ({ page }) => {
  await page.getByRole("button", { name: "Atalhos", exact: true }).click();
  const recording = page.locator(".shortcut").first();
  const original = await recording.textContent();
  const changes: unknown[] = [];
  let releaseCancel!: () => void;
  let cancelStarted = false;
  const cancelGate = new Promise<void>(resolve => { releaseCancel = resolve; });
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    if (request.method === "setHotkey" || (request.method === "savePreference" && request.args?.[0] === "setHotkey")) changes.push(request.args);
    if (request.method === "cancelHotkeyCapture") {
      cancelStarted = true;
      await cancelGate;
    }
    await route.fallback();
  });
  const popup = page.locator('[data-slot="dialog-popup"]');
  let finishTransition: (() => Promise<void>) | undefined;
  try {
    await recording.click();
    await expect(popup).not.toHaveAttribute("data-starting-style", "");
    const transition = await popup.evaluateHandle(async element => {
      await Promise.all(element.getAnimations().map(animation => animation.finished));
      // Keep exit completion under test control, even when CSS transitions finish early.
      const held = element.animate([{ outlineOffset: "0px" }, { outlineOffset: "0px" }], { duration: 1 });
      held.pause();
      return held;
    });
    finishTransition = async () => {
      await transition.evaluate(animation => animation.finish());
      await transition.dispose();
    };
    const field = page.getByRole("textbox", { name: "Novo atalho" });
    await field.press("Escape");
    await expect.poll(() => cancelStarted).toBe(true);
    await field.dispatchEvent("keydown", { key: "k", ctrlKey: true });
    releaseCancel();
    const closed = page.locator('[data-slot="dialog-popup"][data-ending-style]');
    await expect(closed).toHaveCount(1);
    // A queued event must not use a handler retained for the closing animation.
    await closed.locator("input").dispatchEvent("mouseup", { button: 3 });
    await page.waitForResponse(response => response.request().postDataJSON()?.method === "poll");
    expect(changes).toEqual([]);
    await expect(recording).toHaveText(original!);
    await expect(closed).toHaveAttribute("inert", "");
    await expect(closed.locator("input")).not.toBeFocused();
    await page.keyboard.press("Control+k");
    await expect(page.locator('[role="dialog"]:not([inert]):not([data-ending-style])')).toHaveCount(0);
  } finally {
    releaseCancel();
    await finishTransition?.();
  }
  await expect(popup).toHaveCount(0);
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
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d")!;
    const rgba = (color: string) => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    const blend = (front: number[], back: number[]) => {
      const alpha = front[3] / 255;
      return front.slice(0, 3).map((channel, index) => channel * alpha + back[index] * (1 - alpha)).concat(255);
    };
    const ancestors: Element[] = [];
    for (let node: Element | null = element; node; node = node.parentElement) ancestors.unshift(node);
    const background = ancestors.reduce((back, node) => blend(rgba(getComputedStyle(node).backgroundColor), back), [255, 255, 255, 255]);
    const placeholder = getComputedStyle(element, "::placeholder");
    const ink = rgba(placeholder.color);
    ink[3] *= Number(placeholder.opacity);
    const luminance = (color: number[]) => {
      const values = color.slice(0, 3).map(value => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      });
      return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
    };
    const foreground = luminance(blend(ink, background));
    const backdrop = luminance(background);
    return (Math.max(foreground, backdrop) + 0.05) / (Math.min(foreground, backdrop) + 0.05);
  });
  expect(contrast).toBeGreaterThanOrEqual(4.5);
});

test("automatic updates persist immediately without a save step", async ({ page }) => {
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  const toggle = page.getByRole("switch", { name: "Atualização automática", exact: true });
  await expect(toggle).not.toBeChecked();
  const saved = page.waitForResponse(response => response.url().endsWith("/__test_rpc") && response.request().postDataJSON()?.method === "savePreference");
  await toggle.click(); await saved;
  await expect(toggle).toBeChecked();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Geral", exact: true }).click();
  await expect(toggle).toBeChecked();
  await expect(page.getByRole("button", { name: "Verificar atualizações" })).toBeDisabled();
  await page.setViewportSize({ width: 640, height: 520 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
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
  const history = page.getByRole("switch", { name: "Salvar histórico", exact: true });
  await history.click();
  await expect(history).toBeChecked();
  await page.getByRole("spinbutton", { name: "Retenção do histórico", exact: true }).fill("31");
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

test("text actions stay with the form and choices need no save island", async ({ page }) => {
  const actions = page.getByRole("group", { name: "Alterações pendentes" });
  await expect(actions).toBeHidden();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  const before = await page.locator(".scroll-area").boundingBox();
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Contextual text draft.");
  await expect(actions).toBeVisible();
  expect(await actions.evaluate(element => !!element.closest(".page"))).toBe(true);
  expect(await page.locator(".scroll-area").boundingBox()).toEqual(before);
  await actions.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(actions).toBeHidden();
  await expect(page.locator(".floating-save")).toHaveCount(0);
});

test("installed models: keyboard selection persists without save and survives reload", async ({ page }) => {
  await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
  await page.getByRole("option", { name: "Local Whisper" }).click();
  await page.getByRole("combobox", { name: "Modelo", exact: true }).click();
  await page.getByPlaceholder("Buscar modelo…").fill("Medium");
  await expect(page.getByRole("option")).toHaveCount(1);
  const saved = page.waitForResponse(response => response.url().endsWith("/__test_rpc") && response.request().postDataJSON()?.method === "savePreference" && response.request().postDataJSON()?.args?.[0] === "setRouteModelId");
  await page.getByPlaceholder("Buscar modelo…").press("Enter"); await saved;
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("Medium");
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("Medium");
});

test("picker resets search when reopened before its closing animation ends", async ({ page }) => {
  await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
  await page.getByRole("option", { name: "Local Whisper" }).click();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCount(0);
  // Keep the exiting popup mounted to reproduce rapid reopening deterministically.
  await page.addStyleTag({ content: '[data-slot="combobox-popup"][data-ending-style] { transition-duration: 30s; }' });
  const model = page.getByRole("combobox", { name: "Modelo", exact: true });
  const search = page.getByPlaceholder("Buscar modelo…");
  await model.click();
  await search.fill("Medium");
  await expect(page.getByRole("option")).toHaveCount(1);
  await search.press("Enter");
  await expect(page.locator('[data-slot="combobox-popup"][data-ending-style]')).toHaveCount(1);
  await model.click();
  await expect(search).toHaveValue("");
  await expect(page.getByRole("option", { name: /Whisper Base/ })).toBeVisible();
  await search.fill("Medium");
  await search.press("Escape");
  await expect(page.locator('[data-slot="combobox-popup"][data-ending-style]')).toHaveCount(1);
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
  await page.getByRole("spinbutton", { name: "Retenção do histórico" }).fill("31");
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
    for (const name of ["Ditado", "Geral", "Texto", "Atalhos", "Modelos e serviços", "Dicionário", "Snippets", "Histórico", "Conta Clarify"]) {
      await page.getByRole("button", { name, exact: true }).click();
      await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
      await expect(page.locator(".page")).toBeEnabled();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`${width}-${name}.png`), animations: "disabled" });
    }
  }
});

test("navigation preserves the page container, brightness and horizontal geometry", async ({ page }) => {
  await expect(page.locator(".page")).toBeVisible();
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
    await expect(page.locator(".page")).toBeVisible();
  }
  for (const name of ["Reescrita", "Tradução", "Revisão"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".page")).toBeVisible();
  }
  const frames = await page.evaluate(() => {
    (window as any).__sampling = false;
    return (window as any).__navFrames as { opacity: string; same: boolean; width: number; animation: string }[];
  });
  expect(frames.length).toBeGreaterThan(5);
  expect(frames.filter(f => !f.same || f.opacity !== "1" || f.animation !== "none")).toEqual([]);
  expect(new Set(frames.map(f => f.width)).size).toBe(1);
});

test("sidebar width follows the desktop window breakpoints", async ({ page }) => {
  for (const [width, expected] of [[1040, 220], [820, 208], [640, 60]]) {
    await page.setViewportSize({ width, height: 740 });
    await expect.poll(() => page.locator("aside").evaluate(element => element.getBoundingClientRect().width)).toBe(expected);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await expect(page.getByRole("button", { name: "Fechar configurações", exact: true })).toBeInViewport();
  }
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
    await expect(email).toBeEnabled();
    const first = await email.locator("xpath=..").boundingBox(), submit = await next.boundingBox();
    expect(first).not.toBeNull(); expect(submit).not.toBeNull();
    expect(Math.abs(first!.x - submit!.x)).toBeLessThan(1);
    expect(Math.abs(first!.width - submit!.width)).toBeLessThan(1);
    await email.locator("xpath=..").click({ position: { x: first!.width / 2, y: first!.height - 3 } });
    await expect(email).toBeFocused();
    await email.fill("test@example.test"); await next.click();
    const code = page.getByRole("textbox", { name: labels.code, exact: true });
    await expect(code).toBeVisible();
    await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeHidden();
    await expect(code).toBeEnabled();
    const verify = await code.locator("xpath=..").boundingBox();
    const confirm = await page.getByRole("button", { name: labels.confirm, exact: true }).boundingBox();
    expect(Math.abs(verify!.x - confirm!.x)).toBeLessThan(1);
    expect(Math.abs(verify!.width - confirm!.width)).toBeLessThan(1);
    await code.locator("xpath=..").click({ position: { x: verify!.width / 2, y: verify!.height - 3 } });
    await expect(code).toBeFocused();
    await page.getByRole("button", { name: labels.back, exact: true }).click();
    await expect(email).toBeVisible();
    await expect(page.getByRole("button", { name: labels.skip, exact: true })).toBeVisible();
  });
}

test("sidebar navigation retains text drafts without a global search", async ({ page }) => {
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep this draft through navigation.");
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this draft through navigation.");
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("textbox", { name: "Instruções", exact: true }).focus();
  await page.keyboard.press("Control+End"); await page.keyboard.press("/");
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this draft through navigation./");
});

test("snippets account: sidebar excludes personal processing controls", async ({ page }) => {
  await expect(page.getByRole("navigation").getByRole("button")).toHaveCount(7);
  await expect(page.getByRole("button", { name: "Modelos e serviços", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Texto", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Histórico", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Histórico", exact: true })).toBeVisible();
});

test("settings updates: pending telemetry does not leave local navigation busy", async ({ page }) => {
  let releasePoll!: () => void;
  let enteredPoll!: () => void;
  const held = new Promise<void>(resolve => { releasePoll = resolve; });
  const entered = new Promise<void>(resolve => { enteredPoll = resolve; });
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "poll") {
      enteredPoll();
      await held;
    }
    await route.fallback();
  });
  try {
    await entered;
    await page.getByRole("button", { name: "Dicionário", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Novo termo", exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Ditado", exact: true })).toBeEnabled();
  } finally {
    releasePoll();
  }
});

test("settings updates: microphone telemetry stays compact with a full snippet library", async ({ page }) => {
  await page.evaluate(async () => {
    const entries = Array.from({ length: 512 }, (_, index) => ({
      trigger: `isolated phrase ${index}`,
      replacement: "x".repeat(4096),
      enabled: true,
      case_sensitive: false,
    }));
    await (window as any).__TAURI_INTERNALS__.invoke("settings_call", {
      method: "setSnippets", args: [entries, "local"],
    });
  });
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep this draft during live telemetry.");
  await page.getByRole("button", { name: "Ditado", exact: true }).click();
  const telemetry: { bytes: number; level: number | undefined }[] = [];
  page.on("response", async response => {
    if (!response.url().endsWith("/__test_rpc")) return;
    const method = response.request().postDataJSON()?.method;
    if (method !== "snapshot" && method !== "poll") return;
    try {
      const body = await response.text();
      telemetry.push({ bytes: body.length, level: JSON.parse(body).result?.microphoneTestLevel });
    } catch { /* A response may finish after the page closes. */ }
  });
  await page.getByRole("button", { name: "Testar microfone", exact: true }).click();
  await expect(page.getByRole("button", { name: "Parar teste", exact: true })).toBeVisible();
  await expect.poll(() => telemetry.filter(sample => sample.bytes < 4096 && Number(sample.level) > 0).length).toBeGreaterThanOrEqual(3);
  await page.getByRole("button", { name: "Parar teste", exact: true }).click();
  await expect(page.getByRole("button", { name: "Testar microfone", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this draft during live telemetry.");
});


test("repeated menus and dialogs return focus without retaining a modal lock", async ({ page }) => {
  const provider = page.getByRole("combobox", { name: "Serviço", exact: true });
  for (let cycle = 0; cycle < 8; cycle++) {
    await provider.click();
    const search = page.getByPlaceholder("Buscar serviço…");
    await search.fill("no such provider");
    await expect(page.getByRole("option")).toHaveCount(0);
    await search.press("Escape");
    await expect(provider).toBeFocused();
  }
  await page.getByRole("button", { name: "Texto", exact: true }).click();
  const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
  const original = await prompt.inputValue();
  await prompt.fill("Repeated dialog draft.");
  const discard = page.getByRole("group", { name: "Alterações pendentes" }).getByRole("button", { name: "Descartar", exact: true });
  for (let cycle = 0; cycle < 8; cycle++) {
    await discard.click();
    const dialog = page.getByRole("dialog", { name: "Alterações não salvas", exact: true });
    await expect(dialog).toBeVisible(); await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0); await expect(discard).toBeFocused();
  }
  await discard.click();
  await page.getByRole("dialog", { name: "Alterações não salvas", exact: true }).getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(prompt).toHaveValue(original);
  await expect(page.getByRole("group", { name: "Alterações pendentes" })).toBeHidden();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
