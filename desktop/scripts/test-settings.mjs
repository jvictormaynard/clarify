import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnOwned, stopProcessTree } from "./stop-process-tree.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const args = process.argv.slice(2);
const built = args[0] === "--built";
if (built) args.shift();
// Resolve the download cache before isolating the application profile.
const browserCache = process.env.PLAYWRIGHT_BROWSERS_PATH ?? (
  process.platform === "win32" ? join(process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"), "ms-playwright") :
  process.platform === "darwin" ? join(homedir(), "Library", "Caches", "ms-playwright") :
  join(process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache"), "ms-playwright")
);
const profile = await mkdtemp(join(tmpdir(), "clarify-settings-test-"));
let child;
const stop = () => { if (child) stopProcessTree(child); };
try {
  const env = { ...process.env, PLAYWRIGHT_BROWSERS_PATH: browserCache, QT_QPA_PLATFORM: "offscreen", CLARIFY_SKIP_DOTENV: "1" };
  for (const key of Object.keys(env)) {
    if (/(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY)$/i.test(key) || /^(?:GEMINI_|OPENAI_|GROQ_|REFINEMENT_)/.test(key) || key === "PYTHONPATH" || key === "PYTHONHOME") delete env[key];
  }
  for (const key of ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "CLARIFY_DATA_DIR"]) {
    env[key] = join(profile, key.toLowerCase());
    await mkdir(env[key], { recursive: true });
  }
  // An ephemeral port separates parallel worktrees. strictPort and
  // reuseExistingServer:false make a port race fail instead of using another app.
  if (!env.CLARIFY_TEST_PORT) {
    const reservation = createServer();
    await new Promise((resolve, reject) => reservation.once("error", reject).listen(0, "127.0.0.1", resolve));
    env.CLARIFY_TEST_PORT = String(reservation.address().port);
    await new Promise((resolve, reject) => reservation.close(error => error ? reject(error) : resolve()));
  }
  console.log(`Settings ${built ? "built boot" : "browser suite"}: port ${env.CLARIFY_TEST_PORT}, profile ${profile}`);
  child = spawnOwned(process.execPath, [
    join(root, "node_modules/playwright/cli.js"), "test", "--config",
    built ? "playwright.boot.config.ts" : "playwright.config.ts", ...args,
  ], { cwd: root, env, windowsHide: true, stdio: "inherit", ownDetached: true });
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  try {
    process.exitCode = await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("close", code => resolve(code ?? 1));
    });
  } finally {
    process.removeListener("SIGINT", stop);
    process.removeListener("SIGTERM", stop);
  }
} finally {
  if (child && (child.exitCode === null || process.platform !== "win32")) stop();
  await rm(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
}
