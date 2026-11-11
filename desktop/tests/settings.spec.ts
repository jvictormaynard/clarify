import type { Page } from "@playwright/test";
import { test, expect, settingsScenario } from "./settings-fixture";
import { navigate, openSettings, closeSettings, openStyleReview, settingsDialog, openDisclosure, settingsSectionLabel } from "./settings-navigation";

for (const method of ["testMicrophone", "stopMicrophoneTest", "refreshMicrophones"] as const) {
  test(`responsive operations: ${method} keeps navigation and unrelated controls stable`, async ({ page }) => {
    await navigate(page, "Ditado");
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
    const navigation = settingsDialog(page).getByRole("button", { name: "Geral", exact: true });
    const before = await navigation.evaluate(element => getComputedStyle(element).opacity);
    try {
      if (method === "refreshMicrophones") {
        await page.getByRole("combobox", { name: "Microfone", exact: true }).click();
        await page.getByRole("button", { name: "Atualizar microfone", exact: true }).click();
      } else {
        await page.getByRole("button", { name: method === "testMicrophone" ? "Testar microfone" : "Parar teste", exact: true }).click();
      }
      await entered;
      if (method === "refreshMicrophones" && await page.getByRole("combobox", { name: "Microfone", exact: true }).getAttribute("aria-expanded") === "true") await page.keyboard.press("Escape");
      await expect(navigation).toBeEnabled();
      await expect(navigation).toHaveCSS("opacity", before);
      await expect(page.getByRole("combobox", { name: "Serviço", exact: true })).toBeEnabled();
      await navigation.click();
      await expect(settingsDialog(page).getByRole("heading", { name: "Geral", exact: true })).toBeVisible();
      await expect(page.getByRole("combobox", { name: "Idioma", exact: true })).toBeEnabled();
    } finally { release(); }
  });
}

test("responsive operations: saving text allows navigation and preserves edits typed during the save", async ({ page }) => {
  await openStyleReview(page);
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
    await navigate(page, "Dicionário");
    await expect(page.getByRole("button", { name: "Adicionar novo", exact: true })).toBeVisible();
  } finally { release(); }
  await openStyleReview(page);
  await expect(prompt).toHaveValue("Newer unsaved revision.");
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeVisible();
});

test("contextual actions wait for the requested workflow before saving", async ({ page }) => {
  await navigate(page, "Ditado");
  await page.getByText("Instruções da transcrição", { exact: true }).click();
  await page.getByRole("textbox", { name: "Instruções da transcrição", exact: true }).fill("Dictation draft");
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await openStyleReview(page);
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
    await navigate(page, "Ditado");
    await entered;
    await expect(page.getByRole("heading", { name: "Geral", exact: true })).toBeVisible();
    await expect(page.getByRole("group", { name: "Alterações pendentes", exact: true })).toHaveCount(0);
    await expect(settingsDialog(page).getByRole("button", { name: "Geral", exact: true })).toBeEnabled();
  } finally { release(); }
  await page.getByText("Instruções da transcrição", { exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Instruções da transcrição", exact: true })).toHaveValue("Dictation draft");
  await page.getByRole("textbox", { name: "Instruções da transcrição", exact: true }).fill("Updated dictation draft");
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await openStyleReview(page);
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Text draft");
  const snapshot = await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
  expect(snapshot.routePrompt).not.toBe("Text draft");
});

test("automatic preferences: switches persist without committing a pending prompt", async ({ page }) => {
  await openStyleReview(page);
  const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
  const original = await prompt.inputValue();
  const originalScope = await page.evaluate(async () => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }).then((state: any) => state.selectedScope));
  await prompt.fill("Text draft must stay private until Save.");
  await navigate(page, "Sistema");
  const setting = page.getByRole("switch", { name: "Iniciar com o Windows", exact: true });
  const checked = await setting.isChecked();
  const response = page.waitForResponse(response => response.url().endsWith("/__test_rpc") && response.request().postDataJSON().method === "savePreference");
  await setting.click();
  await response;
  const persisted = await page.evaluate(async scope => {
    const invoke = (method: string, args: unknown[]) => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method, args });
    await invoke("selectWorkflow", [scope]);
    return invoke("load", []);
  }, originalScope);
  expect(persisted.autostart).toBe(!checked);
  expect(persisted.routePrompt).toBe(original);
  await openStyleReview(page);
  await expect(prompt).toHaveValue("Text draft must stay private until Save.");
});

