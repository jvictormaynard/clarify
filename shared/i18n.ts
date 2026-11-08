import messages from './ui_strings.json';

export type Language = 'pt' | 'en' | 'es';
export function language(value: string | undefined): Language {
  const primary = (value || '').toLowerCase().replace('_', '-').split('-')[0];
  return primary === 'pt' || primary === 'es' ? primary : 'en';
}
export function translate(source: string, locale: Language, values: Record<string, string | number> = {}): string {
  const entry = (messages as Record<string, Record<Language, string>>)[source];
  return (entry?.[locale] ?? source).replace(/\{(\w+)\}/g, (token, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : token);
}
