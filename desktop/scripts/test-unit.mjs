import { fileURLToPath } from "node:url";
import { createTestEnvironment } from "./test-environment.mjs";
import { spawnOwned, stopProcessTree } from "./stop-process-tree.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const environment = await createTestEnvironment();
delete environment.env.CLARIFY_TEST_PYTHON;
delete environment.env.CLARIFY_TEST_FIXTURE;
let child;
const stop = () => { if (child) stopProcessTree(child); };
try {
  // Only Node and the locked unit dependencies run in this child. No Vite
  // development server, Python controller, or Playwright browser starts here.
  child = spawnOwned(process.execPath, [
    fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url)),
    "run", "--config", "vitest.config.ts", ...process.argv.slice(2),
  ], { cwd: root, env: environment.env, windowsHide: true, stdio: "inherit", detached: process.platform !== "win32" });
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  process.exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", code => resolve(code ?? 1));
  });
} finally {
  process.removeListener("SIGINT", stop);
  process.removeListener("SIGTERM", stop);
  // Vitest closes its worker pool on normal exit. Kill the owned process group
  // on POSIX too, so an abnormal child exit cannot leave descendants running.
  if (child && (child.exitCode === null || process.platform !== "win32")) stop();
  await environment.dispose();
}
