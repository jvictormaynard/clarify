import assert from "node:assert/strict";

// Install before navigation so entry scripts and later chunk imports are covered.
export function observeBuiltBoot(page) {
  const errors = [];
  page.on("pageerror", error => errors.push(`pageerror: ${error.message}`));
  page.on("console", message => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("requestfailed", request => errors.push(`requestfailed: ${request.url()} ${request.failure()?.errorText}`));
  page.on("response", response => {
    if (response.status() >= 400) errors.push(`HTTP ${response.status()}: ${response.url()}`);
  });
  return {
    errors,
    assertHealthy() { assert.equal(errors.length, 0, `Built Settings boot failed:\n${errors.join("\n")}`); },
  };
}
