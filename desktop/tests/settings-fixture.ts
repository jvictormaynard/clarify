import { test as base, expect } from "@playwright/test";
import { navigate } from "./settings-navigation";
import { SettingsProcess } from "./settings-process";

export type SettingsScenario = {
  locale?: "pt" | "en" | "es";
  onboarding?: boolean;
  signedIn?: boolean;
  quota?: boolean;
  usage?: "error" | "legacy" | "malformed" | "waiting" | "unfunded" | "inactive" | "paused" | "exhausted" | "reserved";
  practice?: "account-error" | "auth-error" | "provider-quota";
  socialWait?: boolean;
  librarySync?: boolean;
  history?: boolean;
  historyReview?: boolean;
  historyLarge?: boolean;
  initialPage?: "style";
};

type Fixtures = { settingsApp: void; releaseUsage: () => Promise<void> };
export const test = base.extend<Fixtures & { settingsScenario: SettingsScenario }>({
  settingsScenario: [{}, { option: true }],
  screenshot: "only-on-failure",
  releaseUsage: async ({ page }, use) => {
    await use(async () => {
      await page.evaluate(async () => {
        await (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "accountCommand", args: ["refresh", ""] });
      });
    });
  },
  settingsApp: [async ({ page, settingsScenario: scenario }, use, testInfo) => {
    const actionTimeout = testInfo.timeout, setupStarted = performance.now();
    testInfo.setTimeout(actionTimeout + 30_000);
    const python = process.env.CLARIFY_TEST_PYTHON, fixture = process.env.CLARIFY_TEST_FIXTURE;
    if (!python || !fixture) throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE");
    const locale = scenario.locale ?? "pt";
    const args = ["-u", fixture];
    if (scenario.practice) args.push(`--practice-${scenario.practice}`);
    if (scenario.onboarding) args.push("--onboarding");
    if (scenario.signedIn || scenario.quota) args.push("--signed-in");
    if (scenario.socialWait) args.push("--social-wait");
    if (scenario.librarySync) args.push("--library-sync");
    if (scenario.history) args.push("--history");
    if (scenario.historyReview) args.push("--history-review");
    if (scenario.historyLarge) args.push("--history-large");
    if (scenario.usage && scenario.usage !== "reserved") args.push(`--usage-${scenario.usage}`);
    const controller = new SettingsProcess(python, args, { ...process.env, CLARIFY_TEST_UI_LANGUAGE: locale });
    const requests = new Set<Promise<void>>();
    try {
      await page.route("**/__test_rpc", route => {
        const work = (async () => {
          const request = route.request().postDataJSON();
          // Quota tests release the initial snapshot through an explicit refresh.
          if (scenario.quota && request.method === "accountCommand" && request.args[0] === "auto") {
            request.method = "snapshot"; request.args = [];
          }
          const reply = await controller.request(request);
          const usage = reply.result?.accountState?.usage;
          if (usage && scenario.usage === "reserved") {
            Object.assign(usage, { used_percent: 100, remaining_percent: 0, reserved_percent: 1, hosted_available: false });
          }
          await route.fulfill({ json: reply });
        })();
        requests.add(work);
        void work.then(() => requests.delete(work), () => requests.delete(work));
        return work;
      });
      await page.addInitScript(() => {
        (window as any).__TAURI_INTERNALS__ = { invoke: async (_command: string, request: unknown) => {
          const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
          const result = await response.json(); if (result.error) throw result.error; return result.result;
        } };
      });
      await page.goto("/");
      await expect(scenario.onboarding ? page.getByRole("heading", { name: locale === "en" ? "Welcome to Clarify" : locale === "es" ? "Te damos la bienvenida a Clarify" : "Boas-vindas ao Clarify" }) : page.getByRole("heading", { name: locale === "en" ? "Welcome back" : locale === "es" ? "Bienvenido de nuevo" : "Bem-vindo de volta", exact: true })).toBeVisible({ timeout: 30000 });
      await expect(page.getByRole("button", { name: "Salvar alterações" })).toBeHidden();
      if (scenario.initialPage === "style") await navigate(page, locale === "en" ? "Style" : "Estilo");
      testInfo.setTimeout(actionTimeout + Math.ceil(performance.now() - setupStarted));
      await use();
    } finally {
      try {
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await page.close();
      } finally {
        await controller.stop();
        await Promise.allSettled(requests);
      }
    }
  }, { auto: true, timeout: 65_000 }],
});

// Anonymous groups let loop cases declare options without changing test names.
export function settingsScenario(options: SettingsScenario, defineTests: () => void) {
  test.describe(() => {
    test.use({ settingsScenario: options });
    defineTests();
  });
}
export { expect };
