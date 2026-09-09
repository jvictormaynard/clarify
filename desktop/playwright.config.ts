import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests", workers: 1, timeout: 30000,
  use: { baseURL: "http://127.0.0.1:1420", channel: "msedge", headless: true, viewport: { width: 1040, height: 760 } },
  webServer: { command: "node node_modules/vite/bin/vite.js --host 127.0.0.1", url: "http://127.0.0.1:1420", reuseExistingServer: false },
});
