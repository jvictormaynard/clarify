import assert from 'node:assert/strict';
import test from 'node:test';
import { errorMessage } from '../src/errors.ts';

test('native account failures show the user message without bridge diagnostics', () => {
  assert.equal(errorMessage(new Error('ACCOUNT_ERROR: Não foi possível salvar a sessão. (at ExpoModulesCore/Promise.swift:65)')), 'Não foi possível salvar a sessão.');
});

test('computer errors show the safe native message without bridge details', () => {
  assert.equal(errorMessage(new Error('COMPUTER_ERROR: O QR expirou. Gere outro QR no computador. (at ExpoModulesCore/Promise.swift:65)')), 'O QR expirou. Gere outro QR no computador.');
  assert.equal(errorMessage(new Error('COMPUTER_LIBRARY: Use o dicionário e os snippets configurados no computador. (at ExpoModulesCore/Promise.swift:65)')), 'Use o dicionário e os snippets configurados no computador.');
});

test('localized bridge failures retain their language and useful punctuation', () => {
  for (const message of ['Could not save the session.', 'No fue posible guardar la sesión.']) {
    assert.equal(errorMessage(new Error(`ACCOUNT_ERROR: ${message} (at ExpoModulesCore/Promise.swift:65)`)), message);
  }
  assert.equal(errorMessage(new Error('SNIPPET_ERROR: Limite: 256 KiB (texto da conta). (at ExpoModulesCore/Promise.swift:65)')), 'Limite: 256 KiB (texto da conta).');
});

test('ordinary user errors retain their message', () => {
  assert.equal(errorMessage(new Error('A conta mudou. Abra os snippets novamente.')), 'A conta mudou. Abra os snippets novamente.');
});

test('text-action preparation errors omit Expo diagnostics', () => {
  assert.equal(errorMessage(new Error('TEXT_ERROR: Select an available action. (at ExpoModulesCore/Promise.swift:65)')), 'Select an available action.');
});

test('unknown and empty failures use the existing retry message', () => {
  for (const error of [null, {}, 'internal failure', new Error(''), new Error('ACCOUNT_ERROR:  (at ExpoModulesCore/Promise.swift:65)')]) {
    assert.equal(errorMessage(error), 'Não foi possível concluir. Tente novamente.');
  }
});
