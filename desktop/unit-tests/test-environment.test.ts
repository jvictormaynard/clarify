// @vitest-environment node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, isAbsolute, relative } from "node:path";
import { test, vi } from "vitest";
import { browserChannel, createTestEnvironment } from "../scripts/test-environment.mjs";

// Capture these at module evaluation, before any test can repair the environment.
const profileKeys = ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "CLARIFY_DATA_DIR"];
const importProfile = Object.fromEntries(profileKeys.map(key => [key, process.env[key]]));
const importDotenv = process.env.CLARIFY_SKIP_DOTENV;
const importPython = process.env.CLARIFY_TEST_PYTHON;

test("local and CI browsers default to locked Chromium and reject unknown selections", () => {
  vi.stubEnv("CLARIFY_TEST_BROWSER", undefined);
  try {
    assert.equal(browserChannel(), undefined);
    assert.equal(browserChannel("chromium"), undefined);
    assert.equal(browserChannel("msedge"), "msedge");
    assert.throws(() => browserChannel("other"), /must be chromium or msedge/);
  } finally { vi.unstubAllEnvs(); }
});

test("the unit runner isolates profiles before importing test modules", () => {
  assert.equal(importDotenv, "1");
  assert.equal(importPython, undefined);
  const root = dirname(importProfile.CLARIFY_DATA_DIR!);
  for (const path of Object.values(importProfile)) {
    assert.ok(path && isAbsolute(path));
    assert.equal(dirname(path), root);
    assert.ok(existsSync(path));
  }
});

test("a child inherits an isolated profile without keys; disposal also works after failure", async () => {
  for (const key of ["GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "API_KEY", "EXAMPLE_TOKEN", "EXAMPLE_SECRET", "PYTHONPATH", "PYTHONHOME"])
    vi.stubEnv(key, "synthetic-unit-only");
  let environment: Awaited<ReturnType<typeof createTestEnvironment>> | undefined;
  try {
    environment = await createTestEnvironment("clarify-unit-profile-probe-");
    const result = spawnSync(process.execPath, ["--input-type=module", "-e", `
      import assert from 'node:assert/strict';
      import { homedir } from 'node:os';
      assert.equal(homedir(), process.env.USERPROFILE || process.env.HOME);
      for (const key of ['GEMINI_API_KEY','GROQ_API_KEY','OPENAI_API_KEY','API_KEY','EXAMPLE_TOKEN','EXAMPLE_SECRET','PYTHONPATH','PYTHONHOME'])
        assert.equal(process.env[key], undefined);
      assert.equal(process.env.CLARIFY_SKIP_DOTENV, '1');
    `], { env: environment.env, encoding: "utf8", windowsHide: true, timeout: 10000 });
    assert.equal(result.status, 0, result.stderr);
    for (const key of profileKeys) assert.ok(!relative(environment.profile, environment.env[key]!).startsWith(".."));
    await assert.rejects(async () => {
      try { throw new Error("synthetic fixture failure"); }
      finally { await environment!.dispose(); }
    }, /synthetic fixture failure/);
    assert.equal(existsSync(environment.profile), false);
  } finally {
    await environment?.dispose();
    vi.unstubAllEnvs();
  }
});
