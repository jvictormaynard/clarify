import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import { navigate, openStyleReview } from "./settings-navigation";

let child: ChildProcessWithoutNullStreams;
let id = 0;
const pending = new Map<number, (value: unknown) => void>();
type SessionObservation = {
  clientId: string; authorizationClientId: string; accountId: string;
  accountCount: number; refreshPending: boolean; planNoticeSeen: boolean;
};
let sessionObservations: SessionObservation[] = [];
let commands: { method: string; args?: unknown[] }[] = [];

// Keep the real saved-registration and refresh behavior behind offline OAuth seams.
const reconnectFixture = String.raw`
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

fixture = Path(sys.argv[1])
sys.path[:0] = [str(fixture.parent), str(fixture.parent.parent)]
from chatgpt_auth import ChatGPTPlanError, ChatGPTPlanSession
from secret_store import MemorySecretStore
from test_chatgpt_auth import Listener, OAuthServer, rsa
import test_chatgpt_settings
import web_settings_fixture

with TemporaryDirectory() as directory:
    server = OAuthServer(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    store = MemorySecretStore()

    class SavedSession(ChatGPTPlanSession):
        def __init__(self):
            super().__init__(Path(directory), secret_store=store, http=server,
                clock=lambda: server.now,
                listener_factory=lambda: Listener(server.callback))
            super().sign_in(open_browser=server.browser)
            server.now += 3570
            server.fail_refresh = True
            try:
                self.credential()
            except ChatGPTPlanError as error:
                assert error.code == "refresh_failed"
            else:
                raise AssertionError("Expected an uncertain refresh")
            self.report()

        @property
        def state(self):
            return self.snapshot()

        def sign_in(self, *, open_browser, **kwargs):
            super().sign_in(open_browser=server.browser, **kwargs)
            self.report()

        def report(self):
            saved = json.loads(store.get("chatgpt"))
            record = saved["accounts"][saved["active"]]
            web_settings_fixture.emit_fixture(dict(event="chatgpt_session", state=dict(
                clientId=record["client_id"],
                authorizationClientId=server.query["client_id"][0],
                accountId=saved["active"], accountCount=len(saved["accounts"]),
                refreshPending=bool(record.get("refresh_pending")),
                planNoticeSeen=record.get("plan_notice_seen", False),
            )))

    test_chatgpt_settings.FakeChatGPTSession = SavedSession
    raise SystemExit(web_settings_fixture.main())
`;

const recoveryFixture = String.raw`
import sys
import threading
from pathlib import Path

fixture = Path(sys.argv[1])
sys.path[:0] = [str(fixture.parent), str(fixture.parent.parent)]
from chatgpt_auth import ChatGPTPlanError
import test_chatgpt_settings
import web_settings_fixture

class RecoverySession(test_chatgpt_settings.FakeChatGPTSession):
    def __init__(self):
        super().__init__()
        super().sign_in(open_browser=lambda _: None)
        self.acknowledge_plan_notice()
        self.wait = threading.Event()
        self.attempts = 0

    def sign_in(self, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            raise ChatGPTPlanError("Synthetic network failure", code="network")
        super().sign_in(**kwargs)

test_chatgpt_settings.FakeChatGPTSession = RecoverySession
raise SystemExit(web_settings_fixture.main())
`;

