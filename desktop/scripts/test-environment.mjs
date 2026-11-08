import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

export function browserChannel(value = process.env.CLARIFY_TEST_BROWSER ?? "chromium") {
  if (value === "chromium") return undefined;
  if (value === "msedge") return "msedge";
  throw new Error("CLARIFY_TEST_BROWSER must be chromium or msedge.");
}

// Create this environment before loading application modules or starting a runner.
// The caller owns disposal, including on a failed run or an interrupted child.
export async function createTestEnvironment(prefix = "clarify-settings-unit-") {
  const profile = await mkdtemp(join(tmpdir(), prefix));
  try {
    const env = { ...process.env };
    for (const key of Object.keys(env)) {
      if (/(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY)$/i.test(key) ||
          /^(?:GEMINI_|OPENAI_|GROQ_|REFINEMENT_)/i.test(key) ||
          /^(?:PYTHONPATH|PYTHONHOME|NODE_OPTIONS)$/i.test(key)) delete env[key];
    }
    for (const key of ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "CLARIFY_DATA_DIR"]) {
      env[key] = join(profile, key.toLowerCase());
      await mkdir(env[key], { recursive: true });
    }
    env.CLARIFY_SKIP_DOTENV = "1";
    env.PYTHONDONTWRITEBYTECODE = "1";
    return { profile, env, dispose: () => rm(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 }) };
  } catch (error) {
    await rm(profile, { recursive: true, force: true });
    throw error;
  }
}
