export function errorMessage(error: unknown): string {
  const fallback = 'Não foi possível concluir. Tente novamente.';
  if (!(error instanceof Error)) return fallback;
  let message = error.message.trim();
  // Expo includes its native promise code and source location in this message.
  const bridgeCode = /^(?:ACCOUNT_ERROR|ACCOUNT_BUSY|DICTIONARY_ERROR|SNIPPET_ERROR|KEYBOARD_TEST):\s*/;
  if (bridgeCode.test(message)) {
    message = message.replace(bridgeCode, '').replace(/\s*\(at ExpoModulesCore\/Promise\.swift:\d+\)$/, '').trim();
  }
  return message || fallback;
}
