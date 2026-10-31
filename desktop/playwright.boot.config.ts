import { defineConfig } from "@playwright/test";
import browserConfig from "./playwright.config";

export default defineConfig({
  ...browserConfig,
  testDir: "./boot-tests",
  outputDir: "./test-results/boot",
  use: { ...browserConfig.use, channel: undefined, trace: "retain-on-failure" },
  webServer: {
    command: "node scripts/serve-built.mjs",
    url: browserConfig.use!.baseURL,
    reuseExistingServer: false,
    timeout: 15000,
  },
});
