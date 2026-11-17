import { test, expect } from "./settings-fixture";
import { mkdir, writeFile } from "node:fs/promises";
test.use({ settingsScenario: { onboarding: true, locale: "en" }, video: { mode: "on", size: { width: 1040, height: 760 } } });
async function advance(page: import("@playwright/test").Page, label = "Continue") {
  const setup = page.locator(".personal-setup");
  const step = await setup.count() ? await setup.getAttribute("data-step") : null;
  await page.getByRole("button", { name: label, exact: true }).click();
  if (step) await expect(setup).not.toHaveAttribute("data-step", step);
}
test("personal setup preserves choices, verifies assets, practices and offers phone pairing", async ({ page }, testInfo) => {
  const evidence = process.env.CLARIFY_TEST_ARTIFACTS_DIR || testInfo.outputPath("evidence");
  await mkdir(evidence, { recursive: true });
  const start = performance.now();
  await page.screenshot({ animations: "disabled", path: `${evidence}/welcome.png` });
  const wheel = page.getByRole("listbox", { name: "Interface language", exact: true });
  await wheel.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("heading", { name: "Escolha seu idioma" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Escolha seu idioma" })).toBeVisible();
  await page.getByRole("listbox", { name: "Idioma da interface" }).focus();
  await page.keyboard.press("Home");
  await expect(page.getByRole("heading", { name: "Choose your language" })).toBeVisible();
  const options = page.locator(".setup-language-options");
  await expect(options).toHaveAttribute("aria-disabled", "false");
  await options.hover();
  await page.mouse.wheel(0, 90);
  await expect(page.getByRole("heading", { name: "Escolha seu idioma" })).toBeVisible();
  await expect(options).toHaveAttribute("aria-disabled", "false");
  const bounds = (await options.boundingBox())!;
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2 - 60, { steps: 4 });
  await page.mouse.up();
  await expect(page.getByRole("heading", { name: "Elige tu idioma" })).toBeVisible();
  await expect(options).toHaveAttribute("aria-disabled", "false");
  await page.getByRole("option", { name: "English", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Choose your language" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  await expect(page.getByRole("option", { name: "English", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.screenshot({ animations: "disabled", path: `${evidence}/language.png` });
  await advance(page);
  await page.getByRole("radio", { name: /ChatGPT subscription/ }).focus();
  await page.keyboard.press("End");
  await expect(page.getByRole("radio", { name: /Keep the transcript/ })).toHaveAttribute("aria-checked", "true");
  await page.screenshot({ animations: "disabled", path: `${evidence}/choice.png` });
  await advance(page);
  await expect(page.getByRole("heading", { name: "A model for your voice" })).toBeFocused();
  await page.getByRole("combobox", { name: "Which languages do you speak?", exact: true }).click();
  await page.getByRole("option", { name: "Portuguese", exact: true }).click();
  await expect(page.getByText("Recommended", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2 })).toContainText("Whisper");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  await expect(page.getByText(/Download:.*MiB/)).not.toContainText("NaN");
  await page.screenshot({ animations: "disabled", path: `${evidence}/recommendation.png` });
  await page.getByRole("button", { name: "Other speech models", exact: true }).click();
  const model = page.getByRole("combobox", { name: "Speech model", exact: true });
  await expect(page.getByText(/150\.0 MiB maximum download/)).toBeVisible();
  for (const [name, id] of [
    [/Parakeet/, "parakeet-v3-int8"],
    [/Granite/, "granite-5-turboctc"],
    [/Turbo q5/, "ggml-turbo-q5"],
    [/Nemotron/, "nemotron-3.5-streaming"],
  ] as const) {
    await model.click();
    await expect(page.getByRole("option", { name: /Whisper Small|Whisper Medium/ })).toHaveCount(0);
    await page.getByRole("option", { name }).click();
    await expect.poll(async () => {
      const state = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
      return state.localModelIds[state.localProfileIndex];
    }).toBe(id);
    await expect(model).toBeEnabled();
    await model.focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("option", { name })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(model).toBeFocused();
    for (const width of [1040, 820, 640]) {
      await page.setViewportSize({ width, height: 760 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await page.screenshot({ animations: "disabled", path: `${evidence}/speech-${id}-${width}.png` });
    }
  }
  await model.click();
  await page.getByRole("option", { name: /Base/ }).click();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  let rejectedBrowse = false;
  const rejectBusyBrowse = async (route: import("@playwright/test").Route) => {
    if (route.request().postDataJSON().method !== "selectLocalProfile" || rejectedBrowse) return route.fallback();
    rejectedBrowse = true;
    return route.fulfill({ json: { error: "Model verification is still running." } });
  };
  await page.route("**/__test_rpc", rejectBusyBrowse);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Model verification is still running.");
  await expect(page.locator(".personal-setup")).toHaveAttribute("data-step", "speech");
  await page.unroute("**/__test_rpc", rejectBusyBrowse);
  await advance(page);
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.getByRole("button", { name: "Other speech models", exact: true }).click();
  await expect(model).toContainText("Base");
  await advance(page);
  for (const width of [1040, 820, 640]) {
    await page.setViewportSize({ width, height: 760 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ animations: "disabled", path: `${evidence}/install-${width}.png` });
  }
  await page.getByRole("button", { name: "Verify and try it", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Set up your dictation" })).toBeVisible();
  const state = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
  expect(state.onboardingRequired).toBe(false);
  expect(state.accountState.signedIn).toBe(false);
  expect(state.personalSetupState.language).toBe("pt");
  expect(state.language).not.toBe("pt");
  await advance(page);
  await page.evaluate(() => (window as any).__testSettings({ method: "practiceCommand", args: ["start"] }));
  await page.evaluate(() => (window as any).__testSettings({ method: "practiceCommand", args: ["stop"] }));
  await expect(page.getByRole("heading", { name: "Your dictation is ready" })).toBeVisible();
  await page.screenshot({ animations: "disabled", path: `${evidence}/practice.png` });
  await advance(page);
  await expect(page.getByRole("heading", { name: "Use your PC models on iPhone" })).toBeVisible();
  await page.screenshot({ animations: "disabled", path: `${evidence}/phone.png` });
  await writeFile(`${evidence}/ui-timing.json`, JSON.stringify({ fixtureFlowMilliseconds: performance.now() - start, resources: await page.evaluate(() => performance.getEntriesByType("resource").map(entry => { const item = entry as PerformanceResourceTiming; return { path: new URL(item.name).pathname, durationMilliseconds: item.duration, transferBytes: item.transferSize }; })), viewport: [1040, 820, 640], note: "Fake audio, installed fixture assets, local Python controller. No provider or model latency claim." }, null, 2));
});
test.describe("missing assets", () => {
  test.use({ settingsScenario: { onboarding: true, locale: "en", personalMissing: true } });
  test("completion cannot bypass backend verification", async ({ page }, testInfo) => {
    const evidence = process.env.CLARIFY_TEST_ARTIFACTS_DIR || testInfo.outputPath("evidence");
    await mkdir(evidence, { recursive: true });
    await page.evaluate(() => (window as any).__testSettings({ method: "personalSetupCommand", args: ["complete", JSON.stringify({ language: "auto", speechModelId: "ggml-base", textProvider: "none", textModelId: "" })] }));
    await expect(page.getByRole("alert")).toContainText("Install and verify");
    await page.setViewportSize({ width: 640, height: 520 });
    await page.screenshot({ animations: "disabled", path: `${evidence}/missing-model-error.png` });
    const state = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
    expect(state.onboardingRequired).toBe(true);
  });
});

test.describe("installation", () => {
  test.use({ settingsScenario: { onboarding: true, locale: "en", personalInstall: true } });
  test("install progress can be cancelled and retried before completion", async ({ page }, testInfo) => {
    const evidence = process.env.CLARIFY_TEST_ARTIFACTS_DIR || testInfo.outputPath("evidence");
    await mkdir(evidence, { recursive: true });
    await advance(page);
    await page.getByRole("radio", { name: /Keep the transcript/ }).click();
    for (const step of ["welcome", "speech"]) {
      await expect(page.locator(".personal-setup")).toHaveAttribute("data-step", step);
      await advance(page);
    }
    await page.getByRole("button", { name: "Download and install", exact: true }).click();
    await expect(page.getByRole("progressbar", { name: "Prepare your first dictation", exact: true })).toBeVisible();
    await page.screenshot({ animations: "disabled", path: `${evidence}/install-progress.png` });
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("progressbar", { name: "Prepare your first dictation", exact: true })).toBeHidden();
    await expect(page.getByRole("button", { name: "Verify and try it", exact: true })).toBeHidden();
    await page.getByRole("button", { name: "Download and install", exact: true }).click();
    await expect(page.getByRole("progressbar", { name: "Prepare your first dictation", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Verify and try it", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Set up your dictation", exact: true })).toBeVisible();
  });
});


test.describe("personal text catalogs", () => {
  test.use({ settingsScenario: { onboarding: true, locale: "en", personalCatalog: true } });
  test("ChatGPT and OpenCode use discovered rewriting models and save a separate speech route", async ({ page }, testInfo) => {
    const evidence = process.env.CLARIFY_TEST_ARTIFACTS_DIR || testInfo.outputPath("evidence");
    await mkdir(evidence, { recursive: true });
    await advance(page);
    await advance(page);
    await expect(page.getByRole("combobox", { name: "Rewriting model", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
    await page.screenshot({ animations: "disabled", path: `${evidence}/providers.png` });
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.getByRole("button", { name: "Continue with ChatGPT", exact: true }).click();
    await page.getByRole("button", { name: "Got it", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Continue", exact: true }).click();
    const model = page.getByRole("combobox", { name: "Rewriting model", exact: true });
    await model.click();
    await expect(page.getByRole("option", { name: "First account model", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(model).toBeFocused();
    await page.screenshot({ animations: "disabled", path: `${evidence}/chatgpt-connected.png` });
    await page.getByRole("radio", { name: /OpenCode free models/ }).click();
    await expect(model).toHaveCount(0);
    await page.getByRole("button", { name: "Check free models", exact: true }).click();
    await model.click();
    await page.getByRole("option", { name: "opencode/fixture-free-b", exact: true }).click();
    await page.screenshot({ animations: "disabled", path: `${evidence}/rewriting-model-picker.png` });
    await advance(page);
    await advance(page);
    await expect(page.locator(".setup-recommendation")).toContainText("opencode/fixture-free-b");
    await page.getByRole("button", { name: "Verify and try it", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Set up your dictation" })).toBeVisible();
    const tone = page.getByRole("combobox", { name: "Tone", exact: true });
    await tone.click();
    await page.getByRole("option", { name: "Formal", exact: true }).click();
    await expect(tone).toContainText("Formal");
    await page.screenshot({ animations: "disabled", path: `${evidence}/customization.png` });
    await page.reload();
    const state = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
    expect(state.onboardingRequired).toBe(false);
    expect(state.dictationWritingStyle).toBe("formal");
    const saved = state.personalSetupState.textOptions.find((option: any) => option.id === "opencode");
    expect(saved.modelId).toBe("opencode/fixture-free-b");
    await page.evaluate(() => (window as any).__testSettings({ method: "selectWorkflow", args: ["rewrite"] }));
    const rewrite = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
    expect([rewrite.routeProviderId, rewrite.routeModelId]).toEqual(["opencode", "opencode/fixture-free-b"]);
    await page.evaluate(() => (window as any).__testSettings({ method: "selectWorkflow", args: ["transcription"] }));
    const speech = await page.evaluate(() => (window as any).__testSettings({ method: "snapshot", args: [] }));
    expect([speech.routeProviderId, speech.routeModelId]).toEqual(["local_asr", "ggml-base"]);
  });
});

test.describe("optional text setup recovery", () => {
  test.use({ settingsScenario: { onboarding: true, locale: "pt", personalCatalogError: true } });
  test("provider errors can be retried or skipped, and API drafts do not block plain dictation", async ({ page }, testInfo) => {
    const evidence = process.env.CLARIFY_TEST_ARTIFACTS_DIR || testInfo.outputPath("evidence");
    await mkdir(evidence, { recursive: true });
    await page.setViewportSize({ width: 720, height: 640 });
    await advance(page, "Continuar");
    await page.getByRole("radio", { name: /Experimentar modelos gratuitos/ }).click();
    await advance(page, "Continuar");
    await page.getByRole("button", { name: "Consultar modelos gratuitos", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Não foi possível consultar os modelos do OpenCode");
    await expect(page.getByRole("combobox", { name: "Modelo de reescrita", exact: true })).toHaveCount(0);
    await page.screenshot({ animations: "disabled", path: `${evidence}/opencode-error-pt.png` });
    await page.getByRole("radio", { name: /Assinatura ChatGPT/ }).click();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await page.getByRole("button", { name: "Mais provedores", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Buscar provedores", exact: true }).fill("OpenAI");
    await expect(dialog.getByRole("button", { name: "Gemini", exact: true })).toHaveCount(0);
    await page.screenshot({ animations: "disabled", path: `${evidence}/more-providers.png` });
    await dialog.getByRole("button", { name: "OpenAI", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Endpoint", exact: true })).toBeHidden();
    await page.getByRole("button", { name: "Usar um servidor local ou outro endereço", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Endpoint", exact: true })).toBeVisible();
    for (const width of [640, 820, 1040]) {
      await page.setViewportSize({ width, height: 640 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await page.screenshot({ animations: "disabled", path: `${evidence}/api-connection-${width}-pt.png` });
    }
    await page.getByLabel("Chave de API", { exact: true }).fill("fixture-invalid-key");
    await page.getByRole("button", { name: "Validar e salvar chave", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("Invalid API key.");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Agora não", exact: true }).click();
    await expect(page.locator(".personal-setup")).toHaveAttribute("data-step", "speech");
    await advance(page, "Continuar");
    await expect(page.locator(".setup-recommendation")).toContainText("Manter a transcrição");
    await page.getByRole("button", { name: "Verificar e experimentar", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Vamos preparar seu ditado", exact: true })).toBeVisible();
  });
});
