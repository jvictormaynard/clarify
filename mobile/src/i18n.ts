import Core from '../modules/clarify-core';
import { language, translate } from '../../shared/i18n';

export const uiLanguage = language(Core.uiLanguage);
export const t = (source: string, values?: Record<string, string | number>) => translate(source, uiLanguage, values);
