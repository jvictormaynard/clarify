import assert from "node:assert/strict";
import { beforeEach, vi } from "vitest";
import { act, type ReactNode } from "react";
import { test, mountPage } from "./support/react-fixture";
import { AccountPage } from "../src/pages/account-page";
import { HistoryPage } from "../src/pages/history-page";
import { setUiLanguage } from "../src/i18n";

beforeEach(() => setUiLanguage("pt"));

// Keep page operation logic and React real. Child controls expose only the
// props/events used by these ownership tests. Browser tests own their DOM,
// focus, accessibility, and interaction acceptance.
vi.mock("../src/components/ui", () => ({
  Button: ({ children, ...props }: { children: ReactNode }) => <button {...props}>{children}</button>,
  Confirm: ({ open, onOpenChange, children }: { open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode }) =>
    <div data-confirm data-open={String(open)}><button data-dismiss onClick={() => onOpenChange(false)} />{children}</div>,
  Section: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  SettingsDisclosure: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  Field: () => null,
  Input: () => null,
}));
vi.mock("../src/components/account-sign-in", () => ({
  AccountSignIn: ({ busy }: { busy: boolean }) => <div data-sign-in data-busy={String(busy)} />,
}));
vi.mock("../src/components/history-entry", () => ({
  HistoryEntryActions: () => null, HistoryComparison: () => null,
}));
vi.mock("../src/components/history-correction-dialog", () => ({ HistoryCorrectionAction: () => null }));
vi.mock("../src/settings/bridge", () => ({
  getHistoryPage: async (context: string) => ({ context, revision: "1",
    entries: [{ id: "row", text: "saved", timestamp: 1, sourceDevice: "desktop", truncated: false }], cursor: "" }),
}));

const account = { endpoint: "https://example.test", email: "", signedIn: false, busy: false, pending: "", usage: {} };
const flush = async () => { await act(async () => {}); };
const confirmation = (h: ReturnType<typeof mountPage>) => h.container.querySelector<HTMLElement>("[data-confirm]")!;
const buttons = (h: ReturnType<typeof mountPage>) => [...confirmation(h).querySelectorAll<HTMLButtonElement>("button:not([data-dismiss])")];
const button = (h: ReturnType<typeof mountPage>, label: string) => [...h.container.querySelectorAll("button")].find(node => node.textContent === label)!;
const dismiss = (h: ReturnType<typeof mountPage>) => confirmation(h).querySelector<HTMLButtonElement>("[data-dismiss]")!.click();

test("Account Continue ignores unrelated global busy and respects its own operation", async () => {
  const controller = { state: { accountState: account }, run: async () => true, dirty: false, busy: true, accountPending: false };
  const h = mountPage(AccountPage, controller);
  assert.equal(h.container.querySelector<HTMLElement>("[data-sign-in]")!.dataset.busy, "false");
  assert.equal(h.container.querySelector("fieldset")!.disabled, false);
  controller.accountPending = true; h.render();
  assert.equal(h.container.querySelector<HTMLElement>("[data-sign-in]")!.dataset.busy, "true");
  assert.equal(h.container.querySelector("fieldset")!.disabled, true);
  controller.accountPending = false; controller.dirty = true; h.render();
  assert.equal(h.container.querySelector("fieldset")!.disabled, true);
});

test("History Cancel ignores global busy; only its own deletion prevents repeat or dismissal", async () => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; }); let calls = 0;
  const controller = { state: { historyState: { context: "guest", revision: "1" } }, busy: true,
    run: async () => { calls++; await gate; return true; } };
  const h = mountPage(HistoryPage, controller); await flush(); h.render();
  h.container.querySelector<HTMLButtonElement>('[aria-label="Excluir transcrição"]')!.click(); h.render();
  assert.equal(buttons(h)[0].disabled, false); assert.equal(buttons(h)[1].disabled, false);
  const submit = buttons(h)[1]; submit.click();
  assert.equal(submit.disabled, false, "repeat event precedes the pending-state render");
  submit.click(); h.render();
  assert.equal(calls, 1); assert.equal(buttons(h)[0].disabled, true); assert.equal(buttons(h)[1].disabled, true);
  dismiss(h); h.render(); assert.equal(confirmation(h).dataset.open, "true");
  release(); await flush(); h.render(); assert.equal(confirmation(h).dataset.open, "false");
});

test("Account confirmation Cancel stays available for unrelated busy state and drafts", async () => {
  const controller = { state: { accountState: { ...account, signedIn: true } }, run: async () => true,
    dirty: false, busy: true, accountPending: false };
  const h = mountPage(AccountPage, controller);
  button(h, "Sair da conta").click(); h.render();
  assert.equal(confirmation(h).dataset.open, "true"); assert.equal(buttons(h)[0].disabled, false);
  controller.dirty = true; h.render();
  assert.equal(buttons(h)[0].disabled, false); assert.equal(buttons(h)[1].disabled, true);
  controller.dirty = false; controller.accountPending = true; controller.state.accountState.busy = true; h.render();
  assert.equal(buttons(h)[0].disabled, false); assert.equal(buttons(h)[1].disabled, true);
  dismiss(h); h.render(); assert.equal(confirmation(h).dataset.open, "false");
});

test("Account destructive submission alone blocks dismissal and duplicate confirmation", async () => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; }); let calls = 0;
  const controller = { state: { accountState: { ...account, signedIn: true } },
    run: async () => { calls++; await gate; return true; }, dirty: false, busy: false, accountPending: false };
  const h = mountPage(AccountPage, controller);
  button(h, "Sair da conta").click(); h.render();
  const submit = buttons(h)[1]; submit.click();
  assert.equal(submit.disabled, false, "repeat event precedes the pending-state render");
  submit.click(); h.render();
  assert.equal(calls, 1); assert.equal(buttons(h)[0].disabled, true);
  dismiss(h); h.render(); assert.equal(confirmation(h).dataset.open, "true");
  release(); await flush(); h.render(); assert.equal(confirmation(h).dataset.open, "false");
});

test("Account social cancellation remains available during active login and local drafts", async () => {
  const calls: unknown[][] = [];
  const controller = { state: { accountState: { ...account, busy: true, socialPending: true } },
    run: async (...args: unknown[]) => { calls.push(args); return true; }, dirty: true, busy: true, accountPending: false };
  const h = mountPage(AccountPage, controller);
  const cancel = button(h, "Cancelar login"); assert.equal(cancel.disabled, false);
  cancel.click(); await flush();
  assert.deepEqual(calls, [["accountCommand", "cancel-social", ""]]);
});
