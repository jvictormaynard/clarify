import assert from 'node:assert/strict';
import test from 'node:test';
import { errorMessage } from '../src/errors.ts';

test('native account failures show the user message without bridge diagnostics', () => {
  assert.equal(errorMessage(new Error('ACCOUNT_ERROR: Não foi possível salvar a sessão. (at ExpoModulesCore/Promise.swift:65)')), 'Não foi possível salvar a sessão.');
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

test('unknown and empty failures use the existing retry message', () => {
  for (const error of [null, {}, 'internal failure', new Error(''), new Error('ACCOUNT_ERROR:  (at ExpoModulesCore/Promise.swift:65)')]) {
    assert.equal(errorMessage(error), 'Não foi possível concluir. Tente novamente.');
  }
});
