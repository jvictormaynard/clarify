import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
const root = fileURLToPath(new URL("..", import.meta.url));
for (const [file, args] of [["typescript/bin/tsc", ["--noEmit"]], ["vite/bin/vite.js", ["build"]]]) {
  const result = spawnSync(process.execPath, [resolve(root, "node_modules", file), ...args], { cwd: root, stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status || 1);
}
