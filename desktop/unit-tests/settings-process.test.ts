// @vitest-environment node
import { test, expect, vi } from "vitest";
import { SettingsProcess } from "../tests/settings-process";

const program = `
const lines = require('node:readline').createInterface({ input: process.stdin });
lines.on('line', line => {
  const request = JSON.parse(line);
  if (request.method === 'quit' || request.method === 'crash') process.exit(0);
  if (request.method === 'invalid') { console.log('not json'); return; }
  if (request.method === 'hold') return;
  console.log(JSON.stringify({ id: request.id, result: request.args }));
});
`;
const start = () => new SettingsProcess(process.execPath, ["-e", program], process.env);

test("controller replies belong to their request and each test owns its process", async () => {
  const first = start(), second = start();
  try {
    const held = expect(first.request({ method: "hold" })).rejects.toThrow("stopped");
    expect(await first.request({ method: "echo", args: ["first"] })).toMatchObject({ result: ["first"] });
    expect(await second.request({ method: "echo", args: ["second"] })).toMatchObject({ result: ["second"] });
    await first.stop(); await held;
    expect(first.child.exitCode !== null || first.child.signalCode !== null).toBe(true);
    expect(await second.request({ method: "echo", args: ["still running"] })).toMatchObject({ result: ["still running"] });
  } finally { await Promise.all([first.stop(), second.stop()]); }
});

for (const method of ["crash", "invalid"] as const) {
  test(`controller ${method} rejects all waiting requests and future requests`, async () => {
    const controller = start();
    try {
      const held = expect(controller.request({ method: "hold" })).rejects.toThrow();
      await expect(controller.request({ method })).rejects.toThrow();
      await held;
      await expect(controller.request({ method: "echo" })).rejects.toThrow();
    } finally { await controller.stop(); }
  });
}

test("failed controller spawn rejects requests and cleanup completes", async () => {
  const controller = new SettingsProcess("clarify-missing-test-executable", [], process.env);
  try { await expect(controller.request({ method: "echo" })).rejects.toThrow(); }
  finally { await controller.stop(); }
});

test("cleanup kills an unresponsive controller and waits for it to close", async () => {
  const unresponsive = program.replace("request.method === 'quit' || ", "") + "\nsetInterval(() => {}, 1000);";
  const controller = new SettingsProcess(process.execPath, ["-e", unresponsive], process.env);
  try {
    await controller.request({ method: "echo" });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const stopping = controller.stop();
    vi.advanceTimersByTime(5_000);
    await stopping;
    expect(controller.child.exitCode !== null || controller.child.signalCode !== null).toBe(true);
  } finally {
    vi.useRealTimers();
    await controller.stop();
  }
});
