import assert from "node:assert/strict";
import { Button } from "../src/components/ui";
import { test, mountPage } from "./support/react-fixture";

test("a loading action keeps focus and blocks repeated pointer and keyboard activation", () => {
  let calls = 0;
  const controller = { loading: false, disabled: false };
  function Probe({ controller: state }: { controller: typeof controller }) {
    return <Button loading={state.loading} disabled={state.disabled} onClick={() => calls++}>Refresh</Button>;
  }
  const page = mountPage(Probe, controller);
  const button = page.container.querySelector("button")!;
  button.focus();
  controller.loading = true;
  page.render();
  assert.equal(document.activeElement, button);
  assert.equal(button.disabled, false);
  assert.equal(button.getAttribute("aria-busy"), "true");
  button.click();
  const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
  button.dispatchEvent(event);
  assert.equal(event.defaultPrevented, true);
  assert.equal(calls, 0);
  controller.loading = false;
  page.render();
  button.click();
  assert.equal(calls, 1);
  controller.disabled = true;
  page.render();
  assert.equal(button.disabled, true);
});
