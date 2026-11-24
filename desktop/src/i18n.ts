import { language, translate, type Language } from "../../shared/i18n";
import navigationLocales from "./settings/navigation-locales.json";
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
  const locale = uiLanguage === "de" || uiLanguage === "ru" ? "en" : uiLanguage;
  const navigation = navigationLocales[source as keyof typeof navigationLocales]?.[locale];
  const onboarding = uiLanguage === "de" || uiLanguage === "ru"
    ? onboardingLocales[source as keyof typeof onboardingLocales]?.[uiLanguage]
    : undefined;
  return translate(navigation ?? onboarding ?? source, locale, values);
}
