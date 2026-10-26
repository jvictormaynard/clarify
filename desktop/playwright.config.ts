import { defineConfig } from "@playwright/test";
const port = Number(process.env.CLARIFY_TEST_PORT ?? 1420);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("CLARIFY_TEST_PORT must be a TCP port from 1 to 65535.");
}
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests", workers: 1, timeout: 30000,
  use: { locale: "pt-BR", baseURL, channel: process.env.CLARIFY_TEST_BROWSER === "chromium" ? undefined : "msedge", headless: true, viewport: { width: 1040, height: 760 } },
  webServer: { command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port} --strictPort`, url: baseURL, reuseExistingServer: false },
});
