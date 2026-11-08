import { test } from "@playwright/test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { dictionaryIdentity, unicodeCasefold } from "../src/settings/dictionary-identity";

test("dictionary identity uses the Python domain's Unicode casefold and strip rules", () => {
  assert.ok(process.env.CLARIFY_TEST_PYTHON, "Set CLARIFY_TEST_PYTHON");
  const reference = JSON.parse(execFileSync(process.env.CLARIFY_TEST_PYTHON, ["-c", `
import json, sys, unicodedata
values = ["Straße", "STRASSE", "ΟΣ", "ος", "ı", "I", "İ", "\\u0085Cafe\\u0301\\u001c", "\\ufeffClarify", "Ꭰ", "ꭰ"]
json.dump({"folds": [[code, chr(code).casefold()] for code in range(sys.maxunicode + 1) if chr(code).casefold() != chr(code)], "keys": [[value, unicodedata.normalize("NFC", value.strip()).casefold()] for value in values]}, sys.stdout, ensure_ascii=True)
`], { encoding: "utf8", maxBuffer: 1024 * 1024 }));
  const expected = new Map<number, string>(reference.folds);
  for (let code = 0; code <= 0x10ffff; code++) {
    const scalar = String.fromCodePoint(code);
    assert.equal(unicodeCasefold(scalar), expected.get(code) ?? scalar, `U+${code.toString(16)}`);
  }
  for (const [value, key] of reference.keys) assert.equal(dictionaryIdentity(value), key);
  assert.equal(dictionaryIdentity("Straße"), dictionaryIdentity("STRASSE"));
  assert.notEqual(dictionaryIdentity("ı"), dictionaryIdentity("I"));
});

test("dictionary identity data is current for the pinned Python runtime", () => {
  assert.ok(process.env.CLARIFY_TEST_PYTHON, "Set CLARIFY_TEST_PYTHON");
  execFileSync(process.env.CLARIFY_TEST_PYTHON, ["../scripts/generate_dictionary_identity.py", "--check"], { stdio: "pipe" });
});
