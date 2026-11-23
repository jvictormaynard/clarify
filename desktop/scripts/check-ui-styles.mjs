import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import colorNames from "color-name";
import postcss from "postcss";
import valueParser from "postcss-value-parser";

// These files own palettes or fixed provider/product illustrations, not app controls.
const literalOwners = new Set([
  "styles/tokens.css", "styles/shared-colors.css", "styles/provider-brands.css", "styles/feature-guide.css", "styles/mobile-app-card.css",
]);
const colorFunctions = /^(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|device-cmyk)$/i;
// Named colors are also valid layout identifiers. Limit them to color-bearing properties.
const colorProperties = /^(?:color|.*-color|background(?:-image)?|border(?:-(?:top|right|bottom|left|block(?:-start|-end)?|inline(?:-start|-end)?))?|outline|(?:box|text)-shadow|filter|backdrop-filter|fill|stroke|text-decoration|column-rule|list-style(?:-image)?)$/i;

export function checkStyles(source, filename) {
  if (literalOwners.has(filename.replaceAll("\\", "/"))) return [];
  const failures = [];
  postcss.parse(source, { from: filename }).walkDecls(declaration => {
    let literal;
    valueParser(declaration.value).walk(node => {
      if (node.type === "function") {
        if (node.value.toLowerCase() === "url") return false;
        if (colorFunctions.test(node.value)) literal = `${node.value}(…)`;
      }
      if (node.type === "word" && (/^#[\da-f]{3,8}$/i.test(node.value)
        || (colorProperties.test(declaration.prop) && Object.hasOwn(colorNames, node.value.toLowerCase())))) literal = node.value;
    });
    if (literal) failures.push(`${filename}:${declaration.source.start.line}: use a semantic color token instead of ${literal}`);
  });
  return failures;
}

function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : path.endsWith(".css") ? [path] : [];
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = fileURLToPath(new URL("../src", import.meta.url));
  const failures = files(root).filter(path => !relative(root, path).replaceAll("\\", "/").startsWith("assets/inter/"))
    .flatMap(path => checkStyles(readFileSync(path, "utf8"), relative(root, path)));
  if (failures.length) {
    console.error(failures.join("\n"));
    process.exitCode = 1;
  }
}
