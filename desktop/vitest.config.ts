import { defineConfig } from "vitest/config";

export default defineConfig({
  // Keep this independent from the development server and its CSS plugins.
  oxc: { jsx: { runtime: "automatic" } },
  test: {
    include: ["unit-tests/**/*.test.{js,ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./unit-tests/support/setup.ts"],
    fileParallelism: false,
    restoreMocks: true,
  },
});
