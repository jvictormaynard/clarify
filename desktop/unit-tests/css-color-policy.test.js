import { expect, test } from "vitest";
import { checkStyles } from "../scripts/check-ui-styles.mjs";

test("color policy permits named grid areas and rejects named colors in paint", () => {
  const css = ".panel { grid-area: chocolate; background: chocolate; }";
  expect(checkStyles(css, "styles/page.css")).toEqual([
    "styles/page.css:1: use a semantic color token instead of chocolate",
  ]);
});
