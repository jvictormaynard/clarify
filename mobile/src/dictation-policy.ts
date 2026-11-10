import type { DictationPolicy, OutputLanguage, TextActionCatalog } from '../modules/clarify-core';

export const dictationModes = [
  { value: 'clarity', label: 'Revisar clareza' },
  { value: 'preserve', label: 'Manter minhas palavras' },
] as const;

export function dictationPolicyLabel(mode: DictationPolicy['mode']): string {
  return { legacy: 'Usar configuração do destino', natural: 'Usar instruções de ditado',
    light: 'Ajustar apenas espaços', clarity: 'Revisar clareza', preserve: 'Manter minhas palavras',
    action: 'Aplicar ação de texto' }[mode];
}

export function dictationPolicyOptions(policy: DictationPolicy | undefined, catalog: TextActionCatalog | undefined,
  computer: boolean, outputLanguage: OutputLanguage = 'auto') {
  const capabilities = catalog?.processingContract;
  const selected = catalog?.textActions.find(action => action.id === policy?.actionID && action.revision === policy?.actionRevision);
  const mode = policy?.mode;
  const editingMode = mode && (mode === 'legacy' || mode === 'natural') && outputLanguage !== 'auto'
    ? `${mode}_translated` as const : mode;
  const editing = capabilities?.dictation_editing;
  const readiness = editingMode && editing && editingMode in editing
    ? editing[editingMode as keyof typeof editing] : undefined;
  const toneAllowed = !!policy && mode !== 'preserve' && mode !== 'light' &&
    capabilities?.cleanup_levels?.includes('clarity') === true &&
    (computer ? readiness === true : readiness !== false) &&
    (mode !== 'action' || !!(selected?.enabled && selected.ready));
  return {
    modes: dictationModes.map(mode => ({ ...mode, supported: !!capabilities?.explicit_dictation_policy &&
      capabilities.cleanup_levels?.includes(mode.value) === true })),
    compatibilityLabel: mode && mode !== 'clarity' && mode !== 'preserve' ? dictationPolicyLabel(mode) : undefined,
    actionsSupported: capabilities?.dictation_actions === true,
    actions: catalog?.textActions.filter(action => action.enabled).map(action => ({ ...action,
      selectable: action.ready && (action.kind !== 'translation' || outputLanguage !== 'auto') })) ?? [],
    selected, toneAllowed,
  };
}