test("desktop navigation: Settings sections retain keyboard navigation at every width", async ({ page }, testInfo) => {
  for (const width of [1040, 820, 640]) {
    await page.setViewportSize({ width, height: 740 });
    const dialog = await openSettings(page, "Geral");
    const navigation = dialog.getByRole("navigation");
    await expect(navigation.getByRole("combobox")).toHaveCount(0);
    await expect(navigation.getByRole("button")).toHaveText([
      "Geral", "Sistema", "Dispositivos", "Modelos e serviços", "Dados e privacidade", "Conta", "Sobre",
    ]);
    await navigation.getByRole("button", { name: "Sistema", exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(navigation.getByRole("button", { name: "Dispositivos", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(navigation.getByRole("button", { name: "Modelos e serviços", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(dialog.getByRole("heading", { level: 2, name: "Modelos e serviços", exact: true })).toBeVisible();
    await expect(navigation.getByRole("button", { name: "Conta", exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ path: testInfo.outputPath(`navigation-${width}.png`) });
    await closeSettings(page);
  }
  await expect(page.locator(".floating-save")).toHaveCount(0);
});

test("desktop navigation: global search shortcuts are not intercepted", async ({ page }) => {
  await closeSettings(page);
  await page.evaluate(() => {
    (window as any).__shortcutEvents = [];
    window.addEventListener("keydown", event => {
      if (event.key === "/" || event.key.toLowerCase() === "f") {
        (window as any).__shortcutEvents.push({ key: event.key, prevented: event.defaultPrevented });
      }
    });
  });
  await page.getByRole("navigation").getByRole("button", { name: "Início", exact: true }).focus();
  await page.keyboard.press("/");
  await page.keyboard.press("Control+f");
  expect(await page.evaluate(() => (window as any).__shortcutEvents)).toEqual([
    { key: "/", prevented: false }, { key: "f", prevented: false },
  ]);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("settings organization: tasks and action editors replace workflow destinations", async ({ page }) => {
  await closeSettings(page);
  const navigation = page.locator("aside nav");
  expect(await navigation.getByRole("button").evaluateAll(buttons => buttons.map(button => button.getAttribute("aria-label")))).toEqual([
    "Início", "Dicionário", "Snippets", "Estilo", "Ações", "Configurações",
  ]);
  await openSettings(page, "Ditado");
  await expect(page.getByRole("combobox", { name: "Modo de gravação", exact: true })).toBeVisible();
  const settings = await openSettings(page, "Atalhos");
  await expect(settings.getByRole("combobox", { name: "Modo de gravação", exact: true })).toBeVisible();
  const actionShortcuts = settings.locator("section").filter({ has: page.getByRole("heading", { name: "Atalhos das ações", exact: true }) });
  for (const name of ["Reescrita", "Tradução"]) {
    await actionShortcuts.locator('[data-slot="settings-row"]').filter({ hasText: name }).getByRole("button").click();
    const editor = page.getByRole("dialog", { name: "Editar ação", exact: true });
    await expect(editor.getByRole("textbox", { name: "Nome da ação", exact: true })).toHaveValue(name);
    await expect(editor.getByRole("textbox", { name: "Instruções da ação", exact: true })).toBeVisible();
    await editor.getByRole("button", { name: "Concluído", exact: true }).click();
  }
  await navigate(page, "Ditado");
  await expect(page.getByRole("combobox", { name: "Modo de gravação", exact: true })).toBeVisible();
});

test("settings organization: action Save and Cancel preserve unrelated Style drafts", async ({ page }) => {
  await openStyleReview(page);
  const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
  await prompt.fill("Pending Style instructions");
  await navigate(page, "Ações");
  for (const [id, name] of [["rewrite", "Reescrita"], ["translation", "Tradução"]]) {
    await page.locator(`#text-action-${id}`).getByRole("button", { name: "Editar ação", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "Editar ação", exact: true });
    const instructions = editor.getByRole("textbox", { name: "Instruções da ação", exact: true });
    const original = await instructions.inputValue();
    await instructions.fill(`Cancelled ${name}`);
    await editor.getByRole("button", { name: "Cancelar", exact: true }).click();
    await page.locator(`#text-action-${id}`).getByRole("button", { name: "Editar ação", exact: true }).click();
    await expect(instructions).toHaveValue(original);
    await instructions.fill(`Saved ${name}`);
    await editor.getByRole("button", { name: "Salvar ação", exact: true }).click();
    await expect(editor.getByRole("button", { name: "Salvar ação", exact: true })).toBeDisabled();
    await editor.getByRole("button", { name: "Concluído", exact: true }).click();
  }
  await openStyleReview(page);
  await expect(prompt).toHaveValue("Pending Style instructions");
  const state = await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
  expect(state.routePrompt).not.toBe("Pending Style instructions");
  for (const id of ["rewrite", "translation"]) expect(state.textActions.find((action: any) => action.id === id).prompt).toMatch(/^Saved /);
  });

  test("settings organization: service setup precedes local options and an installed model can be used directly", async ({ page }) => {
    await navigate(page, "Modelos e serviços");
    const cloud = await page.getByRole("heading", { name: /^Serviços na nuvem/ }).boundingBox();
    const local = await page.getByRole("heading", { name: /^Modelos locais/ }).boundingBox();
    expect(cloud!.y).toBeLessThan(local!.y);
    await expect(page.getByRole("button", { name: "Usar este modelo", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Usar este modelo", exact: true }).click();
    await expect(settingsDialog(page).getByRole("heading", { level: 2, name: "Geral", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Serviço", exact: true })).toContainText("Local Whisper");
    await navigate(page, "Modelos e serviços");
    const activeLocal = await page.getByRole("heading", { name: /^Modelos locais/ }).boundingBox();
    const otherCloud = await page.getByRole("heading", { name: /^Serviços na nuvem/ }).boundingBox();
    expect(activeLocal!.y).toBeLessThan(otherCloud!.y);
  });

  test("settings organization: local cleanup setup opens and activates the local review context", async ({ page }) => {
    await navigate(page, "Ditado");
    await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
    await page.getByRole("option", { name: "Local Whisper", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "Serviço", exact: true })).toContainText("Local Whisper");
    await openStyleReview(page);
    await expect(page.getByRole("combobox", { name: "Contexto da revisão", exact: true })).toContainText("Transcrição local");
    const localReview = page.getByRole("switch", { name: "Ativar revisão por IA", exact: true });
    if (await localReview.isChecked()) await localReview.click();
    await expect(localReview).not.toBeChecked();
    await page.getByRole("combobox", { name: "Edição do texto", exact: true }).click();
    await page.getByRole("option", { name: "Melhorar a clareza", exact: true }).click();
    await page.getByRole("button", { name: "Configurar revisão", exact: true }).click();
    await openStyleReview(page);
    await expect(page.getByRole("combobox", { name: "Contexto da revisão", exact: true })).toContainText("Transcrição local");
    await localReview.click();
    await expect(localReview).toBeChecked();
    await navigate(page, "Ditado");
    await openStyleReview(page);
    await expect(localReview).toBeChecked();
    await expect(page.getByRole("combobox", { name: "Edição do texto", exact: true })).toContainText("Melhorar a clareza");
    await expect(page.getByRole("button", { name: "Configurar revisão", exact: true })).toHaveCount(0);
  });

  test("contextual confirmation: Settings Save keeps drafts from other pages unsaved", async ({ page }) => {
    await openStyleReview(page);
    const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
    const original = await prompt.inputValue();
    await prompt.fill("Keep this text draft unsaved.");
    const dialog = await openSettings(page, "Privacidade");
    const history = dialog.getByRole("switch", { name: "Salvar histórico", exact: true });
    if (!await history.isChecked()) await history.click();
    await expect(history).toBeChecked();
    await dialog.getByRole("spinbutton", { name: "Retenção do histórico", exact: true }).fill("31");
    await dialog.getByRole("button", { name: "Fechar", exact: true }).click();
    await expect(dialog.getByRole("status").filter({ hasText: "Há alterações não salvas" })).toBeVisible();
    await dialog.getByRole("button", { name: "Salvar alterações", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(prompt).toHaveValue("Keep this text draft unsaved.");
    await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeVisible();
    await page.reload(); await openStyleReview(page);
    await expect(prompt).toHaveValue(original);
    const reopened = await openSettings(page, "Privacidade");
    await expect(reopened.getByRole("spinbutton", { name: "Retenção do histórico", exact: true })).toHaveValue("31");
  });

  test("responsive account: pending microphone work does not disable sign-in", async ({ page }) => {
    await navigate(page, "Ditado");
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
    await navigate(page, "Conta Clarify");
    await page.getByRole("button", { name: "Continuar com e-mail", exact: true }).click();
    await page.getByRole("textbox", { name: "E-mail", exact: true }).fill("test@example.test");
    await expect(page.getByRole("button", { name: "Continuar", exact: true })).toBeEnabled();
  } finally { release(); }
});

test("provider selection: pending selection cannot transfer a key typed for the visible provider", async ({ page }) => {
  await navigate(page, "Modelos e serviços");
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
    await expect(settingsDialog(page).getByRole("button", { name: "Geral", exact: true })).toBeEnabled();
    // Either bind edits to the displayed provider or guard these inputs during selection.
    if (await key.isEnabled()) await key.fill("sk_test_only_visible_provider");
  } finally { release(); }
  await expect(provider).toContainText("OpenAI");
  await expect(key).toBeEnabled();
  await expect(key).toHaveValue("");
});



test("practice preserves drafts and permits the window close confirmation", async ({ page }) => {
  await openStyleReview(page);
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep this draft through practice.");
  await navigate(page, "Geral");
  await page.getByRole("button", { name: "Praticar ditado", exact: true }).click();
  await page.getByRole("button", { name: "Fechar janela", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Alterações não salvas", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Continuar editando", exact: true }).click();
  await page.getByRole("button", { name: "Pular prática", exact: true }).click();
  await expect(settingsDialog(page)).toBeVisible();
  await openStyleReview(page);
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this draft through practice.");
});

test("modifier and side mouse shortcuts can be captured and saved", async ({ page }) => {
  await navigate(page, "Atalhos");
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
  await expect(page.getByRole("dialog", { name: "Definir atalho", exact: true })).toBeVisible();
  await field.dispatchEvent("mousedown", { button: 3, buttons: 8 });
  await expect(page.getByRole("dialog", { name: "Definir atalho", exact: true })).toBeVisible();
  await field.dispatchEvent("mouseup", { button: 3 });
  await expect(recording).toHaveText("Mouse 4");
  await recording.click();
  await page.getByRole("textbox", { name: "Novo atalho" }).press("Escape");
  await expect(page.getByRole("dialog", { name: "Definir atalho", exact: true })).toBeHidden();
  await expect.poll(captureAction).toBe("");
  await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible({ timeout: 30000 });
  await navigate(page, "Atalhos");
  await expect(page.locator(".shortcut").first()).toHaveText("Mouse 4");
});

test("cancelled shortcut capture rejects retained keyboard and mouse events", async ({ page }) => {
  await navigate(page, "Atalhos");
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
  const popup = page.getByRole("dialog", { name: "Definir atalho", exact: true });
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
    await expect(page.getByRole("dialog", { name: "Definir atalho", exact: true })
      .and(page.locator(":not([inert]):not([data-ending-style])"))).toHaveCount(0);
  } finally {
    releaseCancel();
    await finishTransition?.();
  }
  await expect(popup).toHaveCount(0);
});

test("editable fields expose their guidance to assistive technology", async ({ page }) => {
  await navigate(page, "Privacidade");
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
  await openStyleReview(page);
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
  await navigate(page, "Sistema");
  const toggle = page.getByRole("switch", { name: "Atualização automática", exact: true });
  await expect(toggle).not.toBeChecked();
  const saved = page.waitForResponse(response => response.url().endsWith("/__test_rpc") && response.request().postDataJSON()?.method === "savePreference");
  await toggle.click(); await saved;
  await expect(toggle).toBeChecked();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible({ timeout: 30000 });
  await navigate(page, "Sistema");
  await expect(toggle).toBeChecked();
  await expect(page.getByRole("button", { name: "Verificar atualizações" })).toBeDisabled();
  await page.setViewportSize({ width: 640, height: 520 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
});


test("integrated titlebar stays compact and close preserves unsaved changes", async ({ page }) => {
  await expect(page.locator(".sidebar-brand")).toContainText("Clarify");
  await expect(page.locator(".sidebar-brand img")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Minimizar", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Maximizar", exact: true })).toBeVisible();
  expect(await page.locator(".titlebar").evaluate(el => getComputedStyle(el).backgroundColor)).toBe(await page.locator(".settings-window").evaluate(el => getComputedStyle(el).backgroundColor));
  await openStyleReview(page);
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Titlebar close draft");
  await page.getByRole("button", { name: "Fechar janela", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Alterações não salvas" })).toBeVisible();
  await page.getByRole("button", { name: "Continuar editando" }).click();
  await page.screenshot({ path: "test-results/settings-titlebar.png" });
  await page.setViewportSize({ width: 640, height: 520 });
  await expect(page.getByRole("button", { name: "Fechar janela", exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
  await page.screenshot({ path: "test-results/settings-titlebar-compact.png" });
});

test("page context stays in the header while tasks and Settings sections scroll", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.setViewportSize({ width: 640, height: 520 });
  for (const name of ["Início", "Estilo", "Ações", "Dicionário", "Snippets"]) {
      await navigate(page, name);
      const heading = page.getByRole("heading", { level: 1, name: name === "Início" ? "Bem-vindo de volta" : name, exact: true });
      const scroll = page.locator(".scroll-area");
      await expect(heading).toBeVisible();
      expect(await heading.evaluate(el => !!el.closest(".scroll-area"))).toBe(true);
      const context = page.locator("aside nav").getByRole("button", { name, exact: true });
      await expect(context).toHaveAttribute("aria-current", "page");
      const top = (await context.boundingBox())!.y;
      await scroll.evaluate(el => { el.scrollTop = 100; });
      expect((await context.boundingBox())!.y).toBe(top);
      await expect(page.getByRole("button", { name: "Fechar janela", exact: true })).toBeInViewport();
    }

  for (const name of ["Ditado", "Geral", "Modelos e serviços", "Atalhos", "Privacidade", "Conta Clarify"]) {
      const dialog = await openSettings(page, name);
      await expect(dialog.getByRole("heading", { level: 2, name: settingsSectionLabel(name), exact: true })).toBeVisible();
      await expect(dialog).not.toHaveAttribute("data-starting-style");
      await expect.poll(() => dialog.evaluate(element => element.getAnimations().filter(animation => animation.playState === "running").length)).toBe(0);
      const navigation = dialog.getByRole("navigation");
      const before = await navigation.boundingBox();
      await dialog.locator(".settings-dialog-content").evaluate(el => { el.scrollTop = 300; });
      expect(await navigation.boundingBox()).toEqual(before);
      await expect(dialog.getByRole("button", { name: "Fechar", exact: true })).toBeInViewport();
    }

  expect(consoleErrors).toEqual([]);
});

test("scroll boundaries cannot move the window chrome or sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 520 });
  await openStyleReview(page);
  const area = page.locator(".scroll-area");
  const titlebar = page.locator(".titlebar");
  const nav = page.locator("#desktop-sidebar");
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
    await expect(page.getByRole("button", { name: "Fechar janela", exact: true })).toBeInViewport();
  }
  await titlebar.hover();
  await page.mouse.wheel(0, -1500);
  expect(await titlebar.boundingBox()).toEqual(before.titlebar);
});

test("text actions stay with the form and choices need no save island", async ({ page }) => {
  const actions = page.getByRole("group", { name: "Alterações pendentes" });
  await expect(actions).toBeHidden();
  await openStyleReview(page);
  const before = await page.locator(".scroll-area").boundingBox();
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Contextual text draft.");
  const editor = page.getByRole("textbox", { name: "Instruções", exact: true });
  const shell = await editor.locator("..").boundingBox();
  const panel = await editor.locator("xpath=ancestor::*[@data-slot='settings-group'][1]").boundingBox();
  expect(shell!.x).toBeGreaterThanOrEqual(panel!.x);
  expect(shell!.x + shell!.width).toBeLessThanOrEqual(panel!.x + panel!.width);
  await expect(actions).toBeVisible();
  expect(await actions.evaluate(element => !!element.closest(".page"))).toBe(true);
  expect(await page.locator(".scroll-area").boundingBox()).toEqual(before);
  await actions.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(actions).toBeHidden();
  await expect(page.locator(".floating-save")).toHaveCount(0);
});

test("installed models: keyboard selection persists without save and survives reload", async ({ page }) => {
  await navigate(page, "Ditado");
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
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible({ timeout: 30000 });
  await navigate(page, "Ditado");
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("Medium");
});

test("picker resets search when reopened before its closing animation ends", async ({ page }) => {
  await navigate(page, "Ditado");
  await page.getByRole("combobox", { name: "Serviço", exact: true }).click();
  await page.getByRole("option", { name: "Local Whisper" }).click();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCount(0);
  // Lengthen only the exit; the race starts after the opening fade finishes.
  await page.addStyleTag({ content: '[data-slot="combobox-popup"][data-ending-style] { transition: opacity 30s; opacity: 0; }' });
  const model = page.getByRole("combobox", { name: "Modelo", exact: true });
  const search = page.getByPlaceholder("Buscar modelo…");
  await model.click();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCSS("opacity", "1");
  await search.fill("Medium");
  await expect(page.getByRole("option")).toHaveCount(1);
  await search.press("Enter");
  await expect(page.locator('[data-slot="combobox-popup"][data-ending-style]')).toHaveCount(1);
  await model.click();
  await expect(search).toHaveValue("");
  await expect(page.getByRole("option", { name: /Whisper Base/ })).toBeVisible();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCSS("opacity", "1");
  await search.fill("Medium");
  await search.press("Escape");
  await expect(page.locator('[data-slot="combobox-popup"][data-ending-style]')).toHaveCount(1);
  await model.click();
  await expect(search).toHaveValue("");
  await page.getByRole("option", { name: /Whisper Base/ }).click();
  await expect(model).toContainText("Base");
});

test("draft prompt survives navigation; invalid retention cannot save", async ({ page }, testInfo) => {
  await openStyleReview(page);
  await page.getByRole("textbox", { name: "Instruções" }).fill("Preserve every detail.");
  await navigate(page, "Privacidade");
  await page.getByRole("switch", { name: "Salvar histórico" }).click();
  await expect(page.getByRole("switch", { name: "Salvar histórico" })).toBeChecked();
  await page.getByRole("spinbutton", { name: "Retenção do histórico" }).fill("-1");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(settingsDialog(page).getByRole("alert")).toContainText("3650");
  await page.getByRole("spinbutton", { name: "Retenção do histórico" }).fill("31");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await openStyleReview(page);
  await expect(page.getByRole("textbox", { name: "Instruções" })).toHaveValue("Preserve every detail.");
  await page.getByRole("button", { name: "Salvar alterações", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("settings-text-draft.png"), animations: "disabled" });
});

test("microphone preview stops on navigation and all pages fit", async ({ page }, testInfo) => {
  await navigate(page, "Ditado");
  await page.getByRole("button", { name: "Testar microfone" }).click();
  await expect(page.getByRole("button", { name: "Parar teste" })).toBeVisible();
  await navigate(page, "Sistema"); await navigate(page, "Ditado");
  await expect(page.getByRole("button", { name: "Testar microfone" })).toBeVisible();
  for (const width of [640, 820, 1040]) {
      await page.setViewportSize({ width, height: 760 });
      for (const name of ["Ditado", "Estilo", "Ações", "Dicionário", "Snippets", "Início", "Geral", "Atalhos", "Modelos e serviços", "Privacidade", "Conta Clarify"]) {
            await navigate(page, name);
            const inSettings = await settingsDialog(page).isVisible();
            await expect((inSettings ? settingsDialog(page) : page).getByRole("heading", { level: inSettings ? 2 : 1, name: inSettings ? settingsSectionLabel(name) : name === "Início" ? "Bem-vindo de volta" : name, exact: true })).toBeVisible();
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
            if (inSettings) {
              const bounds = (await settingsDialog(page).boundingBox())!;
              expect(bounds.x).toBeGreaterThanOrEqual(0); expect(bounds.y).toBeGreaterThanOrEqual(0);
              expect(bounds.x + bounds.width).toBeLessThanOrEqual(width); expect(bounds.y + bounds.height).toBeLessThanOrEqual(760);
            }
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
  for (const name of ["Estilo", "Dicionário", "Snippets", "Início", "Estilo"]) {
      await navigate(page, name);
      await expect(page.getByRole("heading", { level: 1, name: name === "Início" ? "Bem-vindo de volta" : name })).toBeVisible();
      await expect(page.locator(".page")).toBeVisible();
    }

  for (const name of ["Ações", "Início", "Estilo"]) {
      await navigate(page, name);
      await expect(page.getByRole("button", { name, exact: true }).filter({ visible: true })).toHaveAttribute("aria-current", "page");
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
  for (const [width, expected] of [[1040, 216], [820, 216], [640, 60]]) {
      await page.setViewportSize({ width, height: 740 });
      await expect.poll(() => page.locator("#desktop-sidebar").evaluate(element => element.getBoundingClientRect().width)).toBe(expected);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await expect(page.getByRole("button", { name: "Fechar janela", exact: true })).toBeInViewport();
    }

});

test("advanced settings use keyboard disclosure and retain recording drafts when folded", async ({ page }, testInfo) => {
  await navigate(page, "Ditado");
  const trigger = page.getByRole("button", { name: "Limites e parada automática", exact: true });
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  const section = trigger.locator("xpath=ancestor::section[1]");
  await section.screenshot({ path: testInfo.outputPath("recording-options-closed.png"), animations: "disabled" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(trigger.locator("svg")).toHaveCSS("rotate", "90deg");
  const maximum = page.getByRole("spinbutton", { name: "Duração máxima", exact: true });
  await maximum.fill("120");
  await trigger.focus();
  await page.keyboard.press("Space");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(maximum).toBeHidden();
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(maximum).toHaveValue("120");
  await section.screenshot({ path: testInfo.outputPath("recording-options-open.png"), animations: "disabled" });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(trigger.locator("svg")).toHaveCSS("transition-property", "none");
  await trigger.click();
  await expect(maximum).toBeHidden();
  await trigger.click();
  await expect(maximum).toHaveValue("120");
});

test("recording options stay in the new window and preserve drafts until save", async ({ page }) => {
  await navigate(page, "Ditado");
  const openLimits = async () => {
    const trigger = page.getByRole("button", { name: "Limites e parada automática", exact: true });
    if (await trigger.getAttribute("aria-expanded") !== "true") await trigger.click();
  };
  await expect(page.getByRole("button", { name: "Opções avançadas" })).toHaveCount(0);
  await page.getByText("Limites e parada automática", { exact: true }).click();
  await page.getByRole("spinbutton", { name: "Duração máxima", exact: true }).fill("5");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("alert")).toContainText("aviso");
  await page.getByRole("spinbutton", { name: "Duração máxima", exact: true }).fill("120");
  await page.getByRole("switch", { name: "Parar após fala e silêncio" }).click();
  await page.getByRole("spinbutton", { name: "Tempo de silêncio", exact: true }).fill("1.5");
  await navigate(page, "Sistema");
  await navigate(page, "Ditado");
  await page.getByText("Limites e parada automática", { exact: true }).click();
  await expect(page.getByRole("spinbutton", { name: "Duração máxima", exact: true })).toHaveValue("120");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await expect(page.getByRole("status").filter({ hasText: "Alterações salvas" })).toBeVisible();
  await openLimits();
  await page.getByRole("spinbutton", { name: "Duração máxima", exact: true }).fill("180");
  await settingsDialog(page).getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Alterações não salvas", exact: true })).toBeHidden();
  await openLimits();
  await expect(page.getByRole("spinbutton", { name: "Duração máxima", exact: true })).toHaveValue("120");
});

test("local cleanup and custom route settings are editable without legacy navigation", async ({ page }) => {
  await openStyleReview(page);
  await page.getByRole("combobox", { name: "Contexto da revisão", exact: true }).click();
  await page.getByRole("option", { name: "Transcrição local", exact: true }).click();
  await openStyleReview(page);
  await expect(page.getByRole("combobox", { name: "Contexto da revisão", exact: true })).toContainText("Transcrição local");
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Revisão local independente.");
  await page.getByText("Modelo e endereço personalizados", { exact: true }).click();
  await page.getByRole("textbox", { name: "ID do modelo", exact: true }).fill("custom-local-cleanup");
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Revisão local independente.");
  await page.getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Revisão local independente.");
  await navigate(page, "Geral");
  await openStyleReview(page);
  await page.getByRole("combobox", { name: "Contexto da revisão", exact: true }).click();
  await page.getByRole("option", { name: "Transcrição local", exact: true }).click();
  await openStyleReview(page);
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Revisão local independente.");
  await expect(page.getByRole("combobox", { name: "Modelo", exact: true })).toContainText("custom-local-cleanup");
});

test("local model removal requires confirmation and cancel keeps the model", async ({ page }) => {
  await navigate(page, "Modelos e serviços");
  await openDisclosure(page, "Opções do modelo local");
  await page.getByRole("button", { name: "Remover modelo", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Remover modelo local?", exact: true })).toContainText("reinstalá-lo");
  await page.getByRole("dialog", { name: "Remover modelo local?", exact: true }).getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(page.getByText("Pronto para usar", { exact: true })).toBeVisible();
});

test("sidebar navigation retains text drafts without a global search", async ({ page }) => {
  await openStyleReview(page);
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep this draft through navigation.");
  await navigate(page, "Ditado");
  await openStyleReview(page);
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this draft through navigation.");
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("textbox", { name: "Instruções", exact: true }).focus();
  await page.keyboard.press("Control+End"); await page.keyboard.press("/");
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this draft through navigation./");
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
    await navigate(page, "Dicionário");
    await expect(page.getByRole("button", { name: "Adicionar novo", exact: true })).toBeEnabled();
    await expect(page.locator("aside nav").getByRole("button", { name: "Início", exact: true })).toBeEnabled();
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
  await openStyleReview(page);
  await page.getByRole("textbox", { name: "Instruções", exact: true }).fill("Keep this draft during live telemetry.");
  await navigate(page, "Ditado");
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
  await openStyleReview(page);
  await expect(page.getByRole("textbox", { name: "Instruções", exact: true })).toHaveValue("Keep this draft during live telemetry.");
});

test("repeated menus and dialogs return focus without retaining a modal lock", async ({ page }) => {
  await navigate(page, "Ditado");
  const provider = page.getByRole("combobox", { name: "Serviço", exact: true });
  for (let cycle = 0; cycle < 8; cycle++) {
    await provider.click();
    const search = page.getByPlaceholder("Buscar serviço…");
    await search.fill("no such provider");
    await expect(page.getByRole("option")).toHaveCount(0);
    await search.press("Escape");
    await expect(provider).toBeFocused();
  }
  await openStyleReview(page);
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

test.describe(() => {
  test.use({ settingsScenario: { signedIn: true, librarySync: true } });
  test("snippets account: a staged draft cannot be saved under a new session", async ({ page }) => {
    await navigate(page, "Snippets");
    await addLibraryEntry(page, false, "private phrase", "Account draft");
    await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["logout", ""] }));
    await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("A conta mudou.");
    const saved = await page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })).snippets);
    expect(saved).toEqual([]);
  });
});


test("snippets: dialog preserves both fields typed while an earlier row Save waits", async ({ page }) => {
  await navigate(page, "Snippets");
  await addLibraryEntry(page, false, "saved phrase", "Saved replacement");
  const save = page.getByRole("button", { name: "Salvar alterações", exact: true });
  await save.click(); await expect(save).toBeHidden();
  await editLibraryEntry(page, false, "Earlier row revision");
  let release!: () => void, started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    if (route.request().postDataJSON().method === "save") { started(); await held; }
    await route.fallback();
  });
  const trigger = page.getByRole("textbox", { name: "Nova frase de ativação", exact: true });
  const replacement = page.getByRole("textbox", { name: "Novo texto do snippet", exact: true });
  try {
    await save.click(); await entered;
    await page.getByRole("button", { name: "Adicionar novo", exact: true }).click();
    await trigger.fill("new unsaved phrase");
    await replacement.fill("New text typed during Save");
  } finally { release(); }
  await expect(save).toBeHidden();
  await expect(trigger).toHaveValue("new unsaved phrase");
  await expect(replacement).toHaveValue("New text typed during Save");
  await expect(replacement).toBeFocused();
  const saved = await page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })).snippets);
  expect(saved).toHaveLength(1);
  expect(saved[0].replacement).toBe("Earlier row revision");
});


test("mobile card: dismissal persists and the download stays available in Devices", async ({ page }, testInfo) => {
  const card = page.getByRole("complementary", { name: "O Clarify agora também está no iPhone!", exact: true });
  await expect(card).toBeVisible();
  await expect(card.locator(".iphone-demo-camera")).toHaveCSS("animation-iteration-count", "infinite");
  await card.locator(".iphone-demo").hover();
  await expect(card.locator(".iphone-demo-camera")).toHaveCSS("animation-play-state", "running");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(card.locator(".iphone-demo-camera")).toHaveCSS("animation-name", "none");
  await page.setViewportSize({ width: 640, height: 520 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
  for (const width of [640, 820, 1040, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await card.screenshot({ path: testInfo.outputPath(`iphone-card-${width}.png`) });
    }

  await page.setViewportSize({ width: 1440, height: 900 });
  const floating = await card.boundingBox();
  const history = await page.locator(".home-history").boundingBox();
  expect(floating!.x + floating!.width).toBeCloseTo(1440 - 24, 0);
  expect(floating!.y + floating!.height).toBeCloseTo(900 - 24, 0);
  expect(history!.x + history!.width).toBeLessThan(floating!.x);
  await page.setViewportSize({ width: 1440, height: 600 });
  await expect(card).toHaveCSS("position", "relative");
  await page.setViewportSize({ width: 1040, height: 900 });
  await expect(card).toHaveCSS("position", "relative");
  await card.getByRole("button", { name: "Fechar sugestão do aplicativo", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(card).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Bem-vindo de volta", exact: true })).toBeVisible();
  await expect(card).toHaveCount(0);
  await navigate(page, "Dispositivos");
  await expect(page.getByRole("img", { name: "QR para baixar o Clarify na App Store", exact: true })).toBeVisible();
  const deviceDemo = settingsDialog(page).locator(".mobile-device-guide .iphone-demo-camera");
  await expect(deviceDemo).toBeVisible();
  await expect(deviceDemo).toHaveCSS("animation-name", "none");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(deviceDemo).toHaveCSS("animation-iteration-count", "infinite");
});


test("dictionary: duplicate identity and edited search results stay focusable", async ({ page }) => {
  await navigate(page, "Dicionário");
  await addLibraryEntry(page, true, "Unrelated");
  await addLibraryEntry(page, true, "Straße");
  await page.getByRole("button", { name: "Adicionar novo", exact: true }).click();
  await page.getByRole("textbox", { name: "Novo termo", exact: true }).fill("STRASSE");
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Este termo já está no dicionário.");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Buscar termos", exact: true }).click();
  await page.getByRole("searchbox", { name: "Buscar termos", exact: true }).fill("Straße");
  await page.getByRole("button", { name: "Editar termo 2", exact: true }).click();
  const term = page.getByRole("textbox", { name: "Termo 2", exact: true });
  await term.fill("Changed term");
  await expect(term).toBeFocused();
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
  const search = page.getByRole("searchbox", { name: "Buscar termos", exact: true });
  await expect(search).toHaveValue("Straße");
  await expect(page.getByText("Changed term", { exact: true })).toBeHidden();
  await search.press("Escape");
  await expect(page.getByRole("searchbox", { name: "Buscar termos", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Buscar termos", exact: true })).toBeFocused();
  await expect(page.getByText("Changed term", { exact: true })).toBeVisible();
});


for (const dictionary of [true, false]) {
  test(`${dictionary ? "dictionary" : "snippets"}: dialog cancel, selective flags, search and discard`, async ({ page }) => {
    await navigate(page, dictionary ? "Dicionário" : "Snippets");
    const add = page.getByRole("button", { name: "Adicionar novo", exact: true });
    await add.click();
    const first = page.getByRole("textbox", { name: dictionary ? "Novo termo" : "Nova frase de ativação", exact: true });
    await expect(first).toBeFocused();
    await first.fill("Cancelled draft");
    // Host close requests bypass the inert titlebar while a modal is open.
    await page.locator(".window-close").evaluate(element => (element as HTMLButtonElement).click());
    await expect(page.getByRole("alert")).toContainText("Aplique ou cancele o editor antes de fechar.");
    await expect(first).toHaveValue("Cancelled draft");
    await page.keyboard.press("Escape");
    await expect(add).toBeFocused();
    await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
    await addLibraryEntry(page, dictionary, "Signature", "Name\n  Team\n");
    const save = page.getByRole("button", { name: "Salvar alterações", exact: true });
    await save.click(); await expect(save).toBeHidden();
    await editLibraryEntry(page, dictionary, "Changed text");
    await page.getByRole("button", { name: dictionary ? "Atualizar Dicionário" : "Atualizar Snippets", exact: true }).click();
    await page.getByRole("button", { name: dictionary ? "Editar termo 1" : "Editar snippet 1", exact: true }).click();
    await expect(page.getByRole("textbox", { name: dictionary ? "Termo 1" : "Texto do snippet 1", exact: true })).toHaveValue("Changed text");
    await page.keyboard.press("Escape");
    const flag = page.getByRole("switch", { name: dictionary ? "Usar termo 1" : "Usar snippet 1", exact: true });
    await flag.click(); await expect(flag).not.toBeChecked();
    await page.getByRole("button", { name: "Descartar", exact: true }).click();
    await page.getByRole("dialog", { name: "Alterações não salvas" }).getByRole("button", { name: "Descartar", exact: true }).click();
    await expect(flag).not.toBeChecked();
    await page.getByRole("button", { name: dictionary ? "Editar termo 1" : "Editar snippet 1", exact: true }).click();
    await expect(page.getByRole("textbox", { name: dictionary ? "Termo 1" : "Texto do snippet 1", exact: true })).toHaveValue(dictionary ? "Signature" : "Name\n  Team\n");
    await expect(page.getByRole("dialog")).toHaveCSS("opacity", "1");
    for (const width of [1040, 820, 640]) {
          await page.setViewportSize({ width, height: 760 });
          expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        }

    if (!dictionary) {
      await page.getByRole("switch", { name: "Diferenciar maiúsculas e minúsculas", exact: true }).click();
      await page.getByRole("button", { name: "Aplicar", exact: true }).click();
      await expect.poll(() => page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })).snippets[0].case_sensitive)).toBe(true);
      await expect(save).toBeHidden();
    } else await page.keyboard.press("Escape");
    const searchToggle = page.getByRole("button", { name: dictionary ? "Buscar termos" : "Buscar snippets", exact: true });
    const search = page.getByRole("searchbox", { name: dictionary ? "Buscar termos" : "Buscar snippets", exact: true });
    await expect(search).toHaveCount(0);
    await searchToggle.click();
    await expect(search).toBeFocused();
    await search.fill("absent");
    await expect(page.getByText(dictionary ? "Nenhum termo encontrado." : "Nenhum snippet encontrado.", { exact: true })).toBeVisible();
    await page.getByRole("heading", { level: 1, name: dictionary ? "Dicionário" : "Snippets", exact: true }).click();
    await expect(search).toHaveCount(0);
    await expect(page.getByText("Signature", { exact: true })).toBeVisible();
    await searchToggle.click();
    await expect(search).toHaveValue("");
    await search.fill("absent");
    await search.press("Escape");
    await expect(search).toHaveCount(0);
    await expect(searchToggle).toBeFocused();
    await page.getByRole("button", { name: dictionary ? "Remover termo 1" : "Remover snippet 1", exact: true }).click();
    await save.click(); await expect(save).toBeHidden();
  });

  settingsScenario({ signedIn: true, librarySync: true }, () => {
  test(`snippets account: ${dictionary ? "dictionary" : "snippets"} dialog clears when the session changes`, async ({ page }) => {
    await navigate(page, dictionary ? "Dicionário" : "Snippets");
    await page.getByRole("button", { name: "Adicionar novo", exact: true }).click();
    await page.getByRole("textbox", { name: dictionary ? "Novo termo" : "Nova frase de ativação", exact: true }).fill("Private draft");
    await page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["logout", ""] }));
    await expect(page.getByRole("dialog")).toBeHidden();
    await page.getByRole("button", { name: "Adicionar novo", exact: true }).click();
    await expect(page.getByRole("textbox", { name: dictionary ? "Novo termo" : "Nova frase de ativação", exact: true })).toHaveValue("");
    await expect(page.getByRole("button", { name: "Aplicar", exact: true })).toBeDisabled();
  });

  test(`snippets account: sync-import keeps local ${dictionary ? "dictionary" : "snippets"} text and remote additions`, async ({ page }) => {
    await navigate(page, dictionary ? "Dicionário" : "Snippets");
    await addLibraryEntry(page, dictionary, "Base term", "Base replacement");
    const save = page.getByRole("button", { name: "Salvar alterações", exact: true });
    await save.click(); await expect(save).toBeHidden();
    await editLibraryEntry(page, dictionary, "Local unsaved revision");
    await page.evaluate(() => fetch("/__test_rpc", { method: "POST", body: JSON.stringify({ method: "testArmLibrarySync", args: [] }) }));
    await page.getByRole("switch", { name: dictionary ? "Usar termo 1" : "Usar snippet 1", exact: true }).click();
    await expect(page.getByText(dictionary ? "Remote term" : "Remote replacement", { exact: true })).toBeVisible();
    await save.click(); await expect(save).toBeHidden();
    const saved = await page.evaluate(async () => (await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] })));
    const entries = dictionary ? saved.dictionaryEntries : saved.snippets;
    expect(entries).toHaveLength(2);
    expect(dictionary ? entries[0].term : entries[0].replacement).toBe("Local unsaved revision");
    expect(entries[0].enabled).toBe(false);
  });
  });
}

async function addLibraryEntry(page: Page, dictionary: boolean, name: string, text = "Original text") {
  await page.getByRole("button", { name: "Adicionar novo", exact: true }).click();
  await page.getByRole("textbox", { name: dictionary ? "Novo termo" : "Nova frase de ativação", exact: true }).fill(name);
  if (dictionary) await page.getByRole("textbox", { name: "Novo termo", exact: true }).press("Enter");
  else {
    await page.getByRole("textbox", { name: "Novo texto do snippet", exact: true }).fill(text);
    await page.getByRole("textbox", { name: "Nova frase de ativação", exact: true }).press("Enter");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("textbox", { name: "Novo texto do snippet", exact: true }).press("ControlOrMeta+Enter");
  }
}
async function editLibraryEntry(page: Page, dictionary: boolean, text: string) {
  await page.getByRole("button", { name: dictionary ? "Editar termo 1" : "Editar snippet 1", exact: true }).click();
  await page.getByRole("textbox", { name: dictionary ? "Termo 1" : "Texto do snippet 1", exact: true }).fill(text);
  await page.getByRole("button", { name: "Aplicar", exact: true }).click();
}