test.beforeEach(async ({ page }, info) => {
  if (!process.env.CLARIFY_TEST_PYTHON || !process.env.CLARIFY_TEST_FIXTURE)
    throw new Error("Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE");
  sessionObservations = [];
  commands = [];
  const fixture = info.title.includes("reauthorizes")
    ? ["-c", reconnectFixture, process.env.CLARIFY_TEST_FIXTURE]
    : info.title.includes("failed reconnection")
    ? ["-c", recoveryFixture, process.env.CLARIFY_TEST_FIXTURE]
    : [process.env.CLARIFY_TEST_FIXTURE];
  child = spawn(process.env.CLARIFY_TEST_PYTHON, ["-u", ...fixture,
    "--chatgpt", ...(info.title.includes("permission") ? ["--chatgpt-no-plan"] : []),
    ...(info.title.includes("cancellation") ? ["--chatgpt-wait"] : []),
    ...(info.title.includes("Clarify account") ? ["--signed-in"] : []),
  ], { windowsHide: true, env: { ...process.env, CLARIFY_TEST_UI_LANGUAGE: "en" } });
  child.stderr.on("data", data => process.stderr.write(data));
  createInterface({ input: child.stdout }).on("line", line => {
    const reply = JSON.parse(line);
    if (reply.event === "chatgpt_session") {
      sessionObservations.push(reply.state);
      return;
    }
    pending.get(reply.id)?.(reply); pending.delete(reply.id);
  });
  await page.route("**/__test_rpc", async route => {
    const key = ++id;
    commands.push(route.request().postDataJSON());
    const result = new Promise(resolve => pending.set(key, resolve));
    child.stdin.write(JSON.stringify({ id: key, ...route.request().postDataJSON() }) + "\n");
    await route.fulfill({ json: await result });
  });
  await page.addInitScript(() => {
    (window as any).__TAURI_INTERNALS__ = { invoke: async (_: string, request: unknown) => {
      const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
      const reply = await response.json(); if (reply.error) throw reply.error; return reply.result;
    } };
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dictation", exact: true })).toBeVisible({ timeout: 30000 });
});

test.afterEach(async () => {
  child?.stdin.end(JSON.stringify({ method: "quit" }) + "\n");
  pending.clear();
});

async function snapshot(page: Page) {
  return page.evaluate(() => (window as any).__TAURI_INTERNALS__.invoke("settings_call", { method: "snapshot", args: [] }));
}

async function selectChatGPT(page: Page) {
  await navigate(page, "Models and services");
  await page.getByRole("combobox", { name: "Cloud service", exact: true }).click();
  await page.getByRole("option", { name: "ChatGPT (subscription)", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "API key", exact: true })).toHaveCount(0);
  await expect(page.getByText("Custom endpoint", { exact: true })).toHaveCount(0);
}

test("ChatGPT connects without API keys, refreshes account catalogs and persists notice acknowledgement", async ({ page }, info) => {
  await selectChatGPT(page);
  await expect(page.getByText(/Audio transcription is excluded/)).toBeVisible();
  await expect(page.getByRole("button", { name: "ChatGPT account options", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Manage usage in ChatGPT", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Continue with ChatGPT", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "You're using your ChatGPT plan", exact: true })).toContainText("You're using your ChatGPT plan");
  await page.getByRole("dialog", { name: "You're using your ChatGPT plan", exact: true }).getByRole("button", { name: "Got it", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "You're using your ChatGPT plan", exact: true })).toBeHidden();
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toContainText("Personal");
  await expect(page.getByRole("button", { name: "Continue with ChatGPT", exact: true })).toHaveCount(0);
  expect((await snapshot(page)).dirty).toBe(false);
  await page.getByRole("button", { name: "Manage usage in ChatGPT", exact: true }).click();
  const menu = page.getByRole("button", { name: "ChatGPT account options", exact: true });
  await expect(menu).toBeEnabled();
  await menu.focus();
  await expect(menu).toBeFocused();
  await menu.press("Enter");
  await expect(page.getByRole("menuitem", { name: "Add ChatGPT account", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Reconnect ChatGPT", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Refresh ChatGPT models", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Sign out of ChatGPT", exact: true })).toBeFocused();
  await expect(page.getByRole("menu").getByRole("separator")).toHaveCount(1);
  await page.screenshot({ path: info.outputPath("chatgpt-account-menu-synthetic.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(menu).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await menu.click();
  const popup = page.getByRole("menu");
  await expect(popup).toBeVisible();
  const bounds = await popup.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("chatgpt-account-menu-narrow-synthetic.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await page.screenshot({ path: info.outputPath("chatgpt-connected-narrow-synthetic.png"), fullPage: true });
  await page.setViewportSize({ width: 1040, height: 760 });
  await menu.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Add ChatGPT account", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Reconnect ChatGPT", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Refresh ChatGPT models", exact: true })).toBeFocused();
  const validations = commands.filter(command => command.method === "validateProvider").length;
  await page.keyboard.press("Enter");
  await expect.poll(() => commands.filter(command => command.method === "validateProvider").length).toBe(validations + 1);
  await expect(page.getByRole("menu")).toHaveCount(0);
  await expect(menu).toBeEnabled();
  await openStyleReview(page, "en");
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await page.getByRole("option", { name: "ChatGPT (subscription)", exact: true }).click();
  await page.getByRole("combobox", { name: "Model", exact: true }).click();
  await expect(page.getByRole("option")).toHaveText(["First account model", "Second account model"]);
  await page.getByRole("option", { name: "Second account model", exact: true }).click();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCount(0);
  expect((await snapshot(page)).routeModelId).toBe("personal-a");
  await expect(page.getByText("Custom model and endpoint", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("chatgpt-text-synthetic.png"), fullPage: true });
  await navigate(page, "Models and services");
  await menu.click();
  await page.getByRole("menuitem", { name: "Add ChatGPT account", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toContainText("Second");
  await page.getByRole("combobox", { name: "ChatGPT account", exact: true }).click();
  await page.getByRole("option", { name: "demo@example.test · Personal", exact: true }).click();
  await expect(page.locator('[data-slot="combobox-popup"]')).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toContainText("Personal");
  expect((await snapshot(page)).chatgptState.planNoticeSeen).toBe(true);
  await page.getByRole("button", { name: "Manage usage in ChatGPT", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("chatgpt-models-synthetic.png"), fullPage: true });
  await openStyleReview(page, "en");
  await expect(page.getByRole("combobox", { name: "Model", exact: true })).toContainText("Select");
  await page.getByRole("combobox", { name: "Model", exact: true }).click();
  await page.getByRole("option", { name: "First account model", exact: true }).click();
  expect((await snapshot(page)).routeModelId).toBe("personal-z");
  await navigate(page, "Models and services");
  await menu.click();
  await page.getByRole("menuitem", { name: "Sign out of ChatGPT", exact: true }).click();
  await expect(page.getByText("ChatGPT not connected", { exact: true })).toBeVisible();
  await openStyleReview(page, "en");
  expect((await snapshot(page)).routeModelOptions).toEqual([]);
  expect((await snapshot(page)).routeModelId).toBe("");
  await navigate(page, "Dictation");
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await expect(page.getByRole("option", { name: "ChatGPT (subscription)", exact: true })).toHaveCount(0);
});

test("ChatGPT reauthorizes a connected saved account with the same client after an uncertain refresh", async ({ page }, info) => {
  expect(sessionObservations).toHaveLength(1);
  const saved = sessionObservations[0];
  expect(saved).toMatchObject({
    clientId: "oaiapp_first", authorizationClientId: "dynamic_agent_client",
    accountCount: 1, refreshPending: true, planNoticeSeen: false,
  });
  await selectChatGPT(page);
  const notice = page.getByRole("dialog", { name: "You're using your ChatGPT plan", exact: true });
  await expect(notice).toBeVisible();
  await notice.getByRole("button", { name: "Got it", exact: true }).click();
  await expect(notice).toBeHidden();
  const before = (await snapshot(page)).chatgptState;
  expect(before).toMatchObject({ connected: true, planEnabled: true, planNoticeSeen: true, accountId: saved.accountId });
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Continue with ChatGPT", exact: true })).toHaveCount(0);
  const menu = page.getByRole("button", { name: "ChatGPT account options", exact: true });
  await expect(page.getByRole("button", { name: "Manage usage in ChatGPT", exact: true })).toBeEnabled();
  await menu.click();
  for (const name of ["Add ChatGPT account", "Sign out of ChatGPT", "Refresh ChatGPT models"])
    await expect(page.getByRole("menuitem", { name, exact: true })).toBeEnabled();
  const reconnect = page.getByRole("menuitem", { name: "Reconnect ChatGPT", exact: true });
  await expect(reconnect).toBeEnabled();
  await reconnect.click();
  await expect.poll(() => sessionObservations.length).toBe(2);
  await expect(menu).toBeEnabled();
  expect(sessionObservations[1]).toEqual({
    clientId: saved.clientId, authorizationClientId: saved.clientId, accountId: saved.accountId,
    accountCount: 1, refreshPending: false, planNoticeSeen: true,
  });
  expect((await snapshot(page)).chatgptState).toMatchObject({
    connected: true, planEnabled: true, busy: false, accountId: before.accountId,
    accounts: before.accounts, planNoticeSeen: true,
  });
  await expect(notice).toBeHidden();
  await page.screenshot({ path: info.outputPath("chatgpt-reconnect-synthetic.png"), fullPage: true });
});

test("ChatGPT identity without plan permission does not enable text models", async ({ page }) => {
  await selectChatGPT(page);
  await expect(page.getByText("Account connected. ChatGPT plan use is not allowed.", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "You're using your ChatGPT plan", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reconnect ChatGPT", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "ChatGPT account options", exact: true }).click();
  await expect(page.getByRole("menuitem", { name: "Reconnect ChatGPT", exact: true })).toBeEnabled();
  await expect(page.getByRole("menuitem", { name: "Refresh ChatGPT models", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
  expect((await snapshot(page)).chatgptState.planEnabled).toBe(false);
  await openStyleReview(page, "en");
  await page.getByRole("combobox", { name: "Service", exact: true }).click();
  await page.getByRole("option", { name: "ChatGPT (subscription)", exact: true }).click();
  expect((await snapshot(page)).routeModelStatus).toBe("not_configured");
});

test("ChatGPT sign-in cancellation leaves the account disconnected", async ({ page }) => {
  await selectChatGPT(page);
  await page.getByRole("button", { name: "Continue with ChatGPT", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue with ChatGPT", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "ChatGPT account options", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Continue with ChatGPT", exact: true })).toBeVisible();
  expect((await snapshot(page)).chatgptState.connected).toBe(false);
});

test("ChatGPT failed reconnection and cancellation preserve the saved account", async ({ page }, info) => {
  await selectChatGPT(page);
  const before = (await snapshot(page)).chatgptState;
  await page.getByRole("button", { name: "ChatGPT account options", exact: true }).click();
  await page.getByRole("menuitem", { name: "Reconnect ChatGPT", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Could not connect to ChatGPT. Check your connection and try again.");
  const reconnect = page.getByRole("button", { name: "Reconnect ChatGPT", exact: true });
  await expect(reconnect).toBeEnabled();
  await expect(page.getByRole("button", { name: "Continue with ChatGPT", exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("chatgpt-reconnect-error-synthetic.png"), fullPage: true });
  await reconnect.click();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeEnabled();
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "ChatGPT account options", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "ChatGPT account options", exact: true })).toBeEnabled();
  await expect(page.getByRole("combobox", { name: "ChatGPT account", exact: true })).toBeEnabled();
  expect((await snapshot(page)).chatgptState).toMatchObject({
    connected: true, planEnabled: true, busy: false,
    accountId: before.accountId, accounts: before.accounts, planNoticeSeen: true,
  });
});

test("Clarify account keeps personal provider controls hidden", async ({ page }) => {
  await navigate(page, "Clarify account");
  await expect(page.getByRole("button", { name: "Models and services", exact: true })).toHaveCount(0);
  await navigate(page, "Style");
  await expect(page.getByRole("combobox", { name: "Cleanup level", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review model and instructions", exact: true })).toHaveCount(0);
});

test("ChatGPT profile models stay available without changing the Style draft", async ({ page }, info) => {
  await selectChatGPT(page);
  await page.getByRole("button", { name: "Continue with ChatGPT", exact: true }).click();
  await page.getByRole("dialog", { name: "You're using your ChatGPT plan", exact: true }).getByRole("button", { name: "Got it", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "You're using your ChatGPT plan", exact: true })).toBeHidden();
  await expect(page.getByRole("dialog", { name: "Settings", exact: true })).toBeVisible();
  await openStyleReview(page, "en");
  const prompt = page.getByRole("textbox", { name: "Instructions", exact: true });
  await prompt.fill("Keep this Style draft.");
  await navigate(page, "Models and services");
  await page.getByRole("button", { name: "Edit Rewriting profile", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Processing profile", exact: true });
  await editor.getByRole("combobox", { name: "Profile service", exact: true }).click();
  await page.getByRole("option", { name: "ChatGPT (subscription)", exact: true }).click();
  await editor.getByRole("combobox", { name: "Profile model", exact: true }).click();
  await expect(page.getByRole("option", { name: "First account model", exact: true })).toBeVisible();
  await expect(page.getByRole("option", { name: "Second account model", exact: true })).toBeVisible();
  await page.getByRole("option", { name: "Second account model", exact: true }).click();
  await page.screenshot({ path: info.outputPath("chatgpt-profile-catalog.png") });
  await editor.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(editor).toBeHidden();
  const saved = await snapshot(page);
  expect(saved.selectedScope).toBe("refinement");
  expect(saved.routePrompt).not.toBe("Keep this Style draft.");
  expect(saved.textActionProfiles.find(profile => profile.id === "legacy-rewrite").modelId).toBe("personal-a");
  await openStyleReview(page, "en");
  await expect(prompt).toHaveValue("Keep this Style draft.");
});
