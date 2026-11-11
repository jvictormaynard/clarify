import { test, expect, settingsScenario } from "./settings-fixture";
import { navigate, openSettings } from "./settings-navigation";

settingsScenario({ history: true }, () => {
  test("history: correction requires review and supports owned undo", async ({ page }, testInfo) => {
    await navigate(page, "Histórico");
    await page.getByRole("button", { name: "Buscar no histórico", exact: true }).click();
    const search = page.getByRole("searchbox", { name: "Buscar no histórico", exact: true });
    await search.fill("Isolated revised desktop history.");
    await expect(page.getByRole("listitem")).toHaveCount(1);
    const row = page.locator(".history-row").filter({ hasText: "Isolated revised desktop history." });
    await expect(row).toBeVisible();
    if (await row.getByRole("button", { name: "Abrir textos", exact: true }).count()) await row.getByRole("button", { name: "Abrir textos", exact: true }).click();
    await row.getByRole("button", { name: "Corrigir termo", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Corrigir termo", exact: true });
    await dialog.getByRole("textbox", { name: "Termo ouvido", exact: true }).fill("desktop");
    await dialog.getByRole("textbox", { name: "Termo correto", exact: true }).click();
    await expect(page.locator(".page-search input")).toHaveValue("Isolated revised desktop history.");
    await dialog.getByRole("textbox", { name: "Termo correto", exact: true }).fill("Desktop Term");
    await dialog.getByRole("button", { name: "Revisar correção", exact: true }).click();
    await expect(dialog.getByRole("textbox", { name: "Termo ouvido", exact: true })).toHaveValue("desktop");
    await expect(dialog.getByRole("textbox", { name: "Termo correto", exact: true })).toBeDisabled();
    const snapshot = () => page.evaluate(async () => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
    expect((await snapshot()).dictionaryEntries).toEqual([]);
    await page.setViewportSize({ width: 640, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(640);
    await page.screenshot({ path: testInfo.outputPath("correction-review-640.png") });
    await dialog.getByRole("button", { name: "Salvar no dicionário", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(row.getByRole("button", { name: "Desfazer adição", exact: true })).toBeEnabled();
    expect((await snapshot()).dictionaryEntries).toEqual([{ term: "Desktop Term", pronunciation: "", aliases: ["desktop"], enabled: true }]);
    await row.getByRole("button", { name: "Desfazer adição", exact: true }).click();
    await expect(row.getByText("Adição desfeita.", { exact: true })).toBeVisible();
    expect((await snapshot()).dictionaryEntries).toEqual([]);
    await expect(row.getByRole("region", { name: "Original", exact: true })).toContainText("Isolated desktop history.");
  });

});

settingsScenario({ history: true }, () => {
  test("history: correction cancel has no effect and external edits disable undo", async ({ page }) => {
    await navigate(page, "Histórico");
    const row = page.locator(".history-row").filter({ hasText: "Isolated revised desktop history." });
    const dialog = page.getByRole("dialog", { name: "Corrigir termo", exact: true });
    const review = async () => {
      await expect(row).toBeVisible();
      if (await row.getByRole("button", { name: "Abrir textos", exact: true }).count()) await row.getByRole("button", { name: "Abrir textos", exact: true }).click();
      await row.getByRole("button", { name: "Corrigir termo", exact: true }).click();
      await dialog.getByRole("textbox", { name: "Termo ouvido", exact: true }).fill("desktop");
      await dialog.getByRole("textbox", { name: "Termo correto", exact: true }).fill("Desktop Term");
      await dialog.getByRole("button", { name: "Revisar correção", exact: true }).click();
      await expect(dialog.getByRole("button", { name: "Salvar no dicionário", exact: true })).toBeVisible();
    };
    await review();
    await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
    const before = await page.evaluate(async () => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
    expect(before.dictionaryEntries).toEqual([]);
    await review();
    await dialog.getByRole("button", { name: "Salvar no dicionário", exact: true }).click();
    await expect(row.getByRole("button", { name: "Desfazer adição", exact: true })).toBeEnabled();
    await page.evaluate(async () => {
      const invoke = (method: string, args: unknown[]) => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method, args });
      const state = await invoke("snapshot", []);
      await invoke("setDictionaryEntries", [[{ ...state.dictionaryEntries[0], pronunciation: "Later edit" }], state.snippetContext]);
      await invoke("save", [state.snippetContext]);
    });
    await expect(row.getByRole("button", { name: "Desfazer adição", exact: true })).toBeDisabled();
    await expect(row.getByText("Desfazer indisponível: o dicionário ou a sessão mudou.", { exact: true })).toBeVisible();
  });

});

for (const [localTerm, correctedTerm] of [["Desktop Term", "Desktop Term"], ["Straße", "STRASSE"]]) settingsScenario({ history: true }, () => {
  test(`history: correction reuses unsaved ${localTerm}/${correctedTerm} and keeps pending metadata`, async ({ page }) => {
    await navigate(page, "Dicionário");
    await page.getByRole("textbox", { name: "Novo termo", exact: true }).fill(localTerm);
    await page.getByRole("button", { name: "Adicionar termo", exact: true }).click();
    const pronunciation = page.getByRole("button", { name: "Pronúncia e variações", exact: true });
    await pronunciation.focus();
    await page.keyboard.press("Enter");
    const pronunciationInput = page.getByRole("textbox", { name: "Pronúncia do termo 1", exact: true });
    await pronunciationInput.fill("Pending pronunciation");
    await pronunciation.focus();
    await page.keyboard.press("Space");
    await expect(pronunciation).toHaveAttribute("aria-expanded", "false");
    await expect(pronunciation).toBeFocused();
    await expect(pronunciationInput).toBeHidden();
    await page.keyboard.press("Enter");
    await expect(pronunciationInput).toHaveValue("Pending pronunciation");
    await navigate(page, "Histórico");
    const row = page.locator(".history-row").filter({ hasText: "Isolated revised desktop history." });
    await row.getByRole("button", { name: "Corrigir termo", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Corrigir termo", exact: true });
    await dialog.getByRole("textbox", { name: "Termo ouvido", exact: true }).fill("desktop");
    await dialog.getByRole("textbox", { name: "Termo correto", exact: true }).fill(correctedTerm);
    await dialog.getByRole("button", { name: "Revisar correção", exact: true }).click();
    await dialog.getByRole("button", { name: "Salvar no dicionário", exact: true }).click();
    await expect(dialog).toBeHidden();
    await navigate(page, "Dicionário");
    await expect(page.getByRole("textbox", { name: "Termo 1", exact: true })).toHaveValue(localTerm);
    await expect(page.getByRole("textbox", { name: "Termo 2", exact: true })).toHaveCount(0);
    await page.getByText("Pronúncia e variações", { exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Pronúncia do termo 1", exact: true })).toHaveValue("Pending pronunciation");
    await expect(page.getByRole("textbox", { name: "Variações do termo 1", exact: true })).toHaveValue("desktop");
    await page.getByRole("button", { name: "Salvar alterações", exact: true }).click();
    await expect(page.getByRole("button", { name: "Salvar alterações", exact: true })).toBeHidden();
    const saved = await page.evaluate(async () => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
    expect(saved.dictionaryEntries).toEqual([{ term: localTerm, pronunciation: "Pending pronunciation", aliases: ["desktop"], enabled: true }]);
  });
});

settingsScenario({ history: true }, () => {
  test("history: existing records stay visible and local delete and clear update the list", async ({ page }) => {
    await navigate(page, "Histórico");
    await expect(page.getByText("Isolated mobile history.", { exact: true })).toBeVisible();
    await expect(page.getByText("Isolated revised desktop history.", { exact: true })).toBeVisible();
    const items = page.getByRole("listitem");
    await expect(items).toHaveCount(2);
    await items.first().getByRole("button", { name: "Abrir textos", exact: true }).click();
    await expect(items.first()).toContainText("Mobile");
    await items.last().getByRole("button", { name: "Abrir textos", exact: true }).click();
    await expect(items.last()).toContainText("Desktop");
    await items.last().getByRole("button", { name: "Fechar textos", exact: true }).click();
    await items.first().getByRole("button", { name: "Excluir transcrição", exact: true }).click();
    await page.getByRole("dialog", { name: /^(Excluir transcrição|Limpar histórico)$/ }).getByRole("button", { name: "Excluir", exact: true }).click();
    await expect(items).toHaveCount(1);
    await openSettings(page, "Privacidade");
  await page.getByRole("button", { name: "Limpar histórico", exact: true }).click();
    await page.getByRole("dialog", { name: /^(Excluir transcrição|Limpar histórico)$/ }).getByRole("button", { name: "Excluir", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Configurações", exact: true })).toBeVisible();
  await navigate(page, "Histórico");
  await expect(page.getByText("Nenhuma transcrição ainda.", { exact: true })).toBeVisible();
  });

});

settingsScenario({ historyLarge: true, history: true }, () => {
  test("history: large history loads bounded pages and full legacy text without blocking Settings", async ({ page }) => {
    test.setTimeout(60000);
    await page.clock.setFixedTime(new Date("2026-10-16T15:00:00Z"));
    const anchors = await page.evaluate(() => [new Date(2026, 9, 16, 0, 49).getTime() / 1000, new Date(2026, 9, 15, 23).getTime() / 1000]);
    await navigate(page, "Estilo");
    await page.evaluate(anchors => {
      const runtime = (window as any).__TAURI_INTERNALS__;
      const invoke = runtime.invoke;
      runtime.invoke = async (command: string, request: any) => {
        const result = await invoke(command, request);
        if (request.method === "getHistoryPage") for (const entry of result.entries) {
          const timestamp = entry.timestamp;
          const today = timestamp >= Date.UTC(2026, 9, 16, 14, 25) / 1000;
          entry.timestamp = anchors[today ? 0 : 1] + timestamp - Date.UTC(2026, 9, 16, 14, today ? 25 : 0) / 1000;
        }
        return result;
      };
    }, anchors);
    await navigate(page, "Histórico");
    await expect(page.getByRole("listitem")).toHaveCount(20);
    await expect(page.locator(".history-day")).toHaveCount(1);
    await expect(page.locator(".history-date")).toHaveText("Hoje");
    await page.getByRole("listitem").first().getByRole("button", { name: "Abrir textos", exact: true }).click();
    const reader = page.getByRole("region", { name: "Resultado", exact: true });
    await expect(reader.locator(".history-text")).toHaveText(("Giant legacy " + "x".repeat(1100000)).slice(0, 600) + "…");
    await reader.getByRole("button", { name: "Ler mais", exact: true }).click();
    const fullText = page.getByRole("dialog", { name: "Resultado", exact: true });
    await expect(fullText.locator(".history-full-text")).toHaveText(("Giant legacy " + "x".repeat(1100000)).slice(0, 4000));
    await fullText.locator(".history-full-reader").evaluate(element => { element.scrollTop = element.scrollHeight; });
    await expect(fullText.locator(".history-full-text")).toHaveText(("Giant legacy " + "x".repeat(1100000)).slice(0, 8000));
    await fullText.getByRole("button", { name: "Fechar", exact: true }).click();
    await expect(fullText).toBeHidden();
    await expect(reader.getByRole("button", { name: "Ler mais", exact: true })).toBeFocused();
    await page.getByRole("button", { name: "Carregar mais", exact: true }).click();
    await expect(page.getByRole("listitem")).toHaveCount(40);
    await expect(page.locator(".history-day")).toHaveCount(2);
    await expect(page.locator(".history-date").last()).toHaveText("15 de out.");
    await expect(page.locator(".history-list").first().getByRole("listitem")).toHaveCount(21);
    await page.getByRole("button", { name: "Carregar mais", exact: true }).click();
    await expect(page.getByRole("listitem")).toHaveCount(48);
    await expect(page.locator(".history-day")).toHaveCount(2);
    await expect(page.locator(".history-list").last().getByRole("listitem")).toHaveCount(27);
    await expect(page.getByRole("button", { name: "Carregar mais", exact: true })).toBeHidden();
    await navigate(page, "Privacidade");
    await expect(page.getByText("Salvar histórico", { exact: true })).toBeVisible();
  });

});

settingsScenario({ history: true }, () => {
  test("history: session context changes close a stale delete dialog", async ({ page }) => {
    await navigate(page, "Histórico");
    await expect(page.getByRole("listitem")).toHaveCount(2);
    await openSettings(page, "Privacidade");
  await page.getByRole("button", { name: "Limpar histórico", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Limpar histórico", exact: true })).toBeVisible();
    await page.evaluate(() => fetch("/__test_rpc", { method: "POST", body: JSON.stringify({ method: "testHistoryContextChange", args: [] }) }));
    await expect(page.getByRole("dialog", { name: "Limpar histórico", exact: true })).toBeHidden();
    await expect(page.getByRole("dialog", { name: "Configurações", exact: true })).toBeVisible();
    await navigate(page, "Histórico");
    await expect(page.getByRole("listitem")).toHaveCount(2);
  });
});

settingsScenario({ historyReview: true, history: true }, () => {
  test("history: review tools compare preserved texts and recover from clipboard failure", async ({ page }, testInfo) => {
    await navigate(page, "Histórico");
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
    const copied = revised.getByRole("button", { name: "Copiado.", exact: true });
    await expect(copied).toBeVisible();
    await expect(revised.getByText("Copiado.", { exact: true })).toHaveCount(0);
    await expect(copied.locator("svg")).toHaveClass(/lucide-check/);
    await expect(revised.getByRole("button", { name: "Copiar resultado", exact: true })).toBeVisible();
    await expect(revised.getByRole("button", { name: "Copiar original", exact: true })).toHaveCount(0);
    await expect.poll(() => page.evaluate(async () => (await (await fetch("/__test_rpc", { method: "POST", body: JSON.stringify({ method: "testHistoryClipboard", args: [] }) })).json()).result)).toEqual(["Isolated revised desktop history."]);
    const same = page.getByRole("listitem").filter({ hasText: "Isolated mobile history." });
    await same.getByRole("button", { name: "Abrir textos", exact: true }).click();
    await expect(same).toContainText("O original e o resultado são iguais.");
    const absent = page.getByRole("listitem").filter({ hasText: "Result without original." });
    await absent.getByRole("button", { name: "Abrir textos", exact: true }).click();
    await expect(absent).toContainText("O original não está disponível para este registro.");
    await expect(absent.getByRole("button", { name: "Copiar original", exact: true })).toHaveCount(0);
  });

});

settingsScenario({ historyLarge: true, history: true }, () => {
  test("history: large history search reaches older originals and never reports partial scan as empty", async ({ page }) => {
    await navigate(page, "Histórico");
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
    await page.getByRole("button", { name: "Buscar no histórico", exact: true }).click();
    const search = page.getByRole("searchbox", { name: "Buscar no histórico", exact: true });
    await expect(search).toBeFocused();
    let result = await scan(() => search.fill(queries[0]), queries[0]);
    for (let i = 0; i < 20 && result.hasMore && !result.entries.length; i++) {
      result = await scan(() => more.click(), queries[0], result.cursor);
    }
    await expect(page.getByText("Isolated revised desktop history.", { exact: true })).toBeVisible();
    await expect(page.getByRole("listitem")).toHaveCount(1);
    result = await scan(() => search.fill(queries[1]), queries[1]);
    for (let i = 0; i < 20 && result.hasMore; i++) {
      result = await scan(() => more.click(), queries[1], result.cursor);
    }
    await expect(empty).toBeVisible();
    await search.focus();
    await page.keyboard.press("Escape");
    await expect(search).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Buscar no histórico", exact: true })).toBeFocused();
    await expect(page.getByRole("listitem")).toHaveCount(20);
    await page.getByRole("button", { name: "Buscar no histórico", exact: true }).click();
    await search.fill("not found");
    await expect(more).toBeVisible();
    await page.getByRole("heading", { name: "Bem-vindo de volta", exact: true }).click();
    await expect(search).toHaveCount(0);
    await expect(page.getByRole("listitem")).toHaveCount(20);
  });

});

settingsScenario({ history: true }, () => {
  test("history: cancelled expansion ignores late text and context change closes comparison", async ({ page }) => {
    await navigate(page, "Histórico");
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
});
