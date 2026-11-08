import { language, translate } from '../../shared/i18n';

export let uiLanguage = language(navigator.language);
document.documentElement.lang = uiLanguage;
export function setUiLanguage(value?: string) {
  if (!value) return;
  uiLanguage = language(value);
  document.documentElement.lang = uiLanguage;
}
export const t = (source: string, values?: Record<string, string | number>) => translate(source, uiLanguage, values);
