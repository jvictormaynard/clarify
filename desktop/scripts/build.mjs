import { spawnSync } from "node:child_process";
import { cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join, relative, resolve } from "node:path";
const root = fileURLToPath(new URL("..", import.meta.url));
const generated = mkdtempSync(join(tmpdir(), "clarify-settings-web-"));
const output = resolve(root, "dist");
try {
  for (const [file, args] of [["typescript/bin/tsc", ["--noEmit"]], ["vite/bin/vite.js", ["build", "--outDir", generated, "--emptyOutDir"]]]) {
    const result = spawnSync(process.execPath, [resolve(root, "node_modules", file), ...args], { cwd: root, stdio: "inherit" });
    if (result.status !== 0) {
      process.exitCode = result.status || 1;
      break;
    }
  }
  if (!process.exitCode) {
    if (existsSync(output) && lstatSync(output).isSymbolicLink()) throw new Error("Settings dist must not be a symbolic link.");
    mkdirSync(output, { recursive: true });
    const expected = new Set(readdirSync(generated, { recursive: true }));
    // Remove obsolete outputs, but keep identical files and their timestamps for Cargo.
    for (const entry of readdirSync(output, { recursive: true, withFileTypes: true })) {
      const destination = join(entry.parentPath, entry.name);
      const source = join(generated, relative(output, destination));
      if (!expected.has(relative(output, destination)) || entry.isSymbolicLink() || entry.isDirectory() !== lstatSync(source).isDirectory()) {
        rmSync(destination, { recursive: true, force: true });
      }
    }
    cpSync(generated, output, {
      recursive: true,
      filter: (source, destination) => !lstatSync(source).isFile() || !existsSync(destination) || !readFileSync(source).equals(readFileSync(destination)),
    });
  }
} finally {
  rmSync(generated, { recursive: true, force: true });
}
