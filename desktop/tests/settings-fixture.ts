import { test as base, expect } from "@playwright/test";
import { navigate } from "./settings-navigation";
import { SettingsProcess } from "./settings-process";

export type SettingsScenario = {
  locale?: "pt" | "en" | "es";
  onboarding?: boolean;
  personalMissing?: boolean;
  personalInstall?: boolean;
  personalCatalog?: boolean;
  personalConnected?: boolean;
  personalRuntimeMissing?: boolean;
  personalCatalogError?: boolean;
  signedIn?: boolean;
  account?: boolean;
  usage?: "error" | "legacy" | "malformed" | "waiting" | "unfunded" | "inactive" | "paused" | "exhausted" | "reserved";
  practice?: "account-error" | "auth-error" | "provider-quota" | "missing-model";
  socialWait?: boolean;
  librarySync?: boolean;
  history?: boolean;
  recordingRecovery?: boolean;
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
        await (window as any).__testSettings({ method: "accountCommand", args: ["refresh", ""] });
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
    if (scenario.personalCatalog) args.push("--personal-catalog", "--chatgpt");
    if (scenario.personalRuntimeMissing) args.push("--opencode-runtime-missing");
    if (scenario.personalConnected) args.push("--chatgpt-connected");
    if (scenario.personalCatalogError) args.push("--personal-catalog", "--personal-catalog-error", "--chatgpt");
    if (scenario.personalInstall) args.push("--personal-install");
    if (scenario.personalMissing) args.push("--personal-missing");
    if (scenario.practice) args.push(`--practice-${scenario.practice}`);
    if (scenario.onboarding) args.push("--onboarding");
    if (scenario.signedIn || scenario.account) args.push("--signed-in");
    if (scenario.socialWait) args.push("--social-wait");
    if (scenario.librarySync) args.push("--library-sync");
    if (scenario.history) args.push("--history");
    if (scenario.historyReview) args.push("--history-review");
    if (scenario.recordingRecovery) args.push("--recording-recovery");
    if (scenario.historyLarge) args.push("--history-large");
    if (scenario.usage && scenario.usage !== "reserved") args.push(`--usage-${scenario.usage}`);
    const controller = new SettingsProcess(python, args, { ...process.env, CLARIFY_TEST_UI_LANGUAGE: locale });
    const requests = new Set<Promise<void>>();
    try {
      if (scenario.account) await controller.request({ method: "accountCommand", args: ["logout", ""] });
      await page.route("**/__test_rpc", route => {
        const work = (async () => {
          const request = route.request().postDataJSON();
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
        const listeners = new Set<(message: any) => void>();
        const windowListeners = new Set<(event: string, target?: string) => void>();
        (window as any).__testDesktop = {
          state: (message: unknown) => listeners.forEach(listener => listener(message)),
          window: (event: string, target?: string) => windowListeners.forEach(listener => listener(event, target)),
        };
        (window as any).__testSettings = async (request: unknown) => {
          const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
          const result = await response.json(); if (result.error) throw result.error; return result.result;
        };
        (window as any).clarifyDesktop = {
          call: async (_channel: string, method: string, args: unknown[]) => (window as any).__testSettings({ method, args }),
          subscribe: (listener: (message: any) => void) => { listeners.add(listener); return () => listeners.delete(listener); },
          onWindow: (listener: (event: string, target?: string) => void) => { windowListeners.add(listener); return () => windowListeners.delete(listener); },
          ready: async () => {}, window: async () => {},
        };
        setInterval(() => {
          if (listeners.size) void (window as any).__testSettings({method:'poll',args:[]})
            .then((state: unknown) => listeners.forEach(listener => listener({event:'settings',state}))).catch(() => {});
        }, 150);
      });
      await page.goto("/");
      await expect(scenario.onboarding ? page.getByRole("heading", { name: locale === "en" ? "Choose your language" : locale === "es" ? "Elige tu idioma" : "Escolha seu idioma" }) : page.getByRole("heading", { name: locale === "en" ? "Welcome back" : locale === "es" ? "Bienvenido de nuevo" : "Bem-vindo de volta", exact: true })).toBeVisible({ timeout: 30000 });
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
