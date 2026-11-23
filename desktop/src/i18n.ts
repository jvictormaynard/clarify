import { language, translate, type Language } from "../../shared/i18n";
import onboardingLocales from "./onboarding-locales.json";

function interfaceLanguage(value: string): Language | "de" | "ru" {
  const primary = value.toLowerCase().split(/[-_]/)[0];
  return primary === "de" || primary === "ru" ? primary : language(value);
}

export let uiLanguage = interfaceLanguage(navigator.language);
document.documentElement.lang = uiLanguage;

export function setUiLanguage(value?: string) {
  if (!value) return;
  uiLanguage = interfaceLanguage(value);
  document.documentElement.lang = uiLanguage;
}

export function t(source: string, values?: Record<string, string | number>) {
  if (uiLanguage === "de" || uiLanguage === "ru") {
    const localized = onboardingLocales[source as keyof typeof onboardingLocales]?.[uiLanguage];
    return translate(localized ?? source, "en", values);
  }
  return translate(source, uiLanguage, values);
}
