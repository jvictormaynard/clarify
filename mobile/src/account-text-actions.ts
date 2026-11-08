import type { AccountTextActionDefinition, AccountTextActionLibrary } from '../modules/clarify-core/index.ts';

export function actionReplacement(base: AccountTextActionLibrary, draft: AccountTextActionDefinition, originalID: string | null, remove = false): AccountTextActionDefinition[] {
  const rows = base.actions.map(({ id, name, prompt, kind, enabled }) => ({ id, name, prompt, kind, enabled }));
  if (originalID !== null && !rows.some(row => row.id === originalID)) throw new Error('A ação mudou ou está indisponível. Atualize a lista e tente novamente.');
  const { id, name, prompt, kind, enabled } = draft;
  const value = { id, name, prompt, kind, enabled };
  if (remove) return rows.filter(row => row.id !== originalID);
  if (originalID === null) return [...rows, value];
  return rows.map(row => row.id === originalID ? value : row);
}

export function ownsActionLibrary(library: AccountTextActionLibrary, context: string, computer: boolean, signedIn: boolean): boolean {
  return signedIn && !computer && library.context === context;
}
