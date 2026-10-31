import { test, expect, openSettings } from "./settings-harness";

test("workspace: navigation presents tasks and keeps keyboard focus at every width", async ({ page }, testInfo) => {
  for (const width of [1040, 820, 640]) {
    await page.setViewportSize({ width, height: 760 });
    const navigation = page.getByRole("navigation");
    expect(await navigation.getByRole("button").evaluateAll(buttons => buttons.map(button => button.getAttribute("aria-label")))).toEqual([
      "Ditado", "Estilo", "Ações de texto", "Dicionário", "Snippets", "Histórico", "Configurações",
    ]);
    await expect(navigation.getByRole("combobox")).toHaveCount(0);
    await navigation.getByRole("button", { name: "Ditado", exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(navigation.getByRole("button", { name: "Estilo", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Estilo", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Nível de revisão", exact: true })).toBeVisible();
    await expect(navigation.getByRole("button", { name: "Configurações", exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ path: testInfo.outputPath(`style-${width}.png`) });
  }
});

test("text profiles: Cancel keeps the route and Save preserves unrelated Style instructions", async ({ page, settingsFixture }, testInfo) => {
  await page.getByRole("button", { name: "Estilo", exact: true }).click();
  await page.getByRole("button", { name: "Modelo e instruções da revisão", exact: true }).click();
  const prompt = page.getByRole("textbox", { name: "Instruções", exact: true });
  await prompt.fill("Pending style instructions.");
  const original = (await settingsFixture.rpc("snapshot")).textActionProfiles;
  const settings = await openSettings(page, "Modelos e serviços");
  await settings.getByRole("button", { name: "Editar perfil de Reescrita", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Perfil de processamento", exact: true });
  await dialog.getByRole("button", { name: "Modelo e endereço personalizados", exact: true }).click();
  await dialog.getByRole("textbox", { name: "ID do modelo", exact: true }).fill("fixture-model");
  await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
  expect((await settingsFixture.rpc("snapshot")).textActionProfiles).toEqual(original);
  await settings.getByRole("button", { name: "Editar perfil de Reescrita", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Perfil de processamento", exact: true });
  const model = dialog.getByRole("textbox", { name: "ID do modelo", exact: true });
  if (!await model.isVisible()) await dialog.getByRole("button", { name: "Modelo e endereço personalizados", exact: true }).click();
  await model.fill("fixture-model");
  await page.screenshot({ path: testInfo.outputPath("text-profile-editor.png") });
  await dialog.getByRole("button", { name: "Salvar perfil", exact: true }).click();
  await expect(dialog).toBeHidden();
  const saved = await settingsFixture.rpc("snapshot");
  expect(saved.textActionProfiles?.find(profile => profile.id === "legacy-rewrite")?.modelId).toBe("fixture-model");
  expect(saved.routePrompt).not.toBe("Pending style instructions.");
  await settings.getByRole("button", { name: "Concluído", exact: true }).click();
  await expect(prompt).toHaveValue("Pending style instructions.");
});

test("after dictation: translation saves only after an explicit target language", async ({ page, settingsFixture }) => {
  await page.getByRole("button", { name: "Estilo", exact: true }).click();
  const select = page.getByRole("combobox", { name: "Ação após o ditado", exact: true });
  await select.click();
  await page.getByRole("option", { name: "Tradução", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Idioma da tradução", exact: true });
  await expect(dialog.getByRole("button", { name: "Aplicar", exact: true })).toBeDisabled();
  expect((await settingsFixture.rpc("snapshot")).afterDictationTextActionId).toBe("");
  await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(select).toContainText("Revisão padrão");
  await select.click(); await page.getByRole("option", { name: "Tradução", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Idioma da tradução", exact: true });
  await dialog.getByRole("combobox", { name: "Idioma de destino", exact: true }).click();
  await page.getByRole("option", { name: "Inglês", exact: true }).click();
  await dialog.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect(dialog).toBeHidden();
  const saved = await settingsFixture.rpc("snapshot");
  expect(saved.afterDictationTextActionId).toBe("translation");
  expect(saved.afterDictationTextActionLanguage).toBe("en");
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Estilo", exact: true }).click();
  await expect(select).toContainText("Tradução");
});

test("text actions: saved preview uses the latest sample and requires a translation target", async ({ page, settingsFixture }, testInfo) => {
  await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  await page.locator("#text-action-rewrite").getByRole("button", { name: "Editar ação", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Editar ação", exact: true });
  const sample = dialog.getByRole("textbox", { name: "Texto de exemplo", exact: true });
  await sample.fill("First sample");
  await dialog.getByRole("button", { name: "Testar", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText("Preview (auto): First sample");
  await sample.fill("Second sample");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Testar", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText("Preview (auto): Second sample");
  await page.screenshot({ path: testInfo.outputPath("action-preview.png") });
  await dialog.getByRole("textbox", { name: "Instruções da ação", exact: true }).fill("Pending edit.");
  await expect(dialog.getByRole("button", { name: "Testar", exact: true })).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
  await page.locator("#text-action-translation").getByRole("button", { name: "Editar ação", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Editar ação", exact: true });
  await dialog.getByRole("textbox", { name: "Texto de exemplo", exact: true }).fill("Target sample");
  await expect(dialog.getByRole("button", { name: "Testar", exact: true })).toBeDisabled();
  await dialog.getByRole("combobox", { name: "Idioma de destino", exact: true }).click();
  await page.getByRole("option", { name: "Inglês", exact: true }).click();
  await dialog.getByRole("button", { name: "Testar", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText("Preview (en): Target sample");
  expect((await settingsFixture.rpc("snapshot")).dirty).toBe(false);
});

test("settings dialog: unsaved privacy changes stay local and the task remains selected", async ({ page }, testInfo) => {
  await page.getByRole("button", { name: "Estilo", exact: true }).click();
  const dialog = await openSettings(page, "Privacidade");
  await dialog.getByRole("switch", { name: "Salvar histórico", exact: true }).click();
  await expect(dialog.getByRole("switch", { name: "Salvar histórico", exact: true })).toBeChecked();
  const retention = dialog.getByRole("spinbutton", { name: "Retenção do histórico", exact: true });
  await retention.fill("31");
  await dialog.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText("Há alterações não salvas");
  await dialog.getByRole("button", { name: "Continuar editando", exact: true }).click();
  await expect(retention).toHaveValue("31");
  await dialog.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath("settings-dialog.png") });
  await dialog.getByRole("button", { name: "Concluído", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Configurações", exact: true })).toBeFocused();
  await expect(page.getByRole("heading", { level: 1, name: "Estilo", exact: true })).toBeVisible();
  await page.reload();
  const reopened = await openSettings(page, "Privacidade");
  await expect(reopened.getByRole("spinbutton", { name: "Retenção do histórico", exact: true })).toHaveValue("31");
});

test("style rule: Cancel preserves configuration and Save adds the named app", async ({ page, settingsFixture }, testInfo) => {
  await page.getByRole("button", { name: "Estilo", exact: true }).click();
  const original = (await settingsFixture.rpc("snapshot")).applicationWritingStyles;
  await page.getByRole("button", { name: "Adicionar aplicativo", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Estilo do aplicativo", exact: true });
  const path = dialog.getByRole("textbox", { name: "Caminho do aplicativo", exact: true });
  if (!await path.isVisible()) await dialog.getByRole("button", { name: "Escolher outro aplicativo", exact: true }).click();
  await path.fill("C:\\Apps\\Editor.exe");
  await dialog.getByRole("combobox", { name: "Estilo de escrita", exact: true }).click();
  await page.getByRole("option", { name: "Muito casual", exact: true }).click();
  await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
  expect((await settingsFixture.rpc("snapshot")).applicationWritingStyles).toEqual(original);
  await page.getByRole("button", { name: "Adicionar aplicativo", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Estilo do aplicativo", exact: true });
  if (!await path.isVisible()) await dialog.getByRole("button", { name: "Escolher outro aplicativo", exact: true }).click();
  await path.fill("C:\\Apps\\Editor.exe");
  await page.screenshot({ path: testInfo.outputPath("app-style-editor.png") });
  await dialog.getByRole("button", { name: "Salvar regra", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Editar estilo de editor", exact: true })).toBeVisible();
  const rules = (await settingsFixture.rpc("snapshot")).applicationWritingStyles ?? [];
  expect(rules.some(rule => rule.executable.toLowerCase().endsWith("editor.exe"))).toBe(true);
});

test("text actions: prompt and shortcut remain drafts until Save", async ({ page, settingsFixture }, testInfo) => {
  await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  const before = (await settingsFixture.rpc("snapshot")).textActions;
  await page.getByRole("button", { name: "Nova ação", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Nova ação", exact: true });
  await dialog.getByRole("textbox", { name: "Nome da ação", exact: true }).fill("Resumo de teste");
  await dialog.getByRole("textbox", { name: "Instruções da ação", exact: true }).fill("Resuma o texto em três tópicos.");
  await dialog.getByRole("button", { name: "Definir atalho", exact: true }).click();
  const capture = dialog.getByRole("textbox", { name: "Novo atalho da ação", exact: true });
  await expect(capture).toBeFocused();
  await capture.press("Control+Shift+S");
  await expect(capture).toBeHidden();
  expect((await settingsFixture.rpc("snapshot")).textActions).toEqual(before);
  await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
  expect((await settingsFixture.rpc("snapshot")).textActions).toEqual(before);
  await page.getByRole("button", { name: "Nova ação", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Nova ação", exact: true });
  await dialog.getByRole("textbox", { name: "Nome da ação", exact: true }).fill("Resumo de teste");
  await dialog.getByRole("textbox", { name: "Instruções da ação", exact: true }).fill("Resuma o texto em três tópicos.");
  await dialog.getByRole("button", { name: "Salvar ação", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Editar ação", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Salvar ação", exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("text-action-editor.png") });
  await page.getByRole("dialog").getByRole("button", { name: "Concluído", exact: true }).click();
  const saved = (await settingsFixture.rpc("snapshot")).textActions?.find(action => action.name === "Resumo de teste");
  expect(saved?.prompt).toBe("Resuma o texto em três tópicos.");
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Microfone", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Resumo de teste", exact: true })).toBeVisible();
});

test("text actions: duplicate has a new ID and no shortcut; disable and delete persist", async ({ page, settingsFixture }) => {
  await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  const original = (await settingsFixture.rpc("snapshot")).textActions!.find(action => action.id === "rewrite")!;
  expect(original.shortcut).not.toBeNull();
  const row = page.locator("#text-action-rewrite");
  await row.getByRole("button", { name: "Mais opções de Reescrita", exact: true }).click();
  await page.getByRole("menuitem", { name: "Duplicar", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Nova ação", exact: true });
  await expect(editor.getByRole("textbox", { name: "Instruções da ação", exact: true })).toHaveValue(original.prompt);
  await expect(editor.getByRole("button", { name: "Definir atalho", exact: true })).toBeVisible();
  expect((await settingsFixture.rpc("snapshot")).textActions).toHaveLength(2);
  await editor.getByRole("textbox", { name: "Nome da ação", exact: true }).fill("Cópia de teste");
  await editor.getByRole("button", { name: "Salvar ação", exact: true }).click();
  const savedEditor = page.getByRole("dialog", { name: "Editar ação", exact: true });
  await expect(savedEditor.getByRole("button", { name: "Salvar ação", exact: true })).toBeDisabled();
  await savedEditor.getByRole("button", { name: "Concluído", exact: true }).click();
  const saved = (await settingsFixture.rpc("snapshot")).textActions!;
  const copy = saved.find(action => action.name === "Cópia de teste")!;
  expect(copy.id).not.toBe(original.id);
  expect(copy.shortcut).toBeNull();
  expect(copy.prompt).toBe(original.prompt);
  expect(saved.find(action => action.id === original.id)).toEqual(original);
  const enabled = row.getByRole("switch", { name: "Ativar Reescrita", exact: true });
  await enabled.click(); await expect(enabled).not.toBeChecked();
  await page.reload(); await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  await expect(enabled).not.toBeChecked();
  const copyRow = page.locator(`#text-action-${copy.id}`);
  await copyRow.getByRole("button", { name: "Mais opções de Cópia de teste", exact: true }).click();
  await page.getByRole("menuitem", { name: "Excluir", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "Excluir ação?", exact: true });
  await confirmation.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(copyRow).toBeVisible();
  await copyRow.getByRole("button", { name: "Mais opções de Cópia de teste", exact: true }).click();
  await page.getByRole("menuitem", { name: "Excluir", exact: true }).click();
  await confirmation.getByRole("button", { name: "Excluir", exact: true }).click();
  await expect(copyRow).toHaveCount(0);
  await page.reload(); await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  await expect(copyRow).toHaveCount(0);
  expect((await settingsFixture.rpc("snapshot")).textActions!.map(action => action.id)).toEqual(["rewrite", "translation"]);
});

test("text actions: stale CAS rejects Save without losing the editor draft or the newer saved action", async ({ page, settingsFixture }) => {
  await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  const before = await settingsFixture.rpc("snapshot");
  const { revision: _revision, ...action } = before.textActions!.find(action => action.id === "rewrite")!;
  await page.locator("#text-action-rewrite").getByRole("button", { name: "Editar ação", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Editar ação", exact: true });
  const prompt = editor.getByRole("textbox", { name: "Instruções da ação", exact: true });
  await prompt.fill("Local instructions that must survive a stale save.");
  const current = await settingsFixture.rpc("saveTextAction", { ...action, prompt: "Newer saved instructions." }, before.textActionContext, before.textActionsRevision);
  expect(current.textActionsRevision).not.toBe(before.textActionsRevision);
  await editor.getByRole("button", { name: "Salvar ação", exact: true }).click();
  await expect(editor.getByRole("alert")).toContainText("Suas alterações foram mantidas");
  await expect(prompt).toHaveValue("Local instructions that must survive a stale save.");
  await expect(editor.getByRole("button", { name: "Salvar ação", exact: true })).toBeEnabled();
  const after = await settingsFixture.rpc("snapshot");
  expect(after.textActionsRevision).toBe(current.textActionsRevision);
  expect(after.textActions!.find(action => action.id === "rewrite")!.prompt).toBe("Newer saved instructions.");
  await editor.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(editor.getByRole("status")).toContainText("Descartar as alterações desta ação?");
  await editor.getByRole("button", { name: "Continuar editando", exact: true }).click();
  await expect(prompt).toHaveValue("Local instructions that must survive a stale save.");
  await editor.getByRole("button", { name: "Atualizar ações", exact: true }).click();
  await expect(editor.getByText("A versão salva mudou", { exact: true })).toBeVisible();
  await expect(editor.getByRole("textbox", { name: "Instruções da versão salva", exact: true })).toHaveValue("Newer saved instructions.");
  await expect(prompt).toHaveValue("Local instructions that must survive a stale save.");
  await expect(editor.getByRole("button", { name: "Salvar ação", exact: true })).toBeDisabled();
  await editor.getByRole("button", { name: "Manter meu rascunho", exact: true }).click();
  expect((await settingsFixture.rpc("snapshot")).textActions!.find(action => action.id === "rewrite")!.prompt).toBe("Newer saved instructions.");
  await editor.getByRole("button", { name: "Salvar ação", exact: true }).click();
  await expect.poll(async () => (await settingsFixture.rpc("snapshot")).textActions!.find(action => action.id === "rewrite")!.prompt).toBe("Local instructions that must survive a stale save.");
  await expect(prompt).toHaveValue("Local instructions that must survive a stale save.");
});

test("text actions: shortcut input receives focus only after the controller accepts capture", async ({ page, settingsFixture }) => {
  await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
  await page.getByRole("button", { name: "Nova ação", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Nova ação", exact: true });
  const begin = editor.getByRole("button", { name: "Definir atalho", exact: true });
  const capture = editor.getByRole("textbox", { name: "Novo atalho da ação", exact: true });
  const before = (await settingsFixture.rpc("snapshot")).textActions;
  let attempt = 0, release!: () => void, started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const entered = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    if (request.method === "beginTextActionHotkeyCapture") {
      if (++attempt === 1) {
        await route.fallback({ postData: JSON.stringify({ ...request, args: ["stale-context"] }) }); return;
      }
      started(); await held;
    }
    await route.fallback();
  });
  await begin.click();
  await expect(editor.getByRole("alert")).toContainText("Não foi possível iniciar a captura");
  await expect(capture).toHaveCount(0);
  await expect(begin).toBeEnabled();
  try {
    await begin.click(); await entered;
    await expect(begin).toBeDisabled();
    await expect(capture).toHaveCount(0);
    await page.keyboard.press("Control+Shift+K");
    expect((await settingsFixture.rpc("snapshot")).textActions).toEqual(before);
  } finally { release(); }
  await expect(capture).toBeFocused();
  await capture.press("Control+Shift+K");
  await expect(capture).toBeHidden();
  await expect(editor.getByRole("button", { name: "Ctrl+Shift+K", exact: true })).toBeVisible();
  expect((await settingsFixture.rpc("snapshot")).textActions).toEqual(before);
  await editor.getByRole("button", { name: "Cancelar", exact: true }).click();
  expect((await settingsFixture.rpc("snapshot")).textActions).toEqual(before);
});

test.describe("hosted text actions", () => {
  test.use({ signedIn: true });
  test("an incomplete hosted write can be refreshed without losing the open draft", async ({ page, settingsFixture }) => {
    await expect.poll(async () => (await settingsFixture.rpc("snapshot")).textActionRefresh?.status).toBe("succeeded");
    await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
    await expect(page.getByRole("button", { name: "Atualizar ações", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Nova ação", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "Nova ação", exact: true });
    const name = editor.getByRole("textbox", { name: "Nome da ação", exact: true });
    const prompt = editor.getByRole("textbox", { name: "Instruções da ação", exact: true });
    await name.fill("Rascunho preservado"); await prompt.fill("Preserve estas instruções durante a atualização.");
    await settingsFixture.rpc("testRequireTextActionRefresh" as never);
    await expect(editor.getByRole("status")).toContainText("concluir a recuperação");
    await editor.getByRole("button", { name: "Atualizar ações", exact: true }).click();
    await expect(editor.getByText("Atualize as ações para concluir a recuperação. Seu rascunho será mantido.", { exact: true })).toHaveCount(0);
    await expect(name).toHaveValue("Rascunho preservado");
    await expect(prompt).toHaveValue("Preserve estas instruções durante a atualização.");
    await editor.getByRole("button", { name: "Salvar ação", exact: true }).click();
    await expect.poll(async () => (await settingsFixture.rpc("snapshot")).textActions!.some(action => action.name === "Rascunho preservado")).toBe(true);
  });
  test("Save waits for the final job and a failed delete keeps its confirmation open", async ({ page, settingsFixture }) => {
    await page.getByRole("button", { name: "Ações de texto", exact: true }).click();
    await expect(page.getByRole("button", { name: "Nova ação", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Nova ação", exact: true }).click();
    const draft = page.getByRole("dialog", { name: "Nova ação", exact: true });
    await draft.getByRole("textbox", { name: "Nome da ação", exact: true }).fill("Ação da conta");
    await draft.getByRole("textbox", { name: "Instruções da ação", exact: true }).fill("Resuma o texto.");
    let armed = false;
    let release!: () => void, started!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const entered = new Promise<void>(resolve => { started = resolve; });
    await page.route("**/__test_rpc", async route => {
      const method = route.request().postDataJSON().method;
      if (method === "saveTextAction") armed = true;
      if (armed && method === "poll") { started(); await held; }
      await route.fallback();
    });
    try {
      await draft.getByRole("button", { name: "Salvar ação", exact: true }).click(); await entered;
      await expect(draft).toBeVisible();
      await expect(draft.getByRole("button", { name: "Salvando…", exact: true })).toBeDisabled();
      await expect(page.getByRole("dialog", { name: "Editar ação", exact: true })).toHaveCount(0);
    } finally { armed = false; release(); }
    const editor = page.getByRole("dialog", { name: "Editar ação", exact: true });
    await expect(editor).toBeVisible();
    await editor.getByRole("button", { name: "Concluído", exact: true }).click();
    const saved = (await settingsFixture.rpc("snapshot")).textActions!.find(action => action.name === "Ação da conta")!;
    await settingsFixture.rpc("testRejectTextActionSave");
    const row = page.locator(`#text-action-${saved.id}`);
    await row.getByRole("button", { name: "Mais opções de Ação da conta", exact: true }).click();
    await page.getByRole("menuitem", { name: "Excluir", exact: true }).click();
    const confirmation = page.getByRole("dialog", { name: "Excluir ação?", exact: true });
    await confirmation.getByRole("button", { name: "Excluir", exact: true }).click();
    await expect(confirmation.getByRole("alert")).toContainText("Não foi possível excluir");
    expect((await settingsFixture.rpc("snapshot")).textActions!.some(action => action.id === saved.id)).toBe(true);
    await confirmation.getByRole("button", { name: "Cancelar", exact: true }).click();
    await expect(row).toBeVisible();
  });
});
