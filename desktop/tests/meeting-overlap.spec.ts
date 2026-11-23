import { expect, test } from "@playwright/test";
import type { Meeting, MeetingState } from "../src/meetings/bridge";
import type { DesktopMessage } from "../src/platform";

test("renders named recovered turns before Stop and keeps the original live transcript", async ({ page }) => {
  const meeting: Meeting = {
    id: "synthetic", title: "Overlap trial", createdAt: 0, updatedAt: 0,
    startedAt: 0, duration: 14, status: "recording", source: "system",
    error: "", hasSummary: false, notes: "", summary: "", segments: [],
    speakers: { 1: "Participant A", 2: "Participant B" },
  };
  const original = { start: 9, end: 12, text: "The yellow barn is nearby." };
  const continuing = { start: 13, end: 14, text: "Capture is still running." };
  const state: MeetingState = {
    supported: true, installed: true, installing: false, installProgress: 0,
    active: meeting, partial: original.text + " " + continuing.text,
    partialTurns: [original, continuing], overlapRevision: 0,
    generating: null, summaryAvailable: false, summaryPending: null, summaryError: null,
    summaryRevision: 0, libraryRevision: 0, error: "", loopback: true,
  };
  await page.addInitScript(({ meeting, state, continuing }) => {
    let detail = meeting;
    let status = state;
    const listeners = new Set<(message: DesktopMessage) => void>();
    let showWindow: (event: string, value?: string) => void;
    window.clarifyDesktop = {
      call: async <T,>(_channel: string, method: string) => (method === "get" ? detail : status) as T,
      subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
      onWindow: listener => { showWindow = listener; return () => {}; },
      window: async () => {},
      ready: async () => {
        showWindow("meeting-locale", "en");
        showWindow("meeting-editor", meeting.id);
      },
    };
    window.addEventListener("synthetic-recovery", () => {
      detail = {
        ...meeting,
        overlapRevision: 1,
        originalSegments: [],
        segments: [
          { start: 9, end: 12, text: "The yellow barn is nearby.", speaker: 2, overlap: true },
          { start: 10, end: 12, text: "We can see the midnight ferry.", speaker: 1, overlap: true },
        ],
      };
      status = { ...state, overlapRevision: 1, projectedPartial: [continuing] };
      listeners.forEach(listener => listener({ event: "meetings", state: status }));
    });
  }, { meeting, state, continuing });
  await page.goto("/?surface=meeting");
  await page.getByRole("tab", { name: "Transcript" }).click();
  const stop = page.getByRole("button", { name: "Stop recording" });
  await expect(stop).toBeEnabled();
  await expect(page.getByText("Recovered voice")).toHaveCount(0);

  await page.evaluate(() => window.dispatchEvent(new Event("synthetic-recovery")));
  await expect(page.getByText("Recovered voice")).toHaveCount(2);
  const pair = page.getByRole("listitem");
  await expect(pair.filter({ hasText: "midnight ferry" })).toContainText("Participant A");
  await expect(pair.filter({ hasText: "yellow barn" })).toContainText("Participant B");
  await expect(pair.filter({ hasText: "midnight ferry" })).toContainText("00:10–00:12");
  await expect(page.getByText("The yellow barn is nearby.", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Capture is still running.", { exact: true })).toBeVisible();
  await expect(stop).toBeEnabled();

  for (const width of [640, 1040]) {
    await page.setViewportSize({ width, height: 760 });
    const originalSwitch = page.getByRole("checkbox", { name: "Show original transcript" });
    await originalSwitch.focus();
    await expect(originalSwitch).toBeFocused();
    await page.keyboard.press("Space");
    await expect(page.getByText("Recovered voice")).toHaveCount(0);
    await expect(page.getByText("The yellow barn is nearby.", { exact: true })).toBeVisible();
    await page.keyboard.press("Space");
    await expect(page.getByText("Recovered voice")).toHaveCount(2);
  }
});

test("only a checked overlap option sends startWithOverlap", async ({ page }) => {
  const starts: string[] = [];
  page.on("console", message => {
    if (message.text().startsWith("meeting-start:")) starts.push(message.text());
  });
  await page.addInitScript(() => {
    const detail: Meeting = {
      id: "synthetic", title: "Overlap trial", createdAt: 0, updatedAt: 0,
      startedAt: null, duration: 0, status: "draft", source: "mic",
      error: "", hasSummary: false, notes: "", summary: "", segments: [],
    };
    const state: MeetingState = {
      supported: true, installed: true, installing: false, installProgress: 0,
      speakersInstalled: true, overlapSupported: true, overlapInstalled: true,
      active: null, partial: "", generating: null, summaryAvailable: false,
      summaryPending: null, summaryError: null, summaryRevision: 0, libraryRevision: 0,
      error: "", loopback: true,
    };
    let showWindow: (event: string, value?: string) => void;
    window.clarifyDesktop = {
      call: async <T,>(_channel: string, method: string, args: unknown[]) => {
        if (method === "start" || method === "startWithOverlap") {
          console.log(`meeting-start:${method}:${args.join(",")}`);
          throw new Error("capture_unavailable");
        }
        return (method === "get" ? detail : state) as T;
      },
      subscribe: () => () => {},
      onWindow: listener => { showWindow = listener; return () => {}; },
      window: async () => {},
      ready: async () => {
        showWindow("meeting-locale", "en");
        showWindow("meeting-editor", detail.id);
      },
    };
  });
  await page.goto("/?surface=meeting");
  await page.getByRole("radio", { name: /Microphone \+ system audio/ }).check();
  const optIn = page.getByRole("checkbox", { name: "Recover overlapping speech" });
  const start = page.getByRole("button", { name: "Start recording" });
  await expect(optIn).not.toBeChecked();
  await start.click();
  await expect.poll(() => starts).toEqual(["meeting-start:start:synthetic,system"]);
  await optIn.focus();
  await page.keyboard.press("Space");
  await expect(optIn).toBeChecked();
  await start.click();
  await expect.poll(() => starts).toEqual([
    "meeting-start:start:synthetic,system",
    "meeting-start:startWithOverlap:synthetic,system",
  ]);
});
