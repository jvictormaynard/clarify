import type { OutputStyle } from '../modules/clarify-core';

export const outputStyles = [
  { value: 'default', label: 'Padrão' },
  { value: 'formal', label: 'Formal' }, { value: 'casual', label: 'Casual' },
  { value: 'very_casual', label: 'Muito casual' },
] as const;
export function outputStyleLabel(style: OutputStyle): string {
  return ({ default: 'Padrão', formal: 'Formal', casual: 'Casual', very_casual: 'Muito casual',
    natural: 'Natural', informal: 'Informal', organized: 'Organizado' })[style];
}
export const visibleOutputStyle = (style: OutputStyle) => style;
