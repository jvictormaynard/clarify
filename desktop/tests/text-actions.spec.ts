import { navigate, openDisclosure } from "./settings-navigation";
import { test, expect, openSettings } from "./settings-harness";

test("workspace: navigation presents tasks and keeps keyboard focus at every width", async ({ page }, testInfo) => {
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible();
  const setup = page.locator("aside nav").getByRole("button", { name: "Configurações", exact: true });
  await setup.click();
  const settings = page.getByRole("dialog", { name: "Configurações", exact: true });
  await expect(settings.getByRole("heading", { level: 2, name: "Geral", exact: true })).toBeVisible();
  await settings.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(setup).toBeFocused();
  for (const width of [1040, 820, 640]) {
    await page.setViewportSize({ width, height: 760 });
    const navigation = page.locator("aside nav");
    expect(await navigation.getByRole("button").evaluateAll(buttons => buttons.map(button => button.getAttribute("aria-label")))).toEqual([
      "Início", "Dicionário", "Snippets", "Estilo", "Ações", "Configurações",
    ]);
    await expect(navigation.getByRole("combobox")).toHaveCount(0);
    await navigation.getByRole("button", { name: "Dicionário", exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(navigation.getByRole("button", { name: "Snippets", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Snippets", exact: true })).toBeVisible();
    await navigation.getByRole("button", { name: "Estilo", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Estilo", exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Edição do texto", exact: true })).toBeVisible();
    await expect(navigation.getByRole("button", { name: "Configurações", exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ path: testInfo.outputPath(`style-${width}.png`) });
  }
});

test("text profiles: Cancel keeps the route and Save preserves unrelated Style instructions", async ({ page, settingsFixture }, testInfo) => {
  await navigate(page, "Estilo");
  await openDisclosure(page, "Mais opções");
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
  await settings.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(prompt).toHaveValue("Pending style instructions.");
});

test("after dictation: translation saves only after an explicit target language", async ({ page, settingsFixture }) => {
  await navigate(page, "Estilo");
  await openDisclosure(page, "Mais opções");
  await page.getByRole("combobox", { name: "Ação automática salva", exact: true }).click();
  await page.getByRole("option", { name: "Aplicar ação de texto", exact: true }).click();
  const select = page.getByRole("combobox", { name: "Ação após o ditado", exact: true });
  await select.click();
  await page.getByRole("option", { name: "Tradução", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "Idioma da tradução", exact: true });
  await expect(dialog.getByRole("button", { name: "Aplicar", exact: true })).toBeDisabled();
  expect((await settingsFixture.rpc("snapshot")).afterDictationTextActionId).toBe("");
  await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(select).toContainText("Escolher ação");
  await select.click(); await page.getByRole("option", { name: "Tradução", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "Idioma da tradução", exact: true });
  await dialog.getByRole("combobox", { name: "Idioma de destino", exact: true }).click();
  await page.getByRole("option", { name: "Inglês", exact: true }).click();
  await dialog.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect(dialog).toBeHidden();
  const saved = await settingsFixture.rpc("snapshot");
  expect(saved.dictationCleanupLevel).toBe("clarity");
  expect(saved.afterDictationTextActionId).toBe("translation");
  expect(saved.afterDictationTextActionLanguage).toBe("en");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Bem-vindo de volta", exact: true })).toBeVisible();
  await navigate(page, "Estilo");
  await expect(page.getByRole("combobox", { name: "Edição do texto", exact: true })).toContainText("Tradução");
  // Changing tone must not remove the selected automatic action or its target.
  await page.getByRole("combobox", { name: "Tom", exact: true }).click();
  await page.getByRole("option", { name: "Formal", exact: true }).click();
  expect((await settingsFixture.rpc("snapshot")).afterDictationTextActionId).toBe("translation");
  expect((await settingsFixture.rpc("snapshot")).afterDictationTextActionLanguage).toBe("en");
  await page.getByRole("combobox", { name: "Edição do texto", exact: true }).click();
  await page.getByRole("option", { name: "Manter minhas palavras", exact: true }).click();
  await expect(select).toHaveCount(0);
  const preserved = await settingsFixture.rpc("snapshot");
  expect(preserved.dictationCleanupLevel).toBe("preserve");
  expect(preserved.afterDictationTextActionId).toBe("");
});

test("after dictation: basic processing stays available without an action catalog", async ({ page, settingsFixture }) => {
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    const result = await settingsFixture.rpc(request.method, ...(request.args ?? []));
    await route.fulfill({ json: { result: { ...result, textActionContext: "", textActions: [] } } });
  });
  await navigate(page, "Estilo");
  const mode = page.getByRole("combobox", { name: "Edição do texto", exact: true });
  await expect(mode).toBeEnabled();
  await mode.click(); await page.getByRole("option", { name: "Manter minhas palavras", exact: true }).click();
  await expect(mode).toContainText("Manter minhas palavras");
  expect((await settingsFixture.rpc("snapshot")).dictationCleanupLevel).toBe("preserve");
  await openDisclosure(page, "Mais opções");
  await page.getByRole("combobox", { name: "Ação automática salva", exact: true }).click();
  await page.getByRole("option", { name: "Aplicar ação de texto", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Ação após o ditado", exact: true })).toBeDisabled();
  await page.getByRole("combobox", { name: "Ação automática salva", exact: true }).click();
  await page.getByRole("option", { name: "Nenhuma", exact: true }).click();
  expect((await settingsFixture.rpc("snapshot")).dictationCleanupLevel).toBe("preserve");

});

test("text actions: saved preview uses the latest sample and the shared output language", async ({ page, settingsFixture }, testInfo) => {
  await settingsFixture.rpc("savePreference", "setLanguage", ["auto"]);
  await page.reload();
  await page.getByRole("button", { name: "Ações", exact: true }).click();
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
  await expect(dialog.getByRole("button", { name: "Testar", exact: true })).toBeEnabled();
  await dialog.getByRole("combobox", { name: "Idioma de saída", exact: true }).click();
  await page.getByRole("option", { name: "Inglês", exact: true }).click();
  await dialog.getByRole("button", { name: "Testar", exact: true }).click();
  await expect(dialog.getByRole("status")).toContainText("Preview (en): Target sample");
  expect((await settingsFixture.rpc("snapshot")).dirty).toBe(false);
  expect((await settingsFixture.rpc("snapshot")).language).toBe("en");
});

test("settings dialog: unsaved privacy changes stay local and the task remains selected", async ({ page }, testInfo) => {
  await navigate(page, "Estilo");
  const dialog = await openSettings(page, "Privacidade");
  const actions = dialog.locator('[data-slot="dialog-footer"]');
  await expect(actions).toHaveCount(0);
  await dialog.getByRole("switch", { name: "Salvar histórico", exact: true }).click();
  await expect(dialog.getByRole("switch", { name: "Salvar histórico", exact: true })).toBeChecked();
  const retention = dialog.getByRole("spinbutton", { name: "Retenção do histórico", exact: true });
  await retention.fill("31");
  await expect(actions).toBeVisible();
  await dialog.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(dialog.getByRole("status").filter({ hasText: "Há alterações não salvas" })).toBeVisible();
  await dialog.getByRole("button", { name: "Continuar editando", exact: true }).click();
  await expect(retention).toHaveValue("31");
  await dialog.getByRole("button", { name: "Salvar alterações", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath("settings-dialog.png") });
  await expect(actions).toHaveCount(0);
  await dialog.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Configurações", exact: true })).toBeFocused();
  await expect(page.getByRole("heading", { level: 1, name: "Estilo", exact: true })).toBeVisible();
  await page.reload();
  const reopened = await openSettings(page, "Privacidade");
  await expect(reopened.getByRole("spinbutton", { name: "Retenção do histórico", exact: true })).toHaveValue("31");
});



test("text actions: prompt and shortcut remain drafts until Save", async ({ page, settingsFixture }, testInfo) => {
  await page.getByRole("button", { name: "Ações", exact: true }).click();
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
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ações", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Resumo de teste", exact: true })).toBeVisible();
});

test("text actions: duplicate has a new ID and no shortcut; disable and delete persist", async ({ page, settingsFixture }) => {
  await page.getByRole("button", { name: "Ações", exact: true }).click();
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
  await row.getByRole("button", { name: "Mais opções de Reescrita", exact: true }).click();
  await page.getByRole("menuitem", { name: "Desativar ação", exact: true }).click();
  await expect(row).toContainText("Desativada");
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ações", exact: true }).click();
  await expect(row).toContainText("Desativada");
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
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Ações", exact: true }).click();
  await expect(copyRow).toHaveCount(0);
  expect((await settingsFixture.rpc("snapshot")).textActions!.map(action => action.id)).toEqual(["rewrite", "translation"]);
});

test("text actions: stale CAS rejects Save without losing the editor draft or the newer saved action", async ({ page, settingsFixture }) => {
  await page.getByRole("button", { name: "Ações", exact: true }).click();
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
  await page.getByRole("button", { name: "Ações", exact: true }).click();
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
    await page.getByRole("button", { name: "Ações", exact: true }).click();
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
    await page.getByRole("button", { name: "Ações", exact: true }).click();
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

test("pill preferences: tone uses the shared saved owner and hides when editing is forbidden", async ({ page, settingsFixture }) => {
  await settingsFixture.rpc("savePreference", "setDictationWritingStyle", ["organized"]);
  await page.addInitScript(() => {
    const listeners = new Set<(message: unknown) => void>();
    const publishWorkflow = async () => {
      const saved = await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] });
      const state = { surface: "idle", uiLanguage: "pt", language: "auto",
        dictationWritingStyle: saved.dictationWritingStyle,
        writingStyleRefinementAllowed: saved.writingStyleRefinementAllowed };
      for (const listener of listeners) listener({ event: "workflow", state });
    };
    (window as any).clarifyDesktop = {
      call: async (channel: string, method: string, args: unknown[]) => {
        if (channel === "workflow") {
          if (method === "refreshMicrophones") await publishWorkflow();
          return;
        }
        if (method !== "savePreference") throw new Error("Invalid renderer channel");
        const result = await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method, args });
        await publishWorkflow();
        return result;
      },
      subscribe: (listener: (message: unknown) => void) => { listeners.add(listener); return () => listeners.delete(listener); },
      ready: publishWorkflow,
      window: async () => {},
    };
  });
  await page.goto("/?surface=pill");
  const more = page.getByRole("button", { name: "Mais opções", exact: true });
  await more.click();
  await page.getByRole("button", { name: "Tom", exact: true }).click();
  await expect(page.getByRole("button", { name: "Organizado", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Manter meu tom", exact: true }).click();
  await expect(more).toBeFocused();
  await expect.poll(async () => (await settingsFixture.rpc("snapshot")).dictationWritingStyle).toBe("natural");
  await settingsFixture.rpc("savePreference", "setDictationCleanupLevel", ["preserve"]);
  await more.click();
  // The adapter projects the saved controller state through the workflow push.
  await expect.poll(async () => (await settingsFixture.rpc("snapshot")).writingStyleRefinementAllowed).toBe(false);
  await expect(page.getByRole("button", { name: "Tom", exact: true })).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.keyboard.press("Escape"); await expect(more).toBeFocused();
});

test("after dictation: custom saved names stay literal in main and advanced pickers", async ({ page, settingsFixture }) => {
  let state = await settingsFixture.rpc("snapshot");
  await settingsFixture.rpc("saveTextAction", {
    ...state.textActions![0], id: "11111111-1111-4111-8111-111111111111", name: "Rewrite", kind: "custom", shortcut: null,
  }, state.textActionContext, state.textActionsRevision);
  await expect.poll(async () => (await settingsFixture.rpc("snapshot")).textActionMutation?.status).toBe("succeeded");
  state = await settingsFixture.rpc("snapshot");
  await settingsFixture.rpc("setDictationPostProcessing", "action", "11111111-1111-4111-8111-111111111111", "auto", state.textActionContext, state.textActionsRevision);
  await expect.poll(async () => (await settingsFixture.rpc("snapshot")).textActionMutation?.status).toBe("succeeded");
  await page.reload(); await page.getByRole("button", { name: "Estilo", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Edição do texto", exact: true })).toContainText("Rewrite");
  await openDisclosure(page, "Mais opções");
  await expect(page.getByRole("combobox", { name: "Ação após o ditado", exact: true })).toContainText("Rewrite");
});

test("after dictation: removing a legacy saved action selects clarity without enabling review", async ({ page, settingsFixture }) => {
  await settingsFixture.rpc("savePreference", "setDictationCleanupLevel", [""]);
  const before = await settingsFixture.rpc("snapshot");
  await settingsFixture.rpc("setAfterDictationTextAction", "translation", "de", before.textActionContext, before.textActionsRevision);
  await settingsFixture.rpc("selectWorkflow", "refinement");
  await settingsFixture.rpc("savePreference", "setRouteEnabled", [false]);
  await page.reload(); await page.getByRole("button", { name: "Estilo", exact: true }).click();
  const editing = page.getByRole("combobox", { name: "Edição do texto", exact: true });
  await expect(editing).toContainText("Tradução");
  await openDisclosure(page, "Mais opções");
  await expect(page.getByRole("button", { name: "Deutsch", exact: true })).toBeVisible();
  const unchanged = await settingsFixture.rpc("snapshot");
  expect(unchanged.dictationCleanupLevel).toBe("");
  expect(unchanged.afterDictationTextActionLanguage).toBe("de");
  await page.getByRole("combobox", { name: "Ação automática salva", exact: true }).click();
  await page.getByRole("option", { name: "Nenhuma", exact: true }).click();
  await expect(editing).toContainText("Melhorar a clareza");
  const saved = await settingsFixture.rpc("snapshot");
  expect(saved.dictationCleanupLevel).toBe("clarity");
  expect(saved.afterDictationTextActionId).toBe("");
  expect(saved.dictationCleanupRefinementAllowed).toBe(false);
  await editing.click();
  await expect(page.getByPlaceholder("Buscar edição do texto…", { exact: true })).toBeFocused();
  await expect(page.getByRole("option", { name: "Instruções atuais", exact: true })).toHaveCount(0);
  await expect(page.getByRole("option", { name: "Ajustes mínimos", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape"); await expect(editing).toBeFocused();
  await page.reload(); await page.getByRole("button", { name: "Estilo", exact: true }).click();
  await expect(editing).toContainText("Melhorar a clareza");
});

test("after dictation: translation keeps its selected revision and cancels when the catalog context changes", async ({ page, settingsFixture }) => {
  await page.getByRole("button", { name: "Estilo", exact: true }).click();
  await openDisclosure(page, "Mais opções");
  await page.getByRole("combobox", { name: "Ação automática salva", exact: true }).click();
  await page.getByRole("option", { name: "Aplicar ação de texto", exact: true }).click();
  const select = page.getByRole("combobox", { name: "Ação após o ditado", exact: true });
  await select.click(); await page.getByRole("option", { name: "Tradução", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Idioma da tradução", exact: true });
  const before = await settingsFixture.rpc("snapshot");
  const { revision: _revision, ...translation } = before.textActions!.find(action => action.id === "translation")!;
  await settingsFixture.rpc("saveTextAction", { ...translation, prompt: "New saved translation instructions." }, before.textActionContext, before.textActionsRevision);
  await dialog.getByRole("combobox", { name: "Idioma de destino", exact: true }).click();
  await page.getByRole("option", { name: "Inglês", exact: true }).click();
  await dialog.getByRole("button", { name: "Aplicar", exact: true }).click();
  await expect.poll(async () => (await settingsFixture.rpc("snapshot")).lastError).not.toBe("");
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog).toBeVisible();
  expect((await settingsFixture.rpc("snapshot")).afterDictationTextActionId).toBe("");
  await page.route("**/__test_rpc", async route => {
    const request = route.request().postDataJSON();
    const result = await settingsFixture.rpc(request.method, ...(request.args ?? []));
    await route.fulfill({ json: { result: { ...result, textActionContext: "changed-context" } } });
  });
  await expect(dialog).toBeHidden();
  await expect(select).toHaveCount(0);
  expect((await settingsFixture.rpc("snapshot")).afterDictationTextActionId).toBe("");
});


test("text tools: use a saved action without editing and reject stale output", async ({ page, settingsFixture }) => {
  await page.locator("aside nav").getByRole("button", { name: "Ações", exact: true }).click();
  await page.getByRole("button", { name: "Buscar ações", exact: true }).click();
  const search = page.getByRole("searchbox", { name: "Buscar ações", exact: true });
  await expect(search).toBeFocused();
  await search.fill("Reescrita");
  await expect(page.locator("#text-action-rewrite")).toBeVisible();
  await expect(page.locator("#text-action-translation")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Buscar ações", exact: true })).toBeFocused();
  await expect(page.locator("#text-action-translation")).toBeVisible();
  const row = page.locator("#text-action-rewrite");
  await row.getByRole("button", { name: "Usar ação: Reescrita", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /^Usar ação:/ });
  const input = dialog.getByRole("textbox", { name: "Texto de entrada", exact: true });
  await expect(input).toBeFocused();
  await expect(dialog.getByRole("textbox", { name: "Instruções da ação" })).toHaveCount(0);
  const before = (await settingsFixture.rpc("snapshot")).textActions;
  await input.fill("My actual text");
  await dialog.getByRole("button", { name: "Executar ação", exact: true }).click();
  await expect(dialog.getByRole("textbox", { name: "Resultado", exact: true })).toHaveValue(/My actual text/);
  await dialog.getByRole("button", { name: "Copiar resultado", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Copiado.", exact: true })).toBeVisible();
  await input.fill("Changed text");
  await expect(dialog.getByRole("textbox", { name: "Resultado", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Copiado.", exact: true })).toHaveCount(0);
  expect((await settingsFixture.rpc("snapshot")).textActions).toEqual(before);
  await dialog.getByRole("button", { name: "Concluído", exact: true }).click();
  await expect(row.getByRole("button", { name: "Usar ação: Reescrita", exact: true })).toBeFocused();
});


test("workspace: visual guides support steps, keyboard, reset, and focus without changing data", async ({ page, settingsFixture }) => {
  const before = await settingsFixture.rpc("snapshot");
  for (const name of ["Snippets", "Dicionário", "Ações"]) {
    await navigate(page, name);
    const trigger = page.getByRole("button", { name: "Como funciona", exact: true });
    await trigger.hover();
    await expect(page.getByRole("tooltip")).toHaveText("Como funciona");
    await trigger.click();
    const guide = page.getByRole("dialog", { name: "Como funciona: " + name, exact: true });
    await expect(guide).toBeVisible();
    await expect(guide.getByText("Etapa 1 de 3", { exact: true })).toBeVisible();
    await expect(guide.getByRole("button", { name: "Etapa anterior", exact: true })).toBeDisabled();
    await guide.getByRole("button", { name: "Próxima etapa", exact: true }).click();
    await expect(guide.getByText("Etapa 2 de 3", { exact: true })).toBeVisible();
    const transientOverflow = await guide.evaluate(root => {
      // Sample the start of the text transition, before a real scrollbar can flash.
      for (const animation of root.getAnimations({ subtree: true })) {
        if (animation instanceof CSSAnimation) { animation.pause(); animation.currentTime = 0; }
      }
      return root.scrollHeight - root.clientHeight;
    });
    expect(transientOverflow).toBeLessThanOrEqual(1);
    await guide.getByRole("button", { name: "Etapa anterior", exact: true }).click();
    await page.keyboard.press("ArrowRight");
    await expect(guide.getByText("Etapa 2 de 3", { exact: true })).toBeVisible();
    await page.keyboard.press("ArrowRight");
    await expect(guide.getByText("Etapa 3 de 3", { exact: true })).toBeVisible();
    await expect(guide.getByRole("button", { name: "Próxima etapa", exact: true })).toBeDisabled();
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(guide.locator(".guide-step-visual")).toHaveCSS("animation-name", "none");
    await guide.getByRole("button", { name: "Concluído", exact: true }).click();
    await expect(guide).toBeHidden();
    await expect(trigger).toBeFocused();
    await trigger.press("Enter");
    await expect(guide.getByText("Etapa 1 de 3", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(guide).toBeHidden();
    await expect(trigger).toBeFocused();
    await page.emulateMedia({ reducedMotion: "no-preference" });
  }
  const after = await settingsFixture.rpc("snapshot");
  expect(after.snippets).toEqual(before.snippets);
  expect(after.dictionaryEntries).toEqual(before.dictionaryEntries);
  expect(after.textActions).toEqual(before.textActions);
});


test("workspace: About owns version information and all page titles match Settings", async ({ page, settingsFixture }) => {
  const state = await settingsFixture.rpc("snapshot");
  const settings = await openSettings(page, "Dispositivos");
  const titleStyle = await settings.getByRole("heading", { name: "Dispositivos", exact: true }).evaluate(el => {
    const style = getComputedStyle(el); return [style.fontFamily, style.fontSize, style.fontWeight, style.lineHeight, style.letterSpacing];
  });
  await settings.getByRole("button", { name: "Sobre", exact: true }).click();
  await expect(settings.getByRole("heading", { name: "Sobre", exact: true })).toBeVisible();
  await expect(settings.locator(".about-page")).toContainText(state.applicationVersion);
  await expect(page.locator("#desktop-sidebar")).not.toContainText(state.applicationVersion);
  await settings.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(settings).toBeHidden();
  for (const name of ["Início", "Dicionário", "Snippets", "Estilo", "Ações"]) {
    await navigate(page, name);
    const title = page.locator("main .workspace-page-header h1");
    expect(await title.evaluate(el => {
      const style = getComputedStyle(el); return [style.fontFamily, style.fontSize, style.fontWeight, style.lineHeight, style.letterSpacing];
    })).toEqual(titleStyle);
  }
});


test("workspace: inline guides cycle all steps and preserve dismissal for every card", async ({ page }) => {
  await page.clock.install();
  await navigate(page, "Snippets");
  let card = page.locator(".feature-guide-card");
  await expect(card.getByRole("heading", { name: "Salve uma frase", exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: /Fechar guia/ })).toHaveCount(1);
  for (const title of ["Diga a frase", "Insira o texto salvo", "Salve uma frase"]) {
    await page.clock.fastForward(6001);
    await expect(card.getByRole("heading", { name: title, exact: true })).toBeVisible();
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.fastForward(18000);
  await expect(card.getByRole("heading", { name: "Salve uma frase", exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Etapa 3 de 3", exact: true }).click();
  await expect(card.getByRole("heading", { name: "Insira o texto salvo", exact: true })).toBeVisible();
  await expect(card.locator(".guide-card-scene")).toHaveCSS("animation-name", "none");
  for (const name of ["Snippets", "Dicionário", "Ações"]) {
    await navigate(page, name);
    card = page.locator(".feature-guide-card");
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "Fechar guia de " + name, exact: true }).click();
    await expect(card).toHaveCount(0);
    const info = page.getByRole("button", { name: "Como funciona", exact: true });
    await expect(info).toBeFocused();
    await info.press("Enter");
    const modal = page.getByRole("dialog", { name: "Como funciona: " + name, exact: true });
    await expect(modal).toBeVisible();
    await page.keyboard.press("Escape");await expect(modal).toBeHidden();
  }
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Bem-vindo de volta", exact: true })).toBeVisible();
  for (const name of ["Snippets", "Dicionário", "Ações"]) {
    await navigate(page, name);await expect(page.locator(".feature-guide-card")).toHaveCount(0);
  }
});
