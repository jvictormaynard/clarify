import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export function spawnOwned(command, args, options) {
  const { ownDetached = false, ...spawnOptions } = options ?? {};
  if (process.platform !== "win32" && ownDetached) {
    if (process.platform !== "linux") throw new Error("Browser process supervision requires Linux or Windows.");
    const request = Buffer.from(JSON.stringify({ file: command, arguments: args, parent: process.pid })).toString("base64");
    const python = spawnOptions.env?.CLARIFY_TEST_PYTHON ?? process.env.CLARIFY_TEST_PYTHON ?? "python3";
    const child = spawn(python, [fileURLToPath(new URL("./process-job.py", import.meta.url)), request],
      { ...spawnOptions, detached: true });
    child.ownedSubreaper = true;
    return child;
  }
  if (process.platform !== "win32") {
    const child = spawn(command, args, { ...spawnOptions, detached: true });
    // Descendants can keep inherited pipes open after their parent exits.
    // End the group on exit so callers can safely wait for close.
    child.once("exit", () => stopProcessTree(child));
    return child;
  }
  const request = Buffer.from(JSON.stringify({ file: command, arguments: args })).toString("base64");
  const env = { ...(spawnOptions.env ?? process.env) };
  for (const key of Object.keys(env)) if (/^PSModuleAnalysisCachePath$/i.test(key)) delete env[key];
  env.PSModuleAnalysisCachePath = "NUL";
  return spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
    fileURLToPath(new URL("./process-job.ps1", import.meta.url)), "-CommandJson", request],
  { ...spawnOptions, env, detached: false, windowsHide: true });
}

// The caller owns this child. POSIX children must use detached:true so that
// their PID identifies the process group created for this test run.
export function stopProcessTree(child) {
  if (!child.pid) return;
  if (child.ownedSubreaper) {
    // The supervisor returns only after all adopted descendants are reaped.
    // A group signal cannot reach Playwright's separate browser/server sessions.
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
    return;
  }
  if (process.platform === "win32") {
    // spawnOwned's Job Object has already closed after helper exit. Never
    // address a completed Windows process by a PID that can be reused.
    if (child.exitCode !== null || child.signalCode !== null) return;
    const result = spawnSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
      windowsHide: true, stdio: "ignore", timeout: 10000,
    });
    if (result.status !== 0 && child.exitCode === null) child.kill();
  } else {
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  }
}
