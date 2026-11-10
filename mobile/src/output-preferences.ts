import type { OutputStyle } from '../modules/clarify-core';

export const outputStyles = [
  { value: 'natural', label: 'Manter meu tom' },
  { value: 'formal', label: 'Formal' }, { value: 'casual', label: 'Casual' },
] as const;
export function outputStyleLabel(style: OutputStyle): string {
  return ({ default: 'Padrão', formal: 'Formal', casual: 'Casual', very_casual: 'Muito casual',
    natural: 'Manter meu tom', informal: 'Informal', organized: 'Organizado' })[style];
}
